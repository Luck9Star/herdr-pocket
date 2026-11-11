#!/usr/bin/env python3
"""Build the pinned Heeler/EasyTier candidate as an iOS static library; never start a node.

Mirrors android_bundle.py's evidence discipline for the aarch64-apple-ios target:
same pinned reference checkout, same candidate patch, hash-pinned manifest. The
archive is consumed in the same CI job that builds it; it never travels between jobs.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import portable_candidate as candidate

base = candidate.base
ROOT = Path(__file__).resolve().parents[3]
TARGET = 'aarch64-apple-ios'
SYMBOLS = ['heeler_et_stream_connect', 'heeler_et_stream_read', 'heeler_et_stream_write',
           'heeler_et_stream_shutdown_write', 'heeler_et_stream_close', 'heeler_et_node_start',
           'heeler_et_node_status', 'heeler_et_node_stop', 'heeler_et_node_stream_connect']


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbols_from_nm(output: str) -> set:
    """Mach-O nm global text symbols carry a leading underscore per object.

    Only external symbols (uppercase type letter) are exported by the archive.
    """
    found = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in ('T', 'W'):
            found.add(parts[2].lstrip('_'))
    return found


def default_nm() -> str:
    """Apple nm cannot parse Rust LLVM-22 object attributes; prefer the matching rust llvm-nm."""
    try:
        sysroot = subprocess.check_output(['rustc', '+1.95.0', '--print', 'sysroot'], text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return 'nm'
    for candidate in sorted(Path(sysroot).glob('lib/rustlib/*/bin/llvm-nm')):
        return str(candidate)
    return 'nm'


def verify(bundle: Path, commit: str, nm: str | None = None) -> dict:
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('target') != TARGET or manifest.get('schemaVersion') != 1:
        raise ValueError('unsupported iOS native manifest schema')
    if manifest['sourceCommit'] != commit or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('source commit mismatch')
    files = manifest['files']
    required = {'libheeler_easytier.a', 'candidate-provenance.json', 'upstream-sources.lock',
                'Heeler-Cargo.lock', 'build-details.json'}
    if not required <= files.keys():
        raise ValueError('required iOS library or source materials missing')
    for name, digest in files.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe manifest path')
        path = bundle / relative
        if path.is_symlink() or not path.is_file() or sha(path) != digest:
            raise ValueError('artifact hash mismatch: ' + name)
    output = subprocess.check_output([(nm or default_nm()), '-g', str(bundle / 'libheeler_easytier.a')], text=True)
    missing = set(SYMBOLS) - symbols_from_nm(output)
    if missing:
        raise ValueError('required exported symbols missing: ' + ','.join(sorted(missing)))
    return manifest


def build(out: Path):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('iOS native candidate build is CI-only')
    out.mkdir(parents=True, exist_ok=False)
    base.OUT = out.resolve()
    base.WORK = Path(os.environ['RUNNER_TEMP']) / ('herdr-ios-candidate-' + os.environ['GITHUB_RUN_ID'])
    base.WORK.mkdir()
    base.CURRENT = {'provider': 'easytier-ios', 'commands': []}
    reference = base.WORK / 'reference'
    base.checkout(base.CONFIG['reference']['repository'], base.CONFIG['reference']['commit'], reference, 'reference')
    lock = base.lock_values(reference)
    env = base.easytier(reference, lock, check=False)
    candidate.apply(reference)
    source = reference / 'native/easytier'
    # The reference crate ships cdylib-only; rustc overrides the crate type for
    # this one invocation to archive every dependency into a single static lib.
    base.run('ios-arm64-staticlib',
             ['cargo', '+1.95.0', 'rustc', '--locked', '--lib', '--release', '--target', TARGET,
              '--', '--crate-type', 'staticlib', '-C', 'strip=symbols'],
             cwd=source, env=env, timeout=3600)
    library = source / 'target' / TARGET / 'release' / 'libheeler_easytier.a'
    if not library.is_file():
        raise RuntimeError('static library missing')
    shutil.copy2(library, out / library.name)
    shutil.copy2(reference / 'sources.lock', out / 'upstream-sources.lock')
    shutil.copy2(source / 'Cargo.lock', out / 'Heeler-Cargo.lock')
    (out / 'build-details.json').write_text(json.dumps(base.CURRENT, indent=2) + '\n', encoding='utf-8')
    files = {p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest = {'schemaVersion': 1, 'target': TARGET, 'sourceCommit': os.environ['GITHUB_SHA'],
                'rust': '1.95.0', 'profile': 'release', 'files': files,
                'staticInspection': 'passed', 'androidLoad': 'not run', 'installation': 'not run',
                'node': 'not run'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    (out / 'SHA256SUMS').write_text(''.join(f'{v}  {k}\n' for k, v in files.items()), encoding='utf-8')
    verify(out, os.environ['GITHUB_SHA'])


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('build'); p.add_argument('bundle', type=Path)
    a = parser.parse_args()
    if a.command == 'build':
        build(a.bundle)


if __name__ == '__main__':
    sys.exit(main())
