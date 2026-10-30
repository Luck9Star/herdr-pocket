#!/usr/bin/env python3
"""Cloud-only SDK setup and isolated scaffold; never writes platform files in repo."""
import argparse
import hashlib
import json
import os
import platform as host_platform
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[3]
VERSION = '3.47.9'
COMMIT = 'c197ca5199e9ee5661e865596c9c07294dfab51c'


def run(args, cwd=None):
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def flutter():
    return 'flutter.bat' if os.name == 'nt' else 'flutter'


def prepare(destination):
    if destination.exists():
        raise SystemExit('Refusing to overwrite existing scaffold: ' + str(destination))
    run([flutter(), 'create', '--platforms=android,ios,macos,windows,linux',
         '--project-name=herdr_flutter_probe', '--org=dev.herdr', '--empty', '--no-pub', destination])
    source = ROOT / 'validation/flutter'
    shutil.copy2(source / 'pubspec.yaml', destination / 'pubspec.yaml')
    if (source / 'pubspec.lock').exists():
        shutil.copy2(source / 'pubspec.lock', destination / 'pubspec.lock')
    shutil.copytree(source / 'lib', destination / 'lib', dirs_exist_ok=True)
    shutil.copytree(source / 'test', destination / 'test', dirs_exist_ok=True)
    (destination / 'analysis_options.yaml').write_text('analyzer:\n  errors:\n    todo: ignore\n')
    shared = ROOT / 'validation/shared'
    fixture = json.loads((shared / 'fixture.json').read_text())
    font = shared / fixture['font']['file']
    if hashlib.sha256(font.read_bytes()).hexdigest() != fixture['font']['sha256']:
        raise SystemExit('Shared font checksum mismatch')
    shutil.copytree(shared, destination / 'assets/shared')


def package(destination, platform, output):
    candidates = {
        'android': ['build/app/outputs/flutter-apk/app-debug.apk'],
        'ios': ['build/ios/iphoneos/Runner.app'],
        'macos': ['build/macos/Build/Products/Debug/herdr_flutter_probe.app'],
        'windows': ['build/windows/x64/runner/Debug'],
        'linux': ['build/linux/x64/debug/bundle'],
    }
    output.mkdir(parents=True, exist_ok=True)
    paths = [destination / relative for relative in candidates[platform]]
    for path in paths:
        if not path.exists():
            raise SystemExit('Missing build output: ' + str(path))
    # tar preserves framework symlinks and executable mode on Apple/Linux bundles.
    unix_bundle = platform in ['ios', 'macos', 'linux']
    archive = output / ('flutter-' + platform + '-debug' + ('.tar.gz' if unix_bundle else '.zip'))
    if unix_bundle:
        with tarfile.open(archive, 'w:gz', dereference=False) as bundle:
            for path in paths:
                bundle.add(path, arcname=path.name)
            bundle.add(destination / 'pubspec.lock', arcname='pubspec.lock')
    else:
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
            for path in paths:
                files = [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
                for p in files:
                    bundle.write(p, p.relative_to(path.parent))
            bundle.write(destination / 'pubspec.lock', 'pubspec.lock')
    def version(command):
        try:
            return subprocess.check_output(command, cwd=destination, text=True, stderr=subprocess.STDOUT, timeout=60).strip()
        except Exception as exc:
            return type(exc).__name__
    shared = ROOT / 'validation/shared'
    shutil.copytree(shared, output / 'shared', dirs_exist_ok=True)
    sdk = os.environ.get('ANDROID_HOME', '')
    ndk_versions = sorted(p.name for p in (Path(sdk) / 'ndk').glob('*') if p.is_dir()) if sdk else []
    manifest = {
        'sourceCommit': os.environ.get('GITHUB_SHA', 'local'),
        'runUrl': 'https://github.com/' + os.environ.get('GITHUB_REPOSITORY', '') + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', ''),
        'fontSha256': hashlib.sha256((shared / 'fonts/JetBrainsMonoNerdFontMono-Regular.ttf').read_bytes()).hexdigest(),
        'runner': {'os': host_platform.platform(), 'arch': host_platform.machine(), 'imageOS': os.environ.get('ImageOS'), 'imageVersion': os.environ.get('ImageVersion')},
        'toolchains': {'flutter': version([flutter(), '--version']), 'xcode': version(['xcodebuild', '-version']) if host_platform.system() == 'Darwin' else 'not applicable', 'java': version(['java', '-version']) if platform == 'android' else 'not applicable', 'installedNdkVersions': ndk_versions},
        'flutterVersion': VERSION, 'flutterCommit': COMMIT, 'platform': platform,
        'artifactSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'fixtureSha256': hashlib.sha256((ROOT / 'validation/shared/fixture.json').read_bytes()).hexdigest(),
        'lockSha256': hashlib.sha256((destination / 'pubspec.lock').read_bytes()).hexdigest(),
        'scope': 'compile only; local fixture sink; SSH/overlays/device validation NOT RUN',
        'signing': 'iOS unsigned, not installable on device' if platform == 'ios' else 'development test build; no production signing/notarization',
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(manifest['artifactSha256'] + '  ' + archive.name + '\n')


parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['bootstrap', 'prepare', 'package'])
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--platform')
parser.add_argument('--output', type=Path)
a = parser.parse_args()
if a.command == 'bootstrap':
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('SDK bootstrap is CI-only; local SDK installation is not authorized')
    run(['git', 'clone', '--depth=1', '--branch=' + VERSION, 'https://github.com/flutter/flutter.git', a.destination])
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=a.destination, text=True).strip()
    if actual != COMMIT:
        raise SystemExit('Flutter tag does not match locked source commit')
    with open(os.environ['GITHUB_PATH'], 'a') as f:
        f.write(str(a.destination / 'bin') + '\n')
elif a.command == 'prepare':
    prepare(a.destination)
else:
    package(a.destination, a.platform, a.output)
