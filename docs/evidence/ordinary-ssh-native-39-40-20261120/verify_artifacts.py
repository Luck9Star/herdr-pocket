"""Verify the six GitHub evidence ZIPs without extracting them."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def require(condition, label):
    if not condition:
        raise ValueError(label)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def report_value(report, path):
    for key in path.split('.'):
        report = report[int(key)] if isinstance(report, list) else report[key]
    return report


def verify_archive(directory, case, fields):
    path = directory / f"{case['run']}-{case['artifact']}.zip"
    bits = path.read_bytes()
    require(len(bits) == case['archive_bytes'] and sha256(bits) == case['archive_sha256'], 'ZIP size or SHA-256')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) == case['zip_members'], 'ZIP members')
        require(archive.testzip() is None, 'ZIP member CRC')
        info = archive.getinfo(case['report_path'])
        report_bits = archive.read(info)
        require(f'{info.CRC:08x}' == case['report_crc32'] and sha256(report_bits) == case['report_sha256'],
                'report CRC or SHA-256')
        report = json.loads(report_bits)
        require(report['sourceSHA'] == case['source'] and report['status'] == 'passed', 'report source or status')
        for report_path, expected in case['facts'].items():
            require(report_value(report, report_path) == expected, report_path)
        for report_path, expected in case.get('connections', {}).items():
            actual = [[event[field] for field in fields] for event in report_value(report, report_path)]
            require(actual == expected, report_path)
        image = case.get('image_properties')
        if image:
            properties = dict(line.split('=', 1) for line in archive.read(image['path']).decode().splitlines() if '=' in line)
            require(all(properties.get(key) == value for key, value in image['values'].items()), 'AVD image properties')


def verify_github(repository, case):
    def get(endpoint):
        return json.loads(subprocess.check_output(['gh', 'api', f'repos/{repository}/actions/{endpoint}']))

    run = get(f"runs/{case['run']}")
    job = get(f"jobs/{case['job']}")
    artifact = get(f"artifacts/{case['artifact']}")
    require((run['head_sha'], run['conclusion'], run['run_attempt'], Path(run['path']).name) ==
            (case['source'], 'success', case['attempt'], case['workflow']), 'GitHub run')
    require((job['run_id'], job['head_sha'], job['conclusion']) ==
            (case['run'], case['source'], 'success'), 'GitHub job')
    require((artifact['workflow_run']['id'], artifact['workflow_run']['head_sha'], artifact['name'],
             artifact['size_in_bytes'], artifact['digest']) ==
            (case['run'], case['source'], case['archive_name'], case['archive_bytes'],
             'sha256:' + case['archive_sha256']), 'GitHub artifact')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='directory containing <run>-<artifact>.zip')
    parser.add_argument('--github', action='store_true', help='also check the live GitHub API using gh')
    args = parser.parse_args()
    index = json.loads(Path(__file__).with_name('official-index.json').read_bytes())
    for case in index['runs']:
        label = f"{case['client']}/{case['platform']} {case['run']}/{case['artifact']}"
        try:
            verify_archive(args.directory, case, index['connection_fields'])
            if args.github:
                verify_github(index['repository'], case)
        except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
            parser.exit(1, f'{label} failed: {error}\n')
        print(f"{label} OK ({case['zip_members']} ZIP members)")


if __name__ == '__main__':
    main()
