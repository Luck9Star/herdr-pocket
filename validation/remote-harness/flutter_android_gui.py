"""Production Flutter UI + native Android signer on one disposable cloud AVD.

The exchange is app-private public data via adb run-as, not a signer/frame API.
No HTTP service, system authorization files, real devices or raw logs in reports.
"""
import hashlib
import base64
import binascii
import json
from pathlib import Path
import re
import subprocess
import time
from guarded_input import EvidenceError, mobile_receipts, validate_mode

PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
TARGET_FIELDS = {'schemaVersion', 'host', 'port', 'username', 'expectedHostKey',
                 'socketPath', 'herdrPath', 'session', 'paneId', 'reviewConfirmed'}
BOOL_FIELDS = ('productionMain', 'defaultHostCatalog', 'uninjectedNativeDeviceKeys',
    'publicRequestShown', 'pendingRequestReopened', 'originalDeviceKeyRevalidated',
    'authorizationReviewed', 'pairedStateVisible', 'paneChosen', 'fullRendered',
    'deltaRendered', 'stoppedStale', 'observeMode', 'directModeDisabled',
    'draftModeDisabled', 'localIdentityDeleted')
STAGES = {'target_invalid', 'catalog_intent_failed', 'device_create_failed', 'handle_save_failed',
          'signer_create', 'signer_public', 'signer_sign', 'signer_delete', 'signer_read_deleted',
          'public_key_failed', 'profile_save_failed', 'create_not_available', 'host_board', 'public_request', 'restore_pending', 'host_authorization',
          'target_finish_edit', 'target_review_ready', 'target_review_unchecked', 'target_create_unavailable',
          'response_review', 'ssh_and_dashboard', 'observe_frames', 'stop',
          'host_task_summary_authoritative', 'host_task_summary_stale',
          'delete_local_identity', 'complete', 'guarded_direct', 'guarded_hidden_draft',
          'guarded_reconnect', 'guarded_draft_review', 'fixture_validation',
          'response_enter', 'response_preview', 'response_source_confirm', 'response_accept',
          'response_authorized', 'response_open_remote', 'response_remote_identity',
          'response_finish_edit', 'response_rejected', 'response_save_unconfirmed',
          'response_review_invalidated',
          'guarded_direct_available', 'guarded_direct_select', 'guarded_direct_focus',
          'guarded_direct_commit', 'guarded_direct_ack', 'guarded_direct_receipt'}
STOCK_CASE = 'android-native-pairing-observe'
GUARDED_CASE = 'android-native-pairing-guarded-input'
GUARDED_FIELDS = ('guardedInput', 'directInputAccepted', 'draftInputAccepted', 'hiddenTabStopped',
                  'hiddenTabManualRecovery', 'unsentDraftRestored', 'postStopInputDisabled')
PUBLIC_LIMITS = {'request.json': 2048, 'result.json': 8192, 'signer.json': 1024, 'stage': 40,
                 'failure.json': 512}
SIGNER_CHALLENGE = b'herdr-pocket-android-signer-probe-v1'
REQUEST_FIELDS = {'version', 'type', 'request_id', 'account', 'host_key',
                  'issued_at', 'expires_at', 'device', 'public_key'}


class DeviceFailure(ValueError):
    """Only static phase codes may leave this module."""


def safe_test_failure(value):
    kinds = {'TestFailure', 'StateError', 'TypeError', 'RemoteFailure', 'FormatException',
             'TimeoutException', 'other'}
    if (not isinstance(value, dict) or set(value) != {'stage', 'errorClass', 'line'} or
            not isinstance(value['stage'], str) or not isinstance(value['errorClass'], str) or
            value['stage'] not in STAGES or value['errorClass'] not in kinds or
            type(value['line']) is not int or not 0 <= value['line'] <= 10000):
        raise DeviceFailure('flutter_android_failure_metadata_invalid')
    return {key: value[key] for key in ('stage', 'errorClass', 'line')}


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
    expected_channels = {'MainActivity.kt', 'PairScanChannel.kt', 'HostCatalogFile.kt', 'InputJournalFile.kt',
                         'ConfigDocumentChannel.kt'}
    if (not isinstance(sources, dict) or not {'lib/main.dart', 'lib/device_keys.dart', 'lib/host_catalog.dart',
            'lib/pairing_page.dart', 'lib/remote_adapter.dart'}.issubset(sources) or
            not isinstance(channels, dict) or len(channels) != len(expected_channels) or
            {Path(path).name for path in channels} != expected_channels):
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


