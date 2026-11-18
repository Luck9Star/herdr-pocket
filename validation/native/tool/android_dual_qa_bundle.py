#!/usr/bin/env python3
"""Separate test-only TS trust variant; normal verified bundle is never changed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

import android_bundle
import android_tailscale
import tailscale_candidate as candidate

SOURCE = Path(__file__).resolve().parents[1] / 'android/qa/private_ca_android_amd64.go'
LIBRARIES = ('libheeler_easytier.so', 'libhp_tailscale.so', 'libherdr_flutter_network_runtime.so')
QA_FILE = 'qa_private_ca_android_amd64.go'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(normal, qa, commit, readelf):
    normal, qa = Path(normal), Path(qa)
    android_bundle.verify(normal, commit, readelf, 'x86_64')
    record = json.loads((qa / 'qa-manifest.json').read_text())
    if record.get('schemaVersion') != 1 or record.get('variant') != 'test-only-private-ca-android-x86_64':
        raise ValueError('not a private CA QA bundle')
    if record.get('sourceCommit') != commit or record.get('normalManifestSha256') != sha(normal / 'manifest.json'):
        raise ValueError('normal source provenance mismatch')
    if (qa / QA_FILE).is_symlink() or record.get('qaSourceSha256') != sha(SOURCE) or sha(qa / QA_FILE) != sha(SOURCE):
        raise ValueError('QA source mismatch')
    if {p.name for p in qa.iterdir()} != set(LIBRARIES) | {QA_FILE, 'qa-manifest.json'}:
        raise ValueError('unexpected QA bundle contents')
    if set(record.get('files', {})) != set(LIBRARIES):
        raise ValueError('QA file inventory mismatch')
    for name in LIBRARIES:
        if (qa / name).is_symlink() or record['files'].get(name) != sha(qa / name):
            raise ValueError('QA file digest mismatch')
        if name != android_tailscale.LIBRARY and sha(qa / name) != sha(normal / name):
            raise ValueError('non-TS library changed')
    if sha(qa / android_tailscale.LIBRARY) == sha(normal / android_tailscale.LIBRARY):
        raise ValueError('QA TS variant is indistinguishable')
    android_bundle.elf(qa / android_tailscale.LIBRARY, readelf, android_tailscale.SYMBOLS, abi='x86_64')
    return record


def build(normal, qa, commit, readelf):
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('QA cross build is CI-only')
    temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    normal, qa = Path(normal).resolve(strict=True), Path(qa).resolve()
    if not normal.is_relative_to(temp) or not qa.is_relative_to(temp) or qa.exists():
        raise ValueError('owned output required')
    android_bundle.verify(normal, commit, readelf, 'x86_64')
    work = temp / ('herdr-android-candidate-' + os.environ['GITHUB_RUN_ID']) / 'tailscale'
    cache = temp / ('herdr-android-candidate-' + os.environ['GITHUB_RUN_ID']) / 'go-cache'
    candidate.verify_candidate(work, candidate.verify_sources())
    target = work / QA_FILE
    if target.exists() or target.is_symlink():
        raise ValueError('unexpected QA source already exists')
    qa.mkdir(mode=0o700)
    try:
        for name in LIBRARIES:
            if name != android_tailscale.LIBRARY:
                shutil.copy2(normal / name, qa / name)
        shutil.copy2(SOURCE, target)
        shutil.copy2(SOURCE, qa / QA_FILE)
        go, env = android_tailscale.cross_environment(cache, Path(os.environ['ANDROID_HOME']) / 'ndk/28.2.13676358', 'x86_64')
        candidate.run([go, 'build', '-trimpath', '-buildmode=c-shared',
                       '-ldflags=-linkmode=external -extldflags=-Wl,-soname,libhp_tailscale.so,-z,max-page-size=16384',
                       '-o', qa / android_tailscale.LIBRARY, '.'], work, env, work / 'logs/android-qa-build.log')
        (qa / 'libhp_tailscale.h').unlink(missing_ok=True)
    finally:
        target.unlink(missing_ok=True)
        candidate.verify_candidate(work, candidate.verify_sources())
    record = {'schemaVersion': 1, 'variant': 'test-only-private-ca-android-x86_64',
              'sourceCommit': commit, 'normalManifestSha256': sha(normal / 'manifest.json'),
              'qaSourceSha256': sha(SOURCE), 'files': {name: sha(qa / name) for name in LIBRARIES},
              'androidLoad': 'not run', 'node': 'not run'}
    (qa / 'qa-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    verify(normal, qa, commit, readelf)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('--normal', required=True, type=Path)
    parser.add_argument('--qa', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--readelf', required=True)
    args = parser.parse_args()
    (build if args.action == 'build' else verify)(args.normal, args.qa, args.commit, args.readelf)
