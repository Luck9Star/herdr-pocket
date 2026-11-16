"""Owned API35 product JNI start/status diagnostic. Never logs in or dials."""
import argparse
import hashlib
import json
import os
import re
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
    'passed', 'nativeScopeClosed', 'identityDeleted', 'cleanupFailed', 'netmonOptIn'}
STATES = {'unavailable', 'stopped', 'starting', 'engine-started', 'needs-login', 'needs-machine-auth', 'running', 'closing', 'error', 'other_state'}
ERRORS = {'overlay_provider_unavailable', 'mobile_node_binding_mismatch', 'mobile_node_busy', 'mobile_node_not_started',
    'network_scope_unavailable', 'identity_unavailable', 'invalid_network_request', 'network_failed',
    'cancelled', 'timeout', 'timed_out', 'close_pending', 'state_store_unavailable', 'other_product_error'}
STAGES = {'initialization', 'private-config', 'load-libraries', 'bind-java-context', 'create-identity', 'directory-callback',
    'create-native-scope', 'native-available', 'native-start', 'native-status', 'netmon-diagnose'}

NETMON_ERR_CLASSES = {'', 'none', 'permission', 'empty', 'other'}
NETMON_PATHS = {'goNet', 'getifaddrs'}


def _safe_netmon_diagnose(item):
    # Mirrors the committed netmon.go JSON schema exactly. Go marshals zero
    # values: stateBuilt=true means stateErrClass stays "" (set only on
    # failure), and a path that never executed keeps ok=false with errClass "".
    # The Java reader may instead produce the single-key sentinels
    # fileMissing/parseError; both pass through as-is.
    if not isinstance(item, dict):
        return False
    if set(item) == {'fileMissing'} or set(item) == {'parseError'}:
        return item.get('fileMissing') is True or item.get('parseError') is True
    if set(item) != {
            'event', 'getterRegistered', 'getterCalls', 'paths', 'selected',
            'stateBuilt', 'stateErrClass', 'haveV4', 'haveV6', 'anyUp'}:
        return False
    if item['event'] != 'netmon_diagnose' or type(item['getterRegistered']) is not bool:
        return False
    if type(item['getterCalls']) is not int or item['getterCalls'] < 0:
        return False
    if item['selected'] not in NETMON_PATHS | {'none'}:
        return False
    if not all(type(item[name]) is bool for name in ('stateBuilt', 'haveV4', 'haveV6', 'anyUp')):
        return False
    if item['stateErrClass'] not in NETMON_ERR_CLASSES:
        return False
    if item['stateBuilt'] and item['stateErrClass'] != '':
        return False
    if not item['stateBuilt'] and item['stateErrClass'] not in ('empty', 'permission', 'other'):
        return False
    paths = item['paths']
    if not isinstance(paths, list) or len(paths) > 2 or [p.get('path') if isinstance(p, dict) else None for p in paths] != ['goNet', 'getifaddrs'][:len(paths)]:
        return False
    for p in paths:
        if not isinstance(p, dict) or set(p) != {'path', 'ok', 'errClass', 'interfaces', 'addresses'}:
            return False
        if type(p['ok']) is not bool or p['errClass'] not in NETMON_ERR_CLASSES:
            return False
        if type(p['interfaces']) is not int or p['interfaces'] < 0 or type(p['addresses']) is not int or p['addresses'] < 0:
            return False
        if p['ok'] and p['errClass'] != 'none':
            return False
        if not p['ok'] and p['errClass'] == 'none':
            return False
    return True


def safe_probe(value):
    if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int or value.get('schemaVersion') != 1:
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
        elif key == 'javaInterfaces':
            valid = (isinstance(item, dict) and set(item) == {'ok', 'interfaces', 'addresses', 'errClass'}
                and type(item['ok']) is bool and type(item['interfaces']) is int
                and type(item['addresses']) is int and isinstance(item['errClass'], str)
                and item['interfaces'] >= 0 and item['addresses'] >= 0
                and (item['errClass'] == '' or item['errClass'].isidentifier()))
            if valid and item['ok'] and (item['errClass'] != '' or item['interfaces'] == 0):
                valid = False
            if valid and not item['ok'] and item['errClass'] == '':
                valid = False
        elif key == 'netmonDiagnose':
            valid = _safe_netmon_diagnose(item)
        else:
            valid = False
        if not valid:
            raise ValueError('probe_result_invalid')
    if value.get('loginInvoked') is not False or value.get('dialInvoked') is not False:
        raise ValueError('probe_operation_boundary_invalid')
    return value


