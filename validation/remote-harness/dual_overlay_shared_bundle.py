#!/usr/bin/env python3
"""Assemble and verify a same-revision, build-only Linux fixture bundle.

Only three executables and their public provenance are retained. No fixture is
started and no runtime identity, authorization, peer state or SSH config is
copied. CI artifact transport and the checked-out source SHA remain part of the
trust boundary; a self-authored hash alone is not source authentication.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))
sys.path.insert(0, str(ROOT / 'validation/native/tool'))
import tailscale_candidate as ts_candidate

spec = importlib.util.spec_from_file_location('shared_input_bootstrap', HARNESS / 'run-ci.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

NAMES = ('herdr', 'peer', 'ts-fixture')
TOOLCHAINS = {'easytierRust': '1.95.0', 'guardedHerdrRust': '1.96.0', 'tailscaleGo': '1.27.1'}
MATERIALS = (
    'validation/native/patches/portable-manifest.json',
    'validation/native/tailscale-runtime-source.json',
    'validation/native/tailscale-runtime/go.mod',
    'validation/native/tailscale-runtime/go.sum',
    'validation/native/patches/0002-tsnet-explicit-auth.patch',
    'validation/native/patches/tsdial-overlay-only-test.go',
    'validation/remote-harness/easytier_peer.rs',
    'validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch',
)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def materials():
    files = list(MATERIALS)
    files.extend(str(path.relative_to(ROOT)) for path in sorted(
        (ROOT / 'validation/native/tailscale-runtime/fixture').glob('*.go')))
    return {name: digest(ROOT / name) for name in files}


def checked_file(path, max_bytes=200 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise ValueError('bundle_file_invalid')
    return path


def checked_elf(path, max_bytes=200 * 1024 * 1024):
    checked_file(path, max_bytes)
    with path.open('rb') as source:
        header = source.read(20)
    if (len(header) < 20 or header[:6] != b'\x7fELF\x02\x01'
            or struct.unpack_from('<HH', header, 16) not in ((2, 62), (3, 62))):
        raise ValueError('linux_x86_64_executable_required')
    return path


def exact_inventory(root, expected):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('bundle_directory_invalid')
    actual = {path.name for path in root.iterdir()}
    if actual != set(expected) or any(path.is_symlink() or not path.is_file() for path in root.iterdir()):
        raise ValueError('bundle_inventory_invalid')


def sha_source(expected):
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{40}', expected) or actual != expected:
        raise ValueError('checked_out_source_mismatch')
    return expected


def record_peers(et_bundle, et_evidence, ts_work, fixture, output, source_sha):
    report = json.loads(checked_file(et_evidence / 'manifest.json').read_text())
    provenance = report.get('provenance', {})
    # Debug Rust output can exceed the publish limit. Verify its original hash
    # first, then strip debug info from a separate copy before packaging.
    peer = checked_elf(et_bundle / 'peer', max_bytes=2 * 1024 * 1024 * 1024)
    if (report.get('status') != 'prepared' or report.get('sourceSHA') != source_sha
            or provenance.get('peerBinarySha256') != digest(peer)
            or provenance.get('heelerCommit') != '6a2817fc02aeb552df251d9478753c22fd4738bb'
            or provenance.get('easytierCommit') != '728ba94b5029240add6204eed591f22e4e039e6b'):
        raise ValueError('easytier_peer_provenance_invalid')
    fixed = ts_candidate.verify_sources()
    ts_candidate.verify_candidate(ts_work, fixed)
    fixture = checked_elf(fixture)
    output.mkdir(mode=0o700)
    subprocess.run(['strip', '--strip-debug', '-o', str(output / 'peer'), str(peer)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    checked_elf(output / 'peer')
    shutil.copyfile(fixture, output / 'ts-fixture')
    record = {'schemaVersion': 1, 'sourceSHA': source_sha, 'platform': 'linux-x86_64',
              'toolchains': TOOLCHAINS, 'sourcePeerSha256': digest(peer),
              'heelerCommit': provenance['heelerCommit'], 'easytierCommit': provenance['easytierCommit'],
              'tailscaleCommit': fixed['tailscaleCommit'], 'materials': materials(),
              'files': {name: digest(output / name) for name in ('peer', 'ts-fixture')}}
    (output / 'peer-manifest.json').write_text(json.dumps(record, indent=2) + '\n')


def verify_peer_bundle(root, source_sha):
    exact_inventory(root, ('peer', 'ts-fixture', 'peer-manifest.json'))
    record = json.loads(checked_file(root / 'peer-manifest.json').read_text())
    expected_keys = {'schemaVersion', 'sourceSHA', 'platform', 'toolchains', 'heelerCommit',
                     'easytierCommit', 'tailscaleCommit', 'sourcePeerSha256', 'materials', 'files'}
    if (not isinstance(record, dict) or set(record) != expected_keys
            or not isinstance(record.get('files'), dict)
            or record.get('schemaVersion') != 1 or record.get('sourceSHA') != source_sha
            or record.get('platform') != 'linux-x86_64' or record.get('toolchains') != TOOLCHAINS
            or not re.fullmatch(r'[a-f0-9]{64}', record.get('sourcePeerSha256', ''))
            or record.get('materials') != materials()
            or record.get('heelerCommit') != '6a2817fc02aeb552df251d9478753c22fd4738bb'
            or record.get('easytierCommit') != '728ba94b5029240add6204eed591f22e4e039e6b'
            or record.get('tailscaleCommit') != '9a522a9786c97eb7910c01ccb7bd66557b04c910'
            or set(record.get('files', {})) != {'peer', 'ts-fixture'}):
        raise ValueError('peer_manifest_invalid')
    for name, expected in record['files'].items():
        if digest(checked_elf(root / name)) != expected:
            raise ValueError('peer_digest_mismatch')
    return record


def assemble(peers, input_dir, output, source_sha):
    record = verify_peer_bundle(peers, source_sha)
    binary, fixture = bootstrap.load_input_fixture(input_dir, os.environ)
    output.mkdir(mode=0o700)
    (output / 'herdr').write_bytes(binary)
    checked_elf(output / 'herdr')
    for name in ('peer', 'ts-fixture'):
        shutil.copyfile(peers / name, output / name)
    for name in NAMES:
        (output / name).chmod(0o700)
    manifest = {'schemaVersion': 1, 'sourceSHA': source_sha, 'platform': 'linux-x86_64',
                'scope': 'Linux build-only fixture executables; no identities, runtime state or device validation',
                'toolchains': TOOLCHAINS, 'sourcePeerSha256': record['sourcePeerSha256'],
                'heelerCommit': record['heelerCommit'], 'easytierCommit': record['easytierCommit'],
                'tailscaleCommit': record['tailscaleCommit'], 'herdrUpstreamSHA': fixture['upstreamSHA'],
                'materials': record['materials'], 'files': {name: digest(output / name) for name in NAMES}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify(output, source_sha)


def verify(root, source_sha):
    exact_inventory(root, (*NAMES, 'manifest.json'))
    manifest = json.loads(checked_file(root / 'manifest.json').read_text())
    expected_keys = {'schemaVersion', 'sourceSHA', 'platform', 'scope', 'toolchains', 'heelerCommit',
                     'easytierCommit', 'tailscaleCommit', 'sourcePeerSha256', 'herdrUpstreamSHA', 'materials', 'files'}
    if (not isinstance(manifest, dict) or set(manifest) != expected_keys
            or not isinstance(manifest.get('files'), dict)
            or manifest.get('scope') != 'Linux build-only fixture executables; no identities, runtime state or device validation'
            or manifest.get('schemaVersion') != 1 or manifest.get('sourceSHA') != source_sha
            or manifest.get('platform') != 'linux-x86_64' or manifest.get('toolchains') != TOOLCHAINS
            or not re.fullmatch(r'[a-f0-9]{64}', manifest.get('sourcePeerSha256', ''))
            or manifest.get('materials') != materials() or set(manifest.get('files', {})) != set(NAMES)
            or manifest.get('herdrUpstreamSHA') != bootstrap.HERDR_COMMIT
            or manifest.get('heelerCommit') != '6a2817fc02aeb552df251d9478753c22fd4738bb'
            or manifest.get('easytierCommit') != '728ba94b5029240add6204eed591f22e4e039e6b'
            or manifest.get('tailscaleCommit') != '9a522a9786c97eb7910c01ccb7bd66557b04c910'):
        raise ValueError('bundle_manifest_invalid')
    for name, expected in manifest['files'].items():
        if digest(checked_elf(root / name)) != expected:
            raise ValueError('bundle_digest_mismatch')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record-peers')
    for name in ('et-bundle', 'et-evidence', 'ts-work', 'ts-fixture', 'output'):
        record.add_argument('--' + name, type=Path, required=True)
    make = sub.add_parser('assemble')
    for name in ('peers', 'input-dir', 'output'):
        make.add_argument('--' + name, type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('--bundle', type=Path, required=True)
    check.add_argument('--source-sha', required=True)
    check.add_argument('--restore-executable', action='store_true')
    args = parser.parse_args()
    try:
        expected_source = args.source_sha if args.command == 'verify' else os.environ.get('GITHUB_SHA', '')
        source = sha_source(expected_source)
        if args.command == 'record-peers':
            record_peers(args.et_bundle, args.et_evidence, args.ts_work, args.ts_fixture, args.output, source)
        elif args.command == 'assemble':
            assemble(args.peers, args.input_dir, args.output, source)
        else:
            verify(args.bundle, source)
            if args.restore_executable:
                for name in NAMES:
                    (args.bundle / name).chmod(0o700)
        print(json.dumps({'status': 'passed', 'sourceSHA': source, 'command': args.command}))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, bootstrap.ProbeFailure, subprocess.SubprocessError) as error:
        codes = {'bundle_file_invalid', 'bundle_directory_invalid', 'bundle_inventory_invalid',
                 'checked_out_source_mismatch', 'linux_x86_64_executable_required',
                 'easytier_peer_provenance_invalid', 'peer_manifest_invalid', 'peer_digest_mismatch',
                 'bundle_manifest_invalid', 'bundle_digest_mismatch'}
        code = str(error) if type(error) is ValueError and str(error) in codes else 'internal_error'
        print(json.dumps({'status': 'failed', 'command': args.command, 'errorCode': code}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
