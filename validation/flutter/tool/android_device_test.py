#!/usr/bin/env python3
"""Add SDK integration_test only to a disposable, already verified candidate.

No SDK installation, emulator, app execution, JVM target change or source-repo
pubspec/lock mutation. The cloud workflow runs pub get between these two steps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'validation/flutter'
FLUTTER_VERSION = '3.47.9'
FLUTTER_COMMIT = 'c197ca5199e9ee5661e865596c9c07294dfab51c'
MARKER = '.herdr-android-device-test.json'
BASELINE = 'tool/android-device-baseline.lock'
SDK_ADDITIONS = {'integration_test', 'flutter_driver', 'fuchsia_remote_debug_protocol'}
# Extra SDK integration-test dependencies are explicitly isolated from the
# product lock. Any existing package drift or unlisted addition fails closed.
ALLOWED_ADDITIONS = SDK_ADDITIONS | {'file', 'platform', 'process', 'sync_http', 'webdriver',
    'web_socket_channel', 'web_socket', 'web', 'crypto', 'http', 'http_parser', 'logging'}


class DevicePreparationFailure(ValueError):
    """Static error labels only."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scoped_path(app, relative):
    path = app / relative
    if not path.resolve().is_relative_to(app) or path.is_symlink():
        raise DevicePreparationFailure('android_device_scaffold_link_rejected')
    return path


def checked_app(destination, env):
    if (env.get('GITHUB_ACTIONS') != 'true' or
            not re.fullmatch(r'\d+', env.get('GITHUB_RUN_ID', '')) or
            not env.get('GITHUB_REF', '').startswith('refs/heads/codex/') or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or not env.get('RUNNER_TEMP')):
        raise DevicePreparationFailure('android_device_preparation_ci_only')
    base = Path(env['RUNNER_TEMP']).resolve()
    app = Path(destination).resolve()
    marker = app / '.herdr-generated-probe.json'
    if (app == base or not app.is_relative_to(base) or (app / '.git').exists() or
            marker.is_symlink() or not marker.is_file()):
        raise DevicePreparationFailure('android_device_not_isolated_scaffold')
    value = json.loads(marker.read_text(encoding='utf-8'))
    if value.get('kind') != 'herdr-flutter-validation' or value.get('sourceCommit') != env['GITHUB_SHA']:
        raise DevicePreparationFailure('android_device_scaffold_source_mismatch')
    for relative in ('lib', 'tool', 'pubspec.yaml', 'pubspec.lock', 'candidate-manifest.json', 'android/app/build.gradle.kts'):
        scoped_path(app, relative)
    return app


PRODUCTION_CHANNELS = ('MainActivity.kt', 'PairScanChannel.kt', 'HostCatalogFile.kt', 'InputJournalFile.kt',
                       'ConfigDocumentChannel.kt')


def production_sources(app):
    expected = {p.relative_to(SOURCE / 'lib') for p in (SOURCE / 'lib').rglob('*.dart')}
    actual = {p.relative_to(app / 'lib') for p in (app / 'lib').rglob('*.dart')}
    if actual != expected or any(digest(app / 'lib' / name) != digest(SOURCE / 'lib' / name) for name in expected):
        raise DevicePreparationFailure('android_device_production_dart_mismatch')
    native = app / 'android/app/src/main/kotlin/dev/herdr/herdr_flutter_probe'
    for name in PRODUCTION_CHANNELS:
        if digest(native / name) != digest(SOURCE / 'native/android' / name):
            raise DevicePreparationFailure('android_device_production_channel_mismatch')
    return {str(Path('lib') / name): digest(scoped_path(app, Path('lib') / name)) for name in sorted(expected)}


def packages(text):
    result, current = {}, None
    for line in text.splitlines():
        if line == 'sdks:':
            break
        match = re.fullmatch(r'  ([A-Za-z0-9_]+):', line)
        if match:
            current = match.group(1)
            if current in result:
                raise DevicePreparationFailure('android_device_duplicate_lock_package')
            result[current] = []
        elif current is not None:
            result[current].append(line)
    if not {'flutter', 'flutter_test', 'terminal_view', 'dartssh2'}.issubset(result):
        raise DevicePreparationFailure('android_device_incomplete_baseline_lock')
    return {name: '\n'.join(lines) for name, lines in result.items()}


def sdk_footer(text):
    return text.split('\nsdks:\n', 1)[1] if '\nsdks:\n' in text else ''


