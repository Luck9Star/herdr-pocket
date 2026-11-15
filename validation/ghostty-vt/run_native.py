#!/usr/bin/env python3
"""Fetch hash-pinned official 1.0.1, link its C API, run locally on macOS arm64."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
import zipfile

BASE = 'https://release.files.ghostty.org/libghostty-vt/1.0.1/'
TAG = 'e9dc690b08bde7e2ec9c7aff8a18a85c9cade46d'
COMMIT = '108cacb17ed8990840cd14abfce43d8ed8503ca1'
HASHES = {
    'SHA256SUMS': 'bb7a3cf9d6de0f9cb278a94006a96586375de5d56d4df74e03ea59dac035a069',
    'ghostty-vt-1.0.1.xcframework.zip': 'c0f9631277f726154c8f521954d17cdc41aac4626fc0df8cf925a19ee58e829b',
}
USER_AGENT = 'herdr-pocket-prototype-validation'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(url):
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('/tmp/herdr-ghostty-vt-1.0.1'))
    parser.add_argument('--output', type=Path, help='safe JSON result; defaults to CACHE/native-result.json')
    parser.add_argument('--require-reset', action='store_true', help='also require reset-only stream isolation; known to fail on 1.0.1')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        parser.error('this probe executes locally on macOS arm64; it does not cross-compile device evidence')
    args.cache.mkdir(parents=True, exist_ok=True)
    ref = json.loads(request('https://api.github.com/repos/ghostty-org/ghostty/git/ref/tags/vt-1.0.1'))
    if ref['object']['sha'] != TAG or ref['object']['type'] != 'tag':
        raise SystemExit('official tag object does not match pinned release')
    tag = json.loads(request('https://api.github.com/repos/ghostty-org/ghostty/git/tags/' + TAG))
    if tag['object']['sha'] != COMMIT or tag['object']['type'] != 'commit':
        raise SystemExit('official tag does not resolve to pinned release commit')
    for name, expected in HASHES.items():
        target = args.cache / name
        if not target.exists() or digest(target) != expected:
            pending = args.cache / (name + '.pending')
            pending.write_bytes(request(BASE + name))
            if digest(pending) != expected:
                pending.unlink()
                raise SystemExit('download hash mismatch: ' + name)
            pending.replace(target)
    manifest = dict(line.split(maxsplit=1)[::-1] for line in (args.cache / 'SHA256SUMS').read_text().splitlines())
    archive = 'ghostty-vt-1.0.1.xcframework.zip'
    if manifest.get(archive) != HASHES[archive]:
        raise SystemExit('pinned manifest does not match pinned package')
    # Always extract from the verified archive; do not trust stale cache headers.
    with zipfile.ZipFile(args.cache / archive) as bundle:
        for item in bundle.infolist():
            if not (args.cache / item.filename).resolve().is_relative_to(args.cache.resolve()):
                raise SystemExit('archive entry escapes cache')
        bundle.extractall(args.cache)
    slice_dir = args.cache / 'ghostty-vt.xcframework/macos-arm64_x86_64'
    source = Path(__file__).with_name('probe.c')
    binary = args.cache / 'probe-arm64'
    command = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-arch', 'arm64',
               '-I' + str(slice_dir / 'Headers'), str(source), str(slice_dir / 'libghostty-vt.a'), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    if data.get('libraryVersion') != '1.0.1':
        raise SystemExit('runtime library version does not match pinned release')
    if result.stderr:
        raise SystemExit('probe emitted unexpected stderr')
    data.update({
        'source': {'tag': 'vt-1.0.1', 'tagObject': TAG, 'releaseCommit': COMMIT,
                   'githubReportsTagSignatureVerified': tag.get('verification', {}).get('verified'),
                   'downloadBase': BASE, 'verifiedSha256': HASHES},
        'execution': {'os': platform.system(), 'osVersion': platform.mac_ver()[0],
                      'architecture': platform.machine(), 'kind': 'native-local-C-ABI',
                      'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
                      'binary': subprocess.check_output(['file', str(binary)], text=True).strip(),
                      'probeSourceSha256': digest(source), 'compileCommand': command,
                      'exitCode': result.returncode},
        'scope': {'networkOrPtyOpenedByProbe': False, 'rendererOrDeviceValidated': False,
                  'packageSignatureVerifiedByThisScript': False,
                  'description': 'Synthetic terminal core only; no remote transport, font pixels, IME or native app UI.'},
    })
    rejected = [item['name'] for item in data['observations'] if not item['supported']]
    data['acceptancePolicy'] = {'sessionIsolation': 'free old terminal and create a new instance',
                                'requireResetIsolation': args.require_reset, 'rejectedResetHypotheses': rejected}
    accepted = result.returncode == 0 and not (args.require_reset and rejected)
    output = args.output or args.cache / 'native-result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    failed = [check['name'] for check in data['checks'] if not check['passed']]
    print(json.dumps({'output': str(output.resolve()), 'checks': data['checkCount'],
                      'failed': failed, 'rejectedResetHypotheses': rejected,
                      'accepted': accepted, 'libraryVersion': data['libraryVersion']}, ensure_ascii=False))
    return 0 if accepted else (result.returncode or 1)


if __name__ == '__main__':
    sys.exit(main())
