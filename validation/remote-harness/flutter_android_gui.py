"""Production Flutter UI + native Android signer on one disposable cloud AVD.

The exchange is app-private public data via adb run-as, not a signer/frame API.
No HTTP service, system authorization files, real devices or raw logs in reports.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
TARGET_FIELDS = {'schemaVersion', 'host', 'port', 'username', 'expectedHostKey',
                 'socketPath', 'herdrPath', 'session', 'paneId', 'reviewConfirmed'}
BOOL_FIELDS = ('productionMain', 'defaultHostCatalog', 'uninjectedNativeDeviceKeys',
    'publicRequestShown', 'pendingRequestReopened', 'originalDeviceKeyRevalidated',
    'authorizationReviewed', 'pairedStateVisible', 'paneChosen', 'fullRendered',
    'deltaRendered', 'stoppedStale', 'observeMode', 'directModeDisabled',
    'draftModeDisabled', 'localIdentityDeleted')
STAGES = {'host_board', 'public_request', 'restore_pending', 'host_authorization',
          'response_review', 'ssh_and_dashboard', 'observe_frames', 'stop',
          'delete_local_identity', 'complete'}


class DeviceFailure(ValueError):
    """Only static phase codes may leave this module."""


def require_cloud(env, root, application, config):
    run_id, sha = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_SHA', '')
    if (env.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'\d+', run_id) or
            not env.get('GITHUB_REF', '').startswith('refs/heads/codex/') or
            not re.fullmatch(r'[0-9a-f]{40}', sha) or env.get('ANDROID_SERIAL') != SERIAL or
            not env.get('RUNNER_TEMP')):
        raise DeviceFailure('flutter_android_ci_emulator_only')
    root, app = Path(root).resolve(), Path(application).resolve()
    temporary = Path(env['RUNNER_TEMP']).resolve()
    if (root.parent != Path('/tmp').resolve() or not root.name.startswith('hp-mobile-' + run_id + '-') or
            app == temporary or not app.is_relative_to(temporary) or (app / '.git').exists()):
        raise DeviceFailure('flutter_android_not_isolated_fixture')
    if (not isinstance(config, dict) or set(config) != TARGET_FIELDS or config['host'] != '127.0.0.1' or
            type(config['port']) is not int or not 1024 <= config['port'] <= 65535 or
            config['session'] != 'pocket-probe' or config['schemaVersion'] != 1 or config['reviewConfirmed'] is not True or
            config['herdrPath'] != str(root / 'herdr') or
            config['socketPath'] != str(root / 'config/herdr/sessions/pocket-probe/herdr.sock')):
        raise DeviceFailure('flutter_android_invalid_public_target')
    marker = app / '.herdr-android-device-test.json'
    if marker.is_symlink() or not marker.is_file():
        raise DeviceFailure('flutter_android_preparation_missing')
    proof = json.loads(marker.read_text(encoding='utf-8'))
    if (proof.get('kind') != 'herdr-flutter-android-integration' or proof.get('sourceSHA') != sha or
            proof.get('lockVerified') is not True or proof.get('flutterVersion') != '3.47.9' or
            proof.get('flutterCommit') != 'c197ca5199e9ee5661e865596c9c07294dfab51c' or
            proof.get('integrationLockSha256') != hashlib.sha256((app / 'pubspec.lock').read_bytes()).hexdigest() or
            proof.get('integrationTestSha256') != hashlib.sha256((app / 'integration_test/android_pairing_observe_test.dart').read_bytes()).hexdigest()):
        raise DeviceFailure('flutter_android_preparation_not_verified')
    sources = proof.get('productionDartSources')
    channels = proof.get('productionAndroidChannels')
    if (not isinstance(sources, dict) or not {'lib/main.dart', 'lib/device_keys.dart', 'lib/host_catalog.dart',
            'lib/pairing_page.dart', 'lib/remote_adapter.dart'}.issubset(sources) or
            not isinstance(channels, dict) or len(channels) != 4):
        raise DeviceFailure('flutter_android_production_source_proof_missing')
    for name, expected in {**sources, **channels}.items():
        if (not isinstance(name, str) or '..' in Path(name).parts or Path(name).is_absolute() or
                not (app / name).resolve().is_relative_to(app) or (app / name).is_symlink() or
                not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or
                hashlib.sha256((app / name).read_bytes()).hexdigest() != expected):
            raise DeviceFailure('flutter_android_production_sources_changed')
    if hashlib.sha256((app / 'android/app/build.gradle.kts').read_bytes()).hexdigest() != proof.get('gradleSha256'):
        raise DeviceFailure('flutter_android_gradle_changed')
    return app


def safe_device_result(raw):
    if not isinstance(raw, dict) or raw.get('case') != 'android-native-pairing-observe' or raw.get('buildMode') != 'debug':
        raise DeviceFailure('flutter_android_result_case_invalid')
    clean = {'case': raw['case'], 'buildMode': 'debug'}
    for field in BOOL_FIELDS:
        if type(raw.get(field)) is not bool or raw[field] is not True:
            raise DeviceFailure('flutter_android_result_boolean_invalid')
        clean[field] = True
    for field in ('firstSequence', 'deltaSequence'):
        value = raw.get(field)
        if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
            raise DeviceFailure('flutter_android_result_sequence_invalid')
        clean[field] = value
    if clean['deltaSequence'] <= clean['firstSequence']:
        raise DeviceFailure('flutter_android_delta_not_observed')
    for field, expected in (('identityCreationActions', 1), ('frameCountLowerBound', 2), ('deltaCountLowerBound', 1)):
        if type(raw.get(field)) is not int or raw[field] != expected:
            raise DeviceFailure('flutter_android_result_counter_invalid')
        clean[field] = expected
    return clean


def adb(*args, check=True, data=None, timeout=30):
    try:
        result = subprocess.run(['adb', '-s', SERIAL, *map(str, args)], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise DeviceFailure('flutter_android_adb_unavailable') from None
    if len(result.stdout) > 1_048_576 or len(result.stderr) > 1_048_576:
        raise DeviceFailure('flutter_android_adb_output_limit')
    if check and result.returncode:
        raise DeviceFailure('flutter_android_adb_failed')
    return result


def text(*args, **kwargs):
    return adb(*args, **kwargs).stdout.decode('utf-8', errors='strict').strip()


def package_present():
    return 'package:' + PACKAGE in text('shell', 'pm', 'list', 'packages', PACKAGE).splitlines()


def checked_flutter_version():
    try:
        reply = subprocess.run(['flutter', '--version', '--machine'], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30, check=False)
        if reply.returncode or len(reply.stdout) > 65536 or len(reply.stderr) > 65536:
            raise DeviceFailure('flutter_android_toolchain_unavailable')
        value = json.loads(reply.stdout.decode('utf-8'))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise DeviceFailure('flutter_android_toolchain_unavailable') from None
    expected = {'frameworkVersion': '3.47.9', 'frameworkRevision': 'c197ca5199e9ee5661e865596c9c07294dfab51c'}
    if not isinstance(value, dict) or any(value.get(name) != item for name, item in expected.items()):
        raise DeviceFailure('flutter_android_toolchain_mismatch')
    return expected


def forward_set():
    result = set()
    for line in text('forward', '--list').splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise DeviceFailure('flutter_android_forward_list_invalid')
        if fields[0] == SERIAL:
            result.add(tuple(fields))
    return result


def read_public(relative, limit):
    if not re.fullmatch(r'cache/herdr-flutter-android-[0-9]+/(?:request\.json|result\.json|stage)', relative):
        raise DeviceFailure('flutter_android_public_path_invalid')
    reply = adb('exec-out', 'run-as', PACKAGE, 'head', '-c', str(limit + 1), relative, check=False)
    if reply.returncode:
        return None
    if len(reply.stdout) > limit:
        raise DeviceFailure('flutter_android_public_exchange_oversize')
    return reply.stdout


def write_response(relative_directory, response):
    if (not re.fullmatch(r'cache/herdr-flutter-android-[0-9]+', relative_directory) or
            not isinstance(response, bytes) or not 1 <= len(response) <= 2048):
        raise DeviceFailure('flutter_android_response_invalid')
    # Disable PTY conversion; public JSON is stdin to tee, never interpolated
    # into executable text. tee's bounded echo stays in this private process.
    pending = relative_directory + '/response.new'
    adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=response)
    adb('shell', 'run-as', PACKAGE, 'mv', pending, relative_directory + '/response.json')


def failure_stage(relative_directory, fallback):
    phase = read_public(relative_directory + '/stage', 40)
    label = phase.decode('ascii', errors='ignore') if phase is not None else ''
    return fallback + '_' + label if label in STAGES else fallback


def wait_public(proc, relative_directory, name, limit, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read_public(relative_directory + '/' + name, limit)
        if result is not None:
            return result
        if proc.poll() is not None:
            raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_test_exited'))
        time.sleep(0.15)
    raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_phase_timeout'))


def run_flutter_android(args, root, env, config, approval):
    # Import the existing process owner only in the real runner path. Guard and
    # evidence unit tests use the standard library and never touch adb/a host.
    from paired_gui import GuiFailure, owned_process
    try:
        return _run(args, Path(root), env, config, approval, owned_process)
    except DeviceFailure as failure:
        raise GuiFailure(str(failure)) from None


def _run(args, root, env, config, approval, owned_process):
    app = require_cloud(env, root, args.flutter_app, config)
    if getattr(args, 'input_fixture', None):
        raise DeviceFailure('flutter_android_readonly_case_requires_stock_server')
    output = Path(args.output).resolve()
    temporary = Path(env['RUNNER_TEMP']).resolve()
    if output == temporary or not output.is_relative_to(temporary) or not output.is_dir():
        raise DeviceFailure('flutter_android_output_not_isolated')
    devices = [line.split()[:2] for line in text('devices').splitlines()[1:] if line.strip()]
    if devices != [[SERIAL, 'device']]:
        raise DeviceFailure('flutter_android_existing_or_non_emulator_device')
    if (text('shell', 'getprop', 'ro.kernel.qemu') != '1' or
            text('shell', 'getprop', 'ro.build.version.sdk') != '35' or
            text('shell', 'am', 'get-current-user') != '0'):
        raise DeviceFailure('flutter_android_avd_api_or_user_mismatch')
    if package_present():
        raise DeviceFailure('flutter_android_package_already_present')
    reverse = 'tcp:' + str(config['port'])
    if any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines()):
        raise DeviceFailure('flutter_android_reverse_already_present')
    toolchain = checked_flutter_version()
    before_forwards = forward_set()
    relative = 'cache/herdr-flutter-android-' + env['GITHUB_RUN_ID']
    defines = root / 'flutter-android-public-defines.json'
    defines.write_text(json.dumps({'HERDR_ANDROID_NATIVE_PAIRING': '1', 'HERDR_ANDROID_RUN_ID': env['GITHUB_RUN_ID'],
        'HERDR_ANDROID_TARGET_JSON': json.dumps(config, separators=(',', ':')),
        'HERDR_ANDROID_PUBLIC_DIR': '/data/user/0/' + PACKAGE + '/' + relative}), encoding='utf-8')
    defines.chmod(0o600)
    command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
               '--dart-define-from-file=' + str(defines), 'integration_test/android_pairing_observe_test.dart']
    process = None
    reverse_added = False
    result = None
    cleanup = {'sourceSHA': env['GITHUB_SHA'], 'ownedPackageInitiallyAbsent': True,
               'ownedPackageAbsent': False, 'appProcessGone': False, 'reverseRemoved': False,
               'ownedForwardsRemoved': False, 'flutterToolStopped': False, 'rawLogsUploaded': False}
    try:
        adb('reverse', reverse, reverse); reverse_added = True
        with owned_process(command, cwd=app, env=env, log=root / 'flutter-android-private.log') as process:
            request = wait_public(process, relative, 'request.json', 2048, timeout=900)
            response = approval.approve(request)
            write_response(relative, response)
            raw = wait_public(process, relative, 'result.json', 8192, timeout=400)
            result = safe_device_result(json.loads(raw.decode('utf-8')))
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                raise DeviceFailure('flutter_android_tool_exit_timeout') from None
            if code:
                raise DeviceFailure(failure_stage(relative, 'flutter_android_test_failed'))
    finally:
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        try:
            if package_present():
                adb('shell', 'am', 'force-stop', PACKAGE)
                cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
                adb('uninstall', PACKAGE, timeout=60)
            else:
                cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
            cleanup['ownedPackageAbsent'] = not package_present()
            cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
        except DeviceFailure:
            pass
        try:
            for _, local, _ in forward_set() - before_forwards:
                if not re.fullmatch(r'tcp:[0-9]+', local):
                    raise DeviceFailure('flutter_android_unknown_forward')
                adb('forward', '--remove', local)
            cleanup['ownedForwardsRemoved'] = forward_set() == before_forwards
        except DeviceFailure:
            pass
        try:
            if reverse_added:
                adb('reverse', '--remove', reverse)
            cleanup['reverseRemoved'] = not any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines())
        except DeviceFailure:
            pass
        defines.unlink(missing_ok=True)
        successful_cleanup = all(cleanup[field] is True for field in
            ('ownedPackageAbsent', 'appProcessGone', 'reverseRemoved', 'ownedForwardsRemoved', 'flutterToolStopped'))
        cleanup['status'] = 'passed' if successful_cleanup else 'failed'
        (output / 'flutter-android-device-cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n', encoding='utf-8')
        if not successful_cleanup:
            raise DeviceFailure('flutter_android_cleanup_failed')
    if result is None:
        raise DeviceFailure('flutter_android_result_missing')
    return {**result, 'paired': True, 'reopenedPendingRequest': True,
        'keyStore': 'API35 emulator production AndroidKeyStore AES-wrapped seed; native software Ed25519 signing',
        'device': 'disposable API35 Android AVD', 'uiDriver': 'Flutter SDK integration_test public text/tap controls',
        'frameEvidence': 'displayed sequence advance on the same production Terminal object after initial full',
        'storageMocked': False, 'signerInjected': False, 'framesInjected': False,
        'flutterToolchain': toolchain, 'deviceApi': 35, 'deviceCleanup': cleanup}