def probe_report(raw):
    if len(raw) > 65536:
        return {'probeReport': 'oversize'}
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        return {'probeReport': 'not-json', 'reportFileMissing': b'No such file or directory' in raw}
    try:
        return {'probeReport': 'valid', 'probe': safe_probe(value)}
    except (ValueError, TypeError):
        partial = {'schemaVersion': 1, 'loginInvoked': False, 'dialInvoked': False}
        rejected = []
        if isinstance(value, dict):
            for key, item in value.items():
                if key in partial:
                    if item != partial[key] or type(item) is not type(partial[key]): rejected.append('boundary')
                    continue
                try:
                    safe_probe(dict(partial, **{key: item}))
                    partial[key] = item
                except (ValueError, TypeError):
                    rejected.append(key if key in BOOLS | {'directories', 'states', 'lastStage', 'failureStage', 'failureClass'} else 'other-field')
        for key in ('loginInvoked', 'dialInvoked'):
            if not isinstance(value, dict) or value.get(key) is not False:
                partial.pop(key, None)
        return {'probeReport': 'schema-rejected', 'probePartial': partial, 'rejectedFields': sorted(set(rejected))}



def instrument_summary(result):
    raw = result.stdout[:65536]
    codes = re.findall(rb'^INSTRUMENTATION_CODE: (-?[0-9]+)\r?$', raw, re.MULTILINE)
    code = codes[-1].decode() if len(codes) == 1 and codes[0] in (b'-1', b'0', b'1') else 'other'
    summary = {'commandSucceeded': result.returncode == 0, 'finished': len(codes) == 1,
        'returnCode': code, 'processCrash': b'Process crashed' in raw or b'Process crash' in raw,
        'instrumentationFailed': b'INSTRUMENTATION_FAILED' in raw}
    # Crash lines can come from debuggerd/crash_dump64 with their own PID, so
    # this works on the merged am-instrument output rather than filtered
    # logcat. Keep "reported by am" separate from hard signal evidence.
    signals = re.findall(rb'Fatal signal (\d+)', raw)
    panics = re.findall(rb'panic: ([a-zA-Z0-9_.:\- ]+)', raw)
    frames = re.findall(rb'herdr\.local/tailscale-runtime\.(\w+)', raw)
    upstream_frames = re.findall(rb'tailscale\.com/([\w/.]+)\.', raw)
    if signals or panics or summary['processCrash'] or summary['instrumentationFailed']:
        # Bounded, redacted crash forensics: signal number, panic type and Go
        # frame names only. Never addresses, paths, keys or full logs.
        summary['crashSignals'] = sorted({int(s) for s in signals})[:4]
        summary['panicTypes'] = sorted({p.decode('ascii', 'replace') for p in panics})[:3]
        summary['goFrames'] = sorted({f.decode('ascii', 'replace') for f in frames})[:8]
        summary['upstreamFrames'] = sorted({f.decode('ascii', 'replace') for f in upstream_frames})[:8]
        summary['signalEvidence'] = bool(signals or panics)
    return summary


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