def safe_device_result(raw, guarded=False):
    case = GUARDED_CASE if guarded else STOCK_CASE
    if not isinstance(raw, dict) or raw.get('case') != case or raw.get('buildMode') != 'debug':
        raise DeviceFailure('flutter_android_result_case_invalid')
    clean = {'case': raw['case'], 'buildMode': 'debug'}
    for field in BOOL_FIELDS + (GUARDED_FIELDS if guarded else ()):
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
    if guarded:
        try:
            clean['inputReceipts'] = mobile_receipts(raw.get('inputReceipts'))
        except EvidenceError as exc:
            raise DeviceFailure(str(exc)) from None
        sizes = [receipt['acceptedBytes'] for receipt in clean['inputReceipts']]
        counts = raw.get('acceptedByteCounts')
        if counts != sizes or not all(type(count) is int for count in counts):
            raise DeviceFailure('flutter_android_guarded_byte_counts_invalid')
        clean['acceptedByteCounts'] = sizes
    elif raw.get('inputReceipts') or raw.get('guardedInput'):
        raise DeviceFailure('flutter_android_stock_input_unexpected')
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


def public_file_pending(reply, relative):
    # During Flutter's build/install the app does not exist yet; after launch
    # its atomic public file may not exist yet. Match only these exact paths
    # and known diagnostics, including legacy exec-out's status-zero stdout.
    pending = {
        ('run-as: unknown package: ' + PACKAGE).encode(),
        ('head: ' + relative + ': No such file or directory').encode(),
        ("head: '" + relative + "': No such file or directory").encode(),
        ('head: ' + relative + ': No such file or directory.').encode(),
    }
    lines = [line.strip() for line in (reply.stdout + b'\n' + reply.stderr).splitlines() if line.strip()]
    return bool(lines) and all(line in pending for line in lines)


def checked_public_payload(raw, name):
    kind = name.split('.')[0]
    invalid = 'flutter_android_public_' + kind + '_invalid'
    if not raw.strip():
        return None
    if name == 'stage':
        try:
            label = raw.decode('ascii')
        except UnicodeDecodeError:
            raise DeviceFailure(invalid) from None
        if label in STAGES:
            return raw
        if any(stage.startswith(label) for stage in STAGES):
            return None
        raise DeviceFailure(invalid)
    if not raw.lstrip().startswith(b'{'):
        raise DeviceFailure(invalid)

    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise DeviceFailure(invalid)
            value[key] = item
        return value

    try:
        decoded = raw.decode('utf-8')
        value = json.loads(decoded, object_pairs_hook=unique_fields)
    except UnicodeDecodeError as error:
        if error.reason == 'unexpected end of data':
            return None
        raise DeviceFailure(invalid) from None
    except json.JSONDecodeError:
        # Nothing incomplete may reach the host approval boundary. The outer
        # phase deadline still bounds a persistently incomplete publication.
        return None
    except RecursionError:
        raise DeviceFailure(invalid) from None
    if name == 'request.json':
        if (not isinstance(value, dict) or set(value) != REQUEST_FIELDS or
                type(value['version']) is not int or value['version'] != 2 or
                value['type'] != 'pairing-public-key-request' or
                any(type(value[key]) is not int for key in ('issued_at', 'expires_at')) or
                any(not isinstance(value[key], str) or not value[key] for key in
                    REQUEST_FIELDS - {'version', 'issued_at', 'expires_at'})):
            raise DeviceFailure(invalid)
        # The production Host.review remains authoritative for public-key
        # parsing, TTL, request ID, account and host fingerprint validation.
    elif name == 'result.json':
        # Validate the wire shape here; _run separately binds it to the
        # explicitly selected stock/guarded case before accepting the result.
        safe_device_result(value, guarded=isinstance(value, dict) and value.get('case') == GUARDED_CASE)
    elif name == 'signer.json':
        if (not isinstance(value, dict) or set(value) != {'publicKey', 'signature', 'deleteReturned', 'readRejected'} or
                not isinstance(value['publicKey'], str) or not isinstance(value['signature'], str) or
                value['deleteReturned'] is not True or value['readRejected'] is not True):
            raise DeviceFailure(invalid)
    elif name == 'failure.json':
        safe_test_failure(value)
    return raw


def read_public(relative, limit):
    if not re.fullmatch(r'cache/herdr-flutter-android-[0-9]+/(?:request\.json|result\.json|signer\.json|failure\.json|stage)', relative):
        raise DeviceFailure('flutter_android_public_path_invalid')
    name = relative.rsplit('/', 1)[1]
    if type(limit) is not int or limit != PUBLIC_LIMITS[name]:
        raise DeviceFailure('flutter_android_public_limit_invalid')
    # shell v2 (without -x) carries remote exit status and separate stderr.
    # exec-out has neither guarantee and can present run-as/head errors as data.
    reply = adb('shell', '-T', 'run-as', PACKAGE, 'head', '-c', str(limit + 1), relative, check=False)
    if public_file_pending(reply, relative):
        return None
    if len(reply.stdout) > limit or len(reply.stderr) > limit:
        raise DeviceFailure('flutter_android_public_exchange_oversize')
    if reply.returncode or reply.stderr:
        raise DeviceFailure('flutter_android_public_' + name.split('.')[0] + '_read_failed')
    return checked_public_payload(reply.stdout, name)


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
        # Flutter may still be building/installing its disposable app. Never
        # run-as a package that has not appeared on this emulator yet.
        if not package_present():
            if proc.poll() is not None:
                raise DeviceFailure('flutter_android_test_exited_before_install')
            time.sleep(0.15)
            continue
        result = read_public(relative_directory + '/' + name, limit)
        if result is not None:
            return result
        if proc.poll() is not None:
            if package_present():
                raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_test_exited'))
            raise DeviceFailure('flutter_android_test_exited')
        time.sleep(0.15)
    if package_present():
        raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_phase_timeout'))
    raise DeviceFailure('flutter_android_package_install_timeout')


