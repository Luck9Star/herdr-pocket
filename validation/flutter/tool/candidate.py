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
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import terminal_view_ime

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
    regression = metadata.get('selectorRegression')
    regression_source = None
    regression_wrapper = destination / 'test/candidate_selector_preservation_test.dart'
    if regression is not None:
        # Candidate-only: the fixed baseline must retain its original results.
        if regression.get('source') != 'regression/selector_preservation.dart':
            raise ValueError('Unexpected selector regression source')
        regression_source = SOURCE / regression['source']
        if digest(regression_source.read_bytes().replace(b'\r\n', b'\n')) != regression['sha256']:
            raise ValueError('Selector regression checksum mismatch')
        existing = destination / regression['source']
        if (regression_wrapper.exists() or regression_wrapper.is_symlink()
                or (destination / 'test').is_symlink()
                or (destination / 'regression').is_symlink()
                or existing.is_symlink()
                or (existing.exists() and digest(existing.read_bytes().replace(b'\r\n', b'\n')) != regression['sha256'])):
            raise ValueError('Refusing existing or changed candidate regression')
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
        subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
                        'apply', *(['--check'] if check else []), str(patch)],
                       cwd=target, check=True)
    for name, hashes in metadata['files'].items():
        if digest((target / name).read_bytes()) != hashes['afterSha256']:
            raise ValueError('Unexpected patched source: ' + name)
    ime_metadata = terminal_view_ime.apply_shim(target, SOURCE)
    for name, expected in metadata.get('upstreamLicenseFiles', {}).items():
        if name not in ('LICENSE', 'NOTICE') or digest((target / name).read_bytes()) != expected:
            raise ValueError('Unexpected upstream license file')
    if regression_source is not None:
        staged = destination / regression['source']
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(regression_source.read_bytes())
        regression_wrapper.parent.mkdir(parents=True, exist_ok=True)
        regression_wrapper.write_text(
            "import 'package:flutter_test/flutter_test.dart';\n"
            "import '../regression/selector_preservation.dart' as selector;\n\n"
            "void main() {\n"
            "  test('candidate preserves ordered selectors, combining suffixes and copy fixtures', () {\n"
            "    selector.runSelectorPreservationChecks();\n"
            "  });\n"
            "}\n", encoding='utf-8')
        metadata['selectorRegressionWrapperSha256'] = digest(regression_wrapper.read_bytes())
    overrides.write_text('dependency_overrides:\n  terminal_view:\n    path: candidate/terminal_view\n', encoding='utf-8')
    options = destination / 'analysis_options.yaml'
    options_text = options.read_text(encoding='utf-8')
    if '    - candidate/**\n' not in options_text:
        options_text = options_text.replace('analyzer:\n', 'analyzer:\n  exclude:\n    - candidate/**\n', 1)
    options.write_text(options_text, encoding='utf-8')
    metadata['imeObservation'] = ime_metadata
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
    metadata['transitiveLockComparison'] = 'package blocks identical except terminal_view explicit path source; SDK footer recorded separately'
    def sdk_footer(path):
        text = path.read_text(encoding='utf-8')
        return text.split('\nsdks:\n', 1)[1] if '\nsdks:\n' in text else ''
    before_sdk = sdk_footer(SOURCE / 'pubspec.lock')
    after_sdk = sdk_footer(destination / 'pubspec.lock')
    metadata['sdkConstraintComparison'] = {'baseline': before_sdk, 'candidate': after_sdk,
                                           'identical': before_sdk == after_sdk,
                                           'actualFlutterVersionPinned': '3.47.9'}
    manifest_file.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print('Candidate lock verified; every other dependency block unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['apply', 'verify-lock'])
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    (apply if args.command == 'apply' else verify_lock)(args.destination)
