#!/usr/bin/env python3
"""Explicit experimental dependency in a disposable generated CI app, never pub cache."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def generated_app(destination):
    destination = destination.resolve()
    runner = os.environ.get('RUNNER_TEMP')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or not runner:
        raise ValueError('Candidate application is CI-only')
    base = Path(runner).resolve()
    if destination == base or not destination.is_relative_to(base):
        raise ValueError('Expected a generated app strictly under RUNNER_TEMP')
    marker = destination / '.herdr-generated-probe.json'
    if marker.is_symlink() or not marker.is_file():
        raise ValueError('Missing isolated scaffold marker')
    if json.loads(marker.read_text(encoding='utf-8')).get('kind') != 'herdr-flutter-validation':
        raise ValueError('Wrong scaffold marker')
    return destination


def apply(destination):
    destination = generated_app(destination)
    target = destination / 'candidate/terminal_view'
    overrides = destination / 'pubspec_overrides.yaml'
    if (target.exists() or target.is_symlink() or overrides.exists() or overrides.is_symlink()
            or (destination / 'candidate').is_symlink()):
        raise ValueError('Refusing existing candidate or dependency overrides')
    metadata = json.loads((SOURCE / 'patches/manifest.json').read_text(encoding='utf-8'))
    patch = SOURCE / 'patches' / metadata['patch']
    if digest(patch.read_bytes()) != metadata['patchSha256']:
        raise ValueError('Patch checksum mismatch')
    with urllib.request.urlopen(metadata['archiveUrl'], timeout=60) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    if len(archive) > 64 * 1024 * 1024 or digest(archive) != metadata['archiveSha256']:
        raise ValueError('Official archive checksum/size mismatch')
    target.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
        members = bundle.getmembers()
        if any(not (m.isfile() or m.isdir()) for m in members):
            raise ValueError('Unexpected link or special file in pinned archive')
        if sum(m.size for m in members) > 64 * 1024 * 1024:
            raise ValueError('Archive extraction exceeds limit')
        bundle.extractall(target, filter='data')
    for name, hashes in metadata['files'].items():
        if digest((target / name).read_bytes()) != hashes['beforeSha256']:
            raise ValueError('Unexpected upstream source: ' + name)
    for check in [True, False]:
        subprocess.run(['git', 'apply', *(['--check'] if check else []), str(patch)],
                       cwd=target, check=True)
    for name, hashes in metadata['files'].items():
        if digest((target / name).read_bytes()) != hashes['afterSha256']:
            raise ValueError('Unexpected patched source: ' + name)
    overrides.write_text('dependency_overrides:\n  terminal_view:\n    path: candidate/terminal_view\n', encoding='utf-8')
    options = destination / 'analysis_options.yaml'
    options.write_text(options.read_text(encoding='utf-8').replace(
        'analyzer:\n', 'analyzer:\n  exclude:\n    - candidate/**\n', 1), encoding='utf-8')
    metadata.update({'sourceCommit': os.environ.get('GITHUB_SHA'),
                     'variant': 'experimental-patched',
                     'baselineLockSha256': digest((SOURCE / 'pubspec.lock').read_bytes())})
    (destination / 'candidate-manifest.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'variant': metadata['variant'], 'patchSha256': metadata['patchSha256']}))


def lock_packages(text):
    """Read pub's stable package blocks without executing YAML or accepting custom types."""
    packages = {}
    name = None
    for line in text.splitlines():
        if line == 'sdks:':
            break
        found = re.fullmatch(r'  ([a-zA-Z0-9_]+):', line)
        if found:
            name = found.group(1)
            if name in packages:
                raise ValueError('Duplicate package in lock')
            packages[name] = []
        elif name is not None:
            packages[name].append(line)
    if 'terminal_view' not in packages:
        raise ValueError('No terminal candidate in lock')
    return {name: '\n'.join(lines) for name, lines in packages.items()}


def verify_lock(destination):
    destination = generated_app(destination)
    baseline = lock_packages((SOURCE / 'pubspec.lock').read_text(encoding='utf-8'))
    resolved = lock_packages((destination / 'pubspec.lock').read_text(encoding='utf-8'))
    if baseline.keys() != resolved.keys():
        raise ValueError('Transitive package set changed')
    for name in baseline:
        if name != 'terminal_view' and baseline[name] != resolved[name]:
            raise ValueError('Transitive dependency drift: ' + name)
    candidate = resolved['terminal_view']
    for required in ['    source: path', '    version: "0.5.0"',
                     '      path: "candidate/terminal_view"', '      relative: true']:
        if required not in candidate.splitlines():
            raise ValueError('Unexpected candidate lock description: ' + required)
    manifest_file = destination / 'candidate-manifest.json'
    metadata = json.loads(manifest_file.read_text(encoding='utf-8'))
    metadata['candidateLockSha256'] = digest((destination / 'pubspec.lock').read_bytes())
    metadata['transitiveLockComparison'] = 'identical except terminal_view explicit path source'
    manifest_file.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print('Candidate lock verified; every other dependency block unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['apply', 'verify-lock'])
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    (apply if args.command == 'apply' else verify_lock)(args.destination)
