"""Owned API35 product JNI start/status diagnostic. Never logs in or dials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

from android_dual_overlay_session import AndroidDualOverlaySession
from android_dual_overlay_reverse import SERIAL, assert_owned_avd
from flutter_android_dual_overlay import prepare_private_ca

PACKAGE = 'dev.herdr.herdr_flutter_probe'
LIBRARIES = ('libheeler_easytier.so', 'libhp_tailscale.so', 'libherdr_flutter_network_runtime.so')
BOOLS = {'loginInvoked', 'dialInvoked', 'librariesLoaded', 'contextBound', 'identityCreated', 'identityReadBack',
    'nativeScopeCreated', 'providerAvailable', 'availableOk', 'startOk', 'statusOk', 'stopOk', 'needsLoginReached',
    'passed', 'nativeScopeClosed', 'identityDeleted', 'cleanupFailed'}
STATES = {'unavailable', 'stopped', 'starting', 'engine-started', 'needs-login', 'needs-machine-auth', 'running', 'closing', 'error', 'other_state'}
ERRORS = {'overlay_provider_unavailable', 'mobile_node_binding_mismatch', 'mobile_node_busy', 'mobile_node_not_started',
    'network_scope_unavailable', 'identity_unavailable', 'invalid_network_request', 'network_failed',
    'cancelled', 'timeout', 'timed_out', 'close_pending', 'state_store_unavailable', 'other_product_error'}
STAGES = {'initialization', 'private-config', 'load-libraries', 'bind-java-context', 'create-identity', 'directory-callback',
    'create-native-scope', 'native-available', 'native-start', 'native-status'}


def safe_probe(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        raise ValueError('probe_result_invalid')
    for key, item in value.items():
        if key == 'schemaVersion':
            continue
        if key in BOOLS:
            valid = type(item) is bool
        elif key in {'availableError', 'startError', 'statusError', 'stopError'}:
            valid = item in ERRORS
        elif key in {'availableState', 'startState', 'statusState', 'stopState'}:
            valid = item in STATES
        elif key in {'lastStage', 'failureStage'}:
            valid = item in STAGES
        elif key == 'failureClass':
            valid = item in {'linkage', 'security', 'controlled_failure'}
        elif key == 'states':
            valid = isinstance(item, list) and len(item) <= 16 and all(state in STATES for state in item)
        elif key == 'directories':
            valid = isinstance(item, dict) and set(item) == {'coreDirectoryPrepared', 'productDirectoryCallbackSucceeded', 'root', 'runtime', 'identity'}
            if valid:
                valid = all(type(item[name]) is bool for name in ('coreDirectoryPrepared', 'productDirectoryCallbackSucceeded'))
                allowed = {'exists', 'directory', 'ownerMatches', 'permissionBits0700', 'fullMode0700', 'setgid'}
                valid = valid and all(isinstance(item[name], dict) and set(item[name]) in ({'exists'}, allowed)
                    and all(type(flag) is bool for flag in item[name].values()) for name in ('root', 'runtime', 'identity'))
        else:
            valid = False
        if not valid:
            raise ValueError('probe_result_invalid')
    if value.get('loginInvoked') is not False or value.get('dialInvoked') is not False:
        raise ValueError('probe_operation_boundary_invalid')
    return value


def verify_apk(apk, libraries):
    hashes = {}
    with zipfile.ZipFile(apk) as archive:
        for name in LIBRARIES:
            binary = archive.read('lib/x86_64/' + name)
            expected = (libraries / name).read_bytes()
            if binary != expected:
                raise ValueError('probe_apk_native_mismatch')
            hashes[name] = hashlib.sha256(binary).hexdigest()
    return hashes


def run(args):
    assert_owned_avd()
    output = {'schemaVersion': 1, 'status': 'failed', 'scope': 'owned API35 real AndroidKeyStore and fixed product JNI TS start/status/stop; no GUI, login or application dial',
        'runnerSource': os.environ['GITHUB_SHA'], 'nativeSource': args.native_source, 'hostSource': args.host_source, 'variants': []}
    def adb(*parts, data=None, timeout=30):
        return subprocess.run(['adb', '-s', SERIAL, *parts], input=data, capture_output=True, timeout=timeout, check=False)
    try:
        for variant in ('normal', 'qa'):
            row = {'variant': variant, 'status': 'failed'}
            output['variants'].append(row)
            apk, libraries = args.apk_root / (variant + '.apk'), getattr(args, variant)
            row['librariesSha256'] = verify_apk(apk, libraries)
            row['apkSha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
            if adb('shell', 'pm', 'path', PACKAGE).stdout.strip():
                raise ValueError('probe_package_already_present')
            installed = False
            session = AndroidDualOverlaySession(args.bundle, args.work_root, host_source=args.host_source,
                source_checkout=args.source_checkout, lifetime=600)
            try:
                with session:
                    row['controlBefore'] = session.control.call({'op': 'ts_diagnostics'})
                    result = adb('install', '-t', str(apk), timeout=60)
                    if result.returncode != 0 or b'Success' not in result.stdout:
                        raise ValueError('probe_install_failed')
                    installed = True
                    prepare_private_ca('adb', SERIAL, session.read_ca(), run=subprocess.run)
                    prefix = ('shell', '-T', 'run-as', PACKAGE)
                    config = json.dumps({'controlUrl': session.materials['controlUrl']}).encode()
                    if adb(*prefix, 'tee', 'files/ts-node-probe-config.json', data=config).returncode:
                        raise ValueError('probe_config_failed')
                    if adb(*prefix, 'chmod', '600', 'files/ts-node-probe-config.json').returncode:
                        raise ValueError('probe_config_failed')
                    result = adb('shell', 'am', 'instrument', '-w', '-r', PACKAGE + '/dev.herdr.tsnodeprobe.ProbeInstrumentation', timeout=100)
                    row['instrumentationCommandSucceeded'] = result.returncode == 0
                    response = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-node-probe-result.json')
                    if response.returncode == 0 and len(response.stdout) <= 16384:
                        row['probe'] = safe_probe(json.loads(response.stdout))
                    else:
                        row['probeResultUnavailable'] = True
                    row['controlAfter'] = session.control.call({'op': 'ts_diagnostics'})
                    row['noSshAuthentication'] = all(session.control.call({'op': 'audit', 'role': role,
                        'expectedBase64': ''})['acceptedSessions'] == 0 for role in ('et', 'ts'))
                    if installed:
                        row['packageRemoved'] = adb('uninstall', PACKAGE).returncode == 0 and not adb('shell', 'pm', 'path', PACKAGE).stdout.strip()
                        installed = False
            finally:
                if installed:
                    row['packageRemoved'] = adb('uninstall', PACKAGE).returncode == 0 and not adb('shell', 'pm', 'path', PACKAGE).stdout.strip()
                row['session'] = session.report
            probe = row.get('probe', {})
            if (probe.get('passed') is True and probe.get('stopOk') is True and probe.get('stopState') == 'stopped'
                    and probe.get('nativeScopeClosed') is True and probe.get('identityDeleted') is True
                    and row.get('packageRemoved') is True and row.get('noSshAuthentication') is True
                    and row['session']['cleanup'] and all(row['session']['cleanup'].values())):
                row['status'] = 'passed'
        if len(output['variants']) == 2 and all(row['status'] == 'passed' for row in output['variants']):
            output['status'] = 'passed'
    except Exception:
        output['errorCode'] = 'controlled_node_probe_failed'
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps({'status': output['status'], 'variants': len(output['variants'])}))
    return 0 if output['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'work-root', 'source-checkout', 'normal', 'qa', 'apk-root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--host-source', required=True)
    parser.add_argument('--native-source', required=True)
    raise SystemExit(run(parser.parse_args()))