def verify_signer(raw):
    # Public bytes are consumed only here; never persist them in the report.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        checked_public_payload(raw, 'signer.json')
        value = json.loads(raw)
        signature = base64.b64decode(value['signature'], validate=True)
        key = load_ssh_public_key(value['publicKey'].encode('ascii'))
        if not isinstance(key, Ed25519PublicKey) or len(signature) != 64:
            raise ValueError()
        key.verify(signature, SIGNER_CHALLENGE)
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, InvalidSignature):
        raise DeviceFailure('flutter_android_signer_verification_failed') from None
    return {'stage': 'complete', 'signatureVerified': True, 'deleteReturned': True, 'readRejected': True}


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
    guarded = getattr(args, 'android_guarded_input', False)
    try:
        validate_mode('flutter-android', bool(args.input_fixture), guarded)
    except EvidenceError as exc:
        raise DeviceFailure(str(exc)) from None
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
        'POCKET_GUARDED_INPUT': 'true' if guarded else 'false',
        'HERDR_ANDROID_TARGET_JSON': json.dumps(config, separators=(',', ':')),
        'HERDR_ANDROID_PUBLIC_DIR': '/data/user/0/' + PACKAGE + '/' + relative}), encoding='utf-8')
    defines.chmod(0o600)
    command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
               '--dart-define-from-file=' + str(defines), 'integration_test/android_pairing_observe_test.dart']
    process = None
    reverse_added = False
    result = None
    signer_evidence = {'stage': 'not_completed', 'signatureVerified': False,
                       'deleteReturned': False, 'readRejected': False}
    cleanup = {'sourceSHA': env['GITHUB_SHA'], 'ownedPackageInitiallyAbsent': True,
               'ownedPackageAbsent': False, 'appProcessGone': False, 'reverseRemoved': False,
               'ownedForwardsRemoved': False, 'flutterToolStopped': False, 'rawLogsUploaded': False}
    try:
        adb('reverse', reverse, reverse); reverse_added = True
        with owned_process(command, cwd=app, env=env, log=root / 'flutter-android-private.log') as process:
            raw_signer = wait_public(process, relative, 'signer.json', 1024, timeout=900)
            signer_evidence['stage'] = 'verification_failed'
            signer_evidence = verify_signer(raw_signer)
            request = wait_public(process, relative, 'request.json', 2048, timeout=900)
            response = approval.approve(request)
            write_response(relative, response)
            raw = wait_public(process, relative, 'result.json', 8192, timeout=400)
            result = safe_device_result(json.loads(raw.decode('utf-8')), guarded=guarded)
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                raise DeviceFailure('flutter_android_tool_exit_timeout') from None
            if code:
                raise DeviceFailure(failure_stage(relative, 'flutter_android_test_failed'))
    finally:
        # Only fixed stage/class names and a bounded source line may leave the
        # device. Never copy exception text or the raw Flutter/SSH logs.
        failure = None
        try:
            raw_failure = read_public(relative + '/failure.json', PUBLIC_LIMITS['failure.json'])
            if raw_failure is not None:
                failure = safe_test_failure(json.loads(raw_failure))
        except (DeviceFailure, ValueError):
            pass
        (output / 'flutter-android-test-failure.json').write_text(
            json.dumps({'sourceSHA': env['GITHUB_SHA'], 'failure': failure}, indent=2) + '\n', encoding='utf-8')
        if signer_evidence['stage'] != 'complete':
            try:
                label = read_public(relative + '/stage', 40)
                if label is not None and label.decode('ascii') in {
                        'signer_create', 'signer_public', 'signer_sign', 'signer_delete', 'signer_read_deleted'}:
                    signer_evidence['stage'] = label.decode('ascii')
            except DeviceFailure:
                pass
        (output / 'flutter-android-signer-probe.json').write_text(json.dumps(signer_evidence, indent=2) + '\n', encoding='utf-8')
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
        'inputQueueAccepted': guarded and result['directInputAccepted'] and result['draftInputAccepted'],
        'keyStore': 'API35 emulator production AndroidKeyStore AES-wrapped seed; native software Ed25519 signing',
        'device': 'disposable API35 Android AVD', 'uiDriver': 'Flutter SDK integration_test public text/tap controls',
        'frameEvidence': 'displayed sequence advance on the same production Terminal object after initial full',
        'storageMocked': False, 'signerInjected': False, 'framesInjected': False,
        'flutterToolchain': toolchain, 'deviceApi': 35, 'deviceCleanup': cleanup}