def prepare(destination, env=None):
    env = os.environ if env is None else env
    app = checked_app(destination, env)
    if any((app / path).exists() or (app / path).is_symlink() for path in (MARKER, BASELINE, 'integration_test')):
        raise DevicePreparationFailure('android_device_preparation_already_exists')
    original = (SOURCE / 'pubspec.yaml').read_text(encoding='utf-8')
    if (app / 'pubspec.yaml').read_text(encoding='utf-8') != original or original.count('dev_dependencies:\n') != 1:
        raise DevicePreparationFailure('android_device_pubspec_source_mismatch')
    if re.search(r'^  integration_test:', original, flags=re.M):
        raise DevicePreparationFailure('android_device_sdk_dependency_already_in_source')
    candidate = json.loads((app / 'candidate-manifest.json').read_text(encoding='utf-8'))
    if (candidate.get('sourceCommit') != env['GITHUB_SHA'] or candidate.get('variant') != 'experimental-patched' or
            candidate.get('candidateLockSha256') != digest(app / 'pubspec.lock')):
        raise DevicePreparationFailure('android_device_candidate_lock_not_verified')
    sources = production_sources(app)
    gradle = app / 'android/app/build.gradle.kts'
    gradle_digest = digest(gradle)
    script = gradle.read_text(encoding='utf-8')
    for expected in ('namespace = "dev.herdr.herdr_flutter_probe"', 'applicationId = "dev.herdr.herdr_flutter_probe"'):
        if expected not in script:
            raise DevicePreparationFailure('android_device_package_mismatch')
    baseline = (app / 'pubspec.lock').read_text(encoding='utf-8')
    packages(baseline)
    replacement = original.replace('dev_dependencies:\n', 'dev_dependencies:\n  integration_test:\n    sdk: flutter\n', 1)
    (app / BASELINE).parent.mkdir(exist_ok=True)
    (app / BASELINE).write_text(baseline, encoding='utf-8')
    shutil.copytree(SOURCE / 'integration_test', app / 'integration_test')
    (app / 'pubspec.yaml').write_text(replacement, encoding='utf-8')
    proof = {'schemaVersion': 1, 'kind': 'herdr-flutter-android-integration', 'sourceSHA': env['GITHUB_SHA'],
        'flutterVersion': FLUTTER_VERSION, 'flutterCommit': FLUTTER_COMMIT,
        'baselineLockSha256': digest(app / BASELINE), 'preparedPubspecSha256': digest(app / 'pubspec.yaml'),
        'gradleSha256': gradle_digest, 'productionDartSources': sources, 'lockVerified': False,
        'jvmTargetPolicy': 'inherited unchanged from generated app and shared device-keys.gradle',
        'nativeSigner': 'production AndroidDeviceKeyStore and Bouncy Castle software Ed25519; no test signer',
        'integrationTestSha256': digest(app / 'integration_test/android_pairing_observe_test.dart')}
    native = Path('android/app/src/main/kotlin/dev/herdr/herdr_flutter_probe')
    proof['productionAndroidChannels'] = {str(native / name): digest(app / native / name) for name in
        PRODUCTION_CHANNELS}
    (app / MARKER).write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    return proof


def verify_lock(destination, env=None):
    env = os.environ if env is None else env
    app = checked_app(destination, env)
    for relative in (MARKER, BASELINE, 'integration_test/android_pairing_observe_test.dart'):
        scoped_path(app, relative)
    proof = json.loads((app / MARKER).read_text(encoding='utf-8'))
    if proof.get('sourceSHA') != env['GITHUB_SHA'] or proof.get('kind') != 'herdr-flutter-android-integration':
        raise DevicePreparationFailure('android_device_preparation_source_mismatch')
    if (digest(app / BASELINE) != proof['baselineLockSha256'] or digest(app / 'pubspec.yaml') != proof['preparedPubspecSha256'] or
            digest(app / 'android/app/build.gradle.kts') != proof['gradleSha256'] or
            digest(app / 'integration_test/android_pairing_observe_test.dart') != proof['integrationTestSha256']):
        raise DevicePreparationFailure('android_device_preparation_changed')
    production_sources(app)
    old_text = (app / BASELINE).read_text(encoding='utf-8')
    new_text = (app / 'pubspec.lock').read_text(encoding='utf-8')
    before, after = packages(old_text), packages(new_text)
    if not before.keys() <= after.keys() or any(after[name] != block for name, block in before.items()):
        raise DevicePreparationFailure('android_device_existing_dependency_drift')
    added = after.keys() - before.keys()
    if not SDK_ADDITIONS <= added or not added <= ALLOWED_ADDITIONS:
        raise DevicePreparationFailure('android_device_unexpected_dependency_addition')
    for name in SDK_ADDITIONS:
        if '    source: sdk' not in after[name].splitlines() or '    version: "0.0.0"' not in after[name].splitlines():
            raise DevicePreparationFailure('android_device_integration_dependency_not_sdk')
    for name in added - SDK_ADDITIONS:
        if ('    source: hosted' not in after[name].splitlines() or
                not re.search(r'^      sha256: "?[0-9a-f]{64}"?$', after[name], flags=re.M) or
                not re.search(r'^      url: "https://pub.dev"$', after[name], flags=re.M)):
            raise DevicePreparationFailure('android_device_new_dependency_source_invalid')
    proof.update(lockVerified=True, integrationLockSha256=digest(app / 'pubspec.lock'),
        addedPackages=sorted(added), sdkConstraintsBefore=sdk_footer(old_text), sdkConstraintsAfter=sdk_footer(new_text))
    (app / MARKER).write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    return proof


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'verify-lock'))
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    try:
        proof = (prepare if args.command == 'prepare' else verify_lock)(args.destination)
        print(json.dumps({'status': 'passed', 'step': args.command, 'lockVerified': proof['lockVerified']}))
    except (DevicePreparationFailure, OSError, ValueError, KeyError):
        print(json.dumps({'status': 'failed', 'errorCode': 'android_device_preparation_failed'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