def netmon_diagnose_collected(variants):
    return bool(variants) and all(isinstance(row.get('probe', {}).get('netmonDiagnose'), dict) for row in variants)


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
                    installed_path = adb('shell', 'pm', 'path', PACKAGE)
                    lines = installed_path.stdout.decode('ascii').strip().splitlines()
                    if (installed_path.returncode or len(lines) != 1 or
                            not re.fullmatch(r'package:/data/app/[A-Za-z0-9_./=+~\-]+/base\.apk', lines[0])
                            or '/../' in lines[0]):
                        raise ValueError('probe_installed_apk_path_invalid')
                    installed_apk = adb('exec-out', 'cat', lines[0][len('package:'):], timeout=60)
                    if installed_apk.returncode or hashlib.sha256(installed_apk.stdout).hexdigest() != row['apkSha256']:
                        raise ValueError('probe_installed_apk_mismatch')
                    row['installedApkSha256'] = hashlib.sha256(installed_apk.stdout).hexdigest()
                    del installed_apk
                    prepare_private_ca('adb', SERIAL, session.read_ca(), run=subprocess.run)
                    prefix = ('shell', '-T', 'run-as', PACKAGE)
                    config = json.dumps({'controlUrl': session.materials['controlUrl']}).encode()
                    if adb(*prefix, 'tee', 'files/ts-node-probe-config.json', data=config).returncode:
                        raise ValueError('probe_config_failed')
                    if adb(*prefix, 'chmod', '600', 'files/ts-node-probe-config.json').returncode:
                        raise ValueError('probe_config_failed')
                    try:
                        result = adb('shell', 'am', 'instrument', '-w', '-r', PACKAGE + '/dev.herdr.tsnodeprobe.ProbeInstrumentation', timeout=100)
                        row['instrumentation'] = instrument_summary(result)
                        # debuggerd/crash_dump64 lines carry their own PID, so
                        # merge the crash buffer attributed by process name
                        # into the same redacted forensics.
                        crash_log = adb('shell', 'logcat', '-d', '-b', 'crash', timeout=30)
                        if crash_log.returncode == 0:
                            attributed = b''.join(line for line in crash_log.stdout.splitlines(keepends=True)
                                if PACKAGE.encode() in line or b'libhp_tailscale' in line
                                or b'>>> dev.herdr' in line)
                            merged = instrument_summary(type('R', (), {'returncode': 0, 'stdout': attributed})())
                            for key in ('crashSignals', 'panicTypes', 'goFrames', 'upstreamFrames', 'signalEvidence'):
                                if key in merged and merged[key]:
                                    combined = row['instrumentation'].get(key)
                                    if isinstance(merged[key], list):
                                        combined = sorted(set((combined or []) + merged[key]))[:8]
                                    row['instrumentation'][key] = combined if isinstance(merged[key], list) else merged[key]
                    except subprocess.TimeoutExpired:
                        row['instrumentation'] = {'commandSucceeded': False, 'timedOut': True}
                    response = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-node-probe-result.json')
                    if response.returncode == 0:
                        row.update(probe_report(response.stdout))
                    else:
                        row['probeReport'] = 'cat-failed'
                    row['controlAfter'] = session.control.call({'op': 'ts_diagnostics'})
                    counter_keys = ('keyRequests', 'noiseRequests', 'registerRequests', 'mapRequests', 'tlsHandshakeErrors', 'authCompletions')
                    delta = {key: row['controlAfter'][key] - row['controlBefore'][key] for key in counter_keys}
                    if any(value < 0 for value in delta.values()):
                        raise ValueError('probe_control_counters_not_monotonic')
                    row['controlDelta'] = delta
                    row['noNewAuthorizationOrRegistration'] = delta['registerRequests'] == delta['authCompletions'] == 0
                    row['noSshAuthentication'] = all(session.control.call({'op': 'audit', 'role': role,
                        'expectedBase64': ''})['acceptedSessions'] == 0 for role in ('et', 'ts'))
                    if installed:
                        row['packageRemoved'] = adb('uninstall', PACKAGE).returncode == 0 and not adb('shell', 'pm', 'path', PACKAGE).stdout.strip()
                        installed = False
            except Exception:
                row['errorCode'] = 'controlled_variant_probe_failed'
            finally:
                if installed:
                    row['packageRemoved'] = adb('uninstall', PACKAGE).returncode == 0 and not adb('shell', 'pm', 'path', PACKAGE).stdout.strip()
                row['session'] = session.report
            probe = row.get('probe', {})
            if (probe.get('passed') is True and probe.get('stopOk') is True and probe.get('stopState') == 'stopped'
                    and probe.get('nativeScopeClosed') is True and probe.get('identityDeleted') is True
                    and row.get('packageRemoved') is True and row.get('noSshAuthentication') is True
                    and row.get('noNewAuthorizationOrRegistration') is True
                    and row['session']['cleanup'] and all(row['session']['cleanup'].values())):
                row['status'] = 'passed'
        output['netmonDiagnoseCollected'] = netmon_diagnose_collected(output['variants'])
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
