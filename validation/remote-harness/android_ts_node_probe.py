"""Owned API35 product JNI start/status diagnostic. Never logs in or dials."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
import zipfile

from android_dual_overlay_session import AndroidDualOverlaySession
from android_dual_overlay_reverse import SERIAL, assert_owned_avd
import android_crash_symbolize as symbolize
import android_go_log as golog
from flutter_android_dual_overlay import prepare_private_ca


class Stage:
    """Records the last completed step of a variant run.

    A harness regression must never be reported as a device result, so the
    first failing step is kept next to the error category.
    """

    def __init__(self, name='variant-start'):
        self.name = name

    def reach(self, name):
        self.name = name
        return self

    def report(self, failure):
        return {'failureClass': type(failure).__name__, 'failureStage': self.name}

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
    'create-native-scope', 'native-available', 'native-start', 'native-start-returned', 'native-status', 'netmon-diagnose'}
NUMS = {'startReturnedAfterMs'}
EXIT_REASONS = set(range(15))

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
        elif key == 'diagnosticsLeg':
            valid = item in {'optin', 'plain'}
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
        elif key == 'previousExit':
            valid = (isinstance(item, dict) and set(item) <= {'available', 'reason', 'status', 'timestamp', 'importance', 'errClass'}
                and type(item.get('available')) is bool)
            if valid and item.get('available'):
                valid = (set(item) == {'available', 'reason', 'status', 'timestamp', 'importance'}
                    and item['reason'] in EXIT_REASONS
                    and all(type(item[name]) is int and item[name] >= 0 for name in ('status', 'timestamp', 'importance')))
            elif valid and 'errClass' in item:
                valid = (item['errClass'] == '' or item['errClass'].isidentifier()) and len(item['errClass']) <= 64
        elif key in NUMS:
            valid = type(item) is int and item >= 0
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


PANIC_CLASSES = (
    (b'nil pointer dereference', 'nil-dereference'),
    (b'index out of range', 'index-out-of-range'),
    (b'slice bounds out of range', 'slice-out-of-range'),
    (b'invalid memory address', 'invalid-memory-address'),
    (b'divide by zero', 'divide-by-zero'),
    (b'all goroutines are asleep', 'deadlock'),
    (b'concurrent map', 'concurrent-map'),
)


ABI_BOOLS = {'abiShimOk', 'librariesLoaded', 'identityCreated', 'identityReadBack',
    'netmonOptIn', 'abiStatusFilePresent', 'completed', 'uidMatches',
    'mappedLibraryPresent', 'libraryDigestMatches', 'mappedLibraryPathMatches',
    'storeCountsPresent'}


def safe_abi_probe(value):
    """Bounded schema for the ABI leg's result file.

    The ABI leg is a separate process, so its report is validated
    independently of the main probe's schema.
    """
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        raise ValueError('abi_probe_invalid')
    for key, item in value.items():
        if key == 'schemaVersion':
            continue
        if key in ABI_BOOLS:
            valid = type(item) is bool
        elif key == 'abiShimCode':
            valid = type(item) is int and 0 <= item <= 8
        elif key in ('storeReads', 'storeWrites', 'engineStartCode'):
            valid = type(item) is int and 0 <= item <= 100000
        elif key == 'errClass':
            valid = isinstance(item, str) and (item == '' or item.isidentifier()) and len(item) <= 64
        elif key == 'targetPackage':
            valid = isinstance(item, str) and item == 'dev.herdr.herdr_flutter_probe'
        elif key == 'netmonDiagnose':
            valid = _safe_netmon_diagnose(item)
        else:
            valid = False
        if not valid:
            raise ValueError('abi_probe_invalid')
    return value


def collect_abi_evidence(adb, expected_digest):
    """Read fixed-path ABI evidence even when the ABI process aborted."""
    evidence = {}
    response = adb('exec-out', 'run-as', PACKAGE, 'cat',
                   'files/hp-probe-abi/node/netmon-diagnose.json')
    if response.returncode == 0:
        try:
            value = json.loads(response.stdout)
            evidence['diagnose'] = value if _safe_netmon_diagnose(value) else 'schema-rejected'
        except (ValueError, TypeError, UnicodeError):
            evidence['diagnose'] = 'not-json'
    else:
        evidence['diagnose'] = 'file-missing'

    library = {'pathAvailable': False, 'digestAvailable': False, 'digestMatches': False}
    response = adb('exec-out', 'run-as', PACKAGE, 'cat',
                   'files/hp-probe-abi/hp-probe-abi-library.txt')
    if response.returncode == 0:
        try:
            path = response.stdout.decode('ascii').strip()
        except UnicodeError:
            path = ''
        if path.startswith('/') and len(path) <= 4096 and '\n' not in path:
            library['pathAvailable'] = True
            mapped = adb('exec-out', 'run-as', PACKAGE, 'cat', path)
    evidence['library'] = library

    store = {'present': False, 'reads': 0, 'writes': 0, 'startCode': 0}
    response = adb('exec-out', 'run-as', PACKAGE, 'cat',
                   'files/hp-probe-abi/hp-probe-abi-store.txt')
    if response.returncode == 0:
        store['present'] = True
        for line in response.stdout.decode('ascii', 'replace').splitlines():
            parts = line.strip().split('=')
            if len(parts) != 2 or not parts[1].isdigit():
                continue
            value = int(parts[1])
            if parts[0] == 'read':
                store['reads'] = value
            elif parts[0] == 'write':
                store['writes'] = value
            elif parts[0] == 'start':
                store['startCode'] = value
    evidence['store'] = store

    # Stage markers: separate files, never overwritten, so the last marker
    # present is the stage that was reached before the process died.
    stages = {}
    for name in ('library-mapped', 'abi-version', 'node-new', 'node-status',
                 'node-start-entered', 'node-start-returned',
                 'node-status-after-start', 'node-close-entered',
                 'node-close-returned', 'node-release-entered',
                 'node-release-returned'):
        response = adb('exec-out', 'run-as', PACKAGE, 'cat',
                       'files/hp-probe-abi/hp-probe-abi-stage-%s.txt' % name)
        stages[name] = response.returncode == 0
    evidence['stages'] = stages

    expected = {'present': False, 'digestMatches': False}
    response = adb('exec-out', 'run-as', PACKAGE, 'cat',
                   'files/hp-probe-abi/hp-probe-abi-expected-digest.txt')
    if response.returncode == 0:
        digest = response.stdout.decode('ascii', 'replace').strip()
        expected['present'] = len(digest) == 64
        if expected['present']:
            expected['sha256'] = digest
            expected['digestMatches'] = digest == expected_digest
    evidence['expectedLibrary'] = expected
    return evidence


def _panic_class(line):
    for needle, name in PANIC_CLASSES:
        if needle in line:
            return name
    return 'other'


def _redacted_forensics(text):
    """Extract bounded crash evidence from am output or one crash record.

    A tombstone record is attributed as a whole (*** *** *** header through
    the next separator): the Cmdline line binds it to this run's package,
    while signal/frame lines carry debuggerd's own PID, so line-level
    filtering would shred the record. Output is counts and whitelisted names
    only - never raw panic text, addresses, paths or keys.
    """
    tombstone = sorted({int(s) for s in re.findall(rb'signal (\d+) \(', text)})[:4]
    fatal = sorted({int(s) for s in re.findall(rb'Fatal signal (\d+)', text)})[:4]
    signals = sorted(set(tombstone) | set(fatal))[:4]
    panics = sorted({_panic_class(l) for l in text.splitlines()
        if b'panic: ' in l})[:3]
    frames = sorted({f.decode('ascii', 'replace') for f in
        re.findall(rb'herdr\.local/tailscale-runtime\.(\w+)', text)})[:8]
    upstream = sorted({f.decode('ascii', 'replace') for f in
        re.findall(rb'tailscale\.com/([\w/.]+(?=\.\(\*?[\w.]+\))|[\w/.]+(?=\.))', text)})[:8]
    return {'crashSignals': signals, 'panicTypes': panics,
        'goFrames': frames, 'upstreamFrames': upstream}

def _current_exit_info():
    """This run's own exit record via package-scoped dumpsys exit-info.

    Redacted to reason class and status only; never the trace blob. Runs
    after am instrument (return or timeout) and before uninstall, so the
    record belongs to the process that just died or finished.
    """
    try:
        result = adb('shell', 'dumpsys', 'activity', 'exit-info', PACKAGE, timeout=30)
        if result.returncode != 0:
            return {'available': False}
        text = result.stdout.decode('ascii', 'replace')
        reasons = re.findall(r'reason=(\d+)', text)
        statuses = re.findall(r'status=(\d+)', text)
        latest_reason = int(reasons[0])
        if latest_reason not in EXIT_REASONS:
            latest_reason = 15
        return {'available': True, 'reason': latest_reason,
                'status': int(statuses[0]) if statuses else -1}
    except Exception:
        return {'available': False}


ABORT_CLASSES = (
    (b'CheckJNI', 'jni-checkjni'),
    (b'JNI DETECTED', 'jni-checkjni'),
    (b'panicked at', 'rust-panic'),
    (b'panic: ', 'go-panic'),
    (b'fatal error:', 'go-fatal'),
    (b'runtime error:', 'go-runtime-error'),
    (b'ownership of fd', 'capture-self-fdsan'),
    (b'fdsan', 'capture-self-fdsan'),
    (b'assertion failed', 'libc-assert'),
    (b'__pthread', 'pthread'),
)

def _abort_class(record):
    # Prefer the Abort message line; fall back to a whole-record scan so a
    # standalone "JNI DETECTED ERROR IN APPLICATION" line still classifies.
    # android_set_abort_message truncates near 128 bytes, so match on the
    # leading part of the message as well.
    abort_lines = [l for l in record.splitlines() if b'Abort message:' in l]
    for line in abort_lines + record.splitlines():
        for needle, name in ABORT_CLASSES:
            if needle in line:
                return name
    return 'other'


def _module_basenames(record):
    # Tombstone frame lines: '#00 pc <addr> /path/to/libX.so (off)' and the
    # AOSP 'APK !libX.so' form. Only the bare module name is kept.
    names = []
    for match in re.finditer(rb'(?:#[0-9]+ pc [0-9a-f]+ \S*/([\w.\-]+\.so))|(?:!\(?([\w.\-]+\.so)\)?)', record):
        name = (match.group(1) or match.group(2)).decode('ascii', 'replace')
        if name not in names:
            names.append(name)
    return names[:8]


def _thread_names(record):
    """Thread identity from the tombstone header and the fatal-signal line.

    The Rust node thread is named overlay-node-st (15-char truncation), a
    JNI-attached Java thread shows as Thread-N, and a plain Go scheduler
    thread has no pthread name. This classifies the aborting thread even
    when the backtrace stays empty.
    """
    names = []
    for match in re.finditer(rb'>>> ([^\n\r]+) <<<', record):
        name = match.group(1).decode('ascii', 'replace').strip()
        # The >>> header is the process name, not a thread; the pid/tid/name
        # line below carries the thread identity.
        if name and PACKAGE not in name and name not in names:
            names.append(name)
    for match in re.finditer(rb'\bpid: (\d+), tid: (\d+), name: ([^\n\r]+)', record):
        name = match.group(3).decode('ascii', 'replace').strip()
        if name and name not in names:
            names.append(name)
    for match in re.finditer(rb'Fatal signal \d+ \([A-Z]+\).*?\(tid (\d+), ([^)]*)\)', record):
        name = match.group(2).decode('ascii', 'replace').strip()
        if name and name not in names:
            names.append(name)
    return names[:6]


def _stderr_evidence():
    """Redacted evidence from the probe's own stderr file.

    A fatal error that exits without a signal (Go runtime fatal, direct
    exit) writes only to stderr; the file survives the dead process. Only
    classified panic/fatal kinds and function names are reported, never the
    original text, addresses or paths.
    """
    try:
        result = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-node-probe-stderr.txt')
        # Remove it either way: both variants share one package, so the next
        # variant must not read this one's leftovers.
        adb('shell', 'run-as', PACKAGE, 'rm', '-f', 'files/ts-node-probe-stderr.txt', timeout=15)
        if result.returncode != 0 or not result.stdout:
            return {'available': False}
        text = result.stdout[:65536]
        kinds = []
        for needle, name in (
                (b'panicked at', 'rust-panic'),
                (b'fatal error:', 'go-fatal-error'),
                (b'panic: ', 'go-panic'),
                (b'runtime error:', 'runtime-error'),
                (b'concurrent map', 'concurrent-map'),
                (b'goroutine ', 'goroutine-dump'),
                (b'JNI DETECTED ERROR', 'jni-error'),
                (b'ownership of fd', 'fd-ownership'),
                (b'SIGSEGV', 'sigsegv-text'),
                (b'SIGABRT', 'sigabrt-text')):
            if needle in text and name not in kinds:
                kinds.append(name)
        frames = sorted({f.decode('ascii', 'replace') for f in
            re.findall(rb'herdr\.local/tailscale-runtime\.(\w+)', text)})[:8]
        upstream = sorted({f.decode('ascii', 'replace') for f in
            re.findall(rb'tailscale\.com/([\w/.]+(?=\.\(\*?[\w.]+\))|[\w/.]+(?=\.))', text)})[:8]
        panic_classes = sorted({_panic_class(l) for l in text.splitlines()
            if b'panic: ' in l or b'panicked at' in l})[:3]
        if not kinds and not frames and not upstream and not panic_classes:
            return {'available': False}
        return {'available': True, 'kinds': kinds[:6], 'panicTypes': panic_classes,
                'goFrames': frames, 'upstreamFrames': upstream}
    except Exception:
        return {'available': False}


def _go_log_evidence(adb, pid):
    """Classify this process's own `Go` log lines.

    `logcat -s Go:E` is the Go runtime's panic channel. The tag carries no
    package name, so the lines are selected by this leg's pid. The shared
    stderr file is not read here: it belongs to whichever process last
    redirected descriptor 2, not necessarily this pid.
    """
    if not pid:
        return {'available': False}
    try:
        # -v threadtime pins the format: the default brief format prints
        # "E/Go( 4242):", which the classifier does not read.
        result = adb('shell', 'logcat', '-d', '-v', 'threadtime', '-b', 'main',
                     '--pid', str(pid), '-s', 'Go:E', timeout=30)
    except Exception:
        return {'available': False}
    if result.returncode != 0:
        return {'available': False}
    return safe_go_log(golog.classify(result.stdout[:131072]))


GO_PANIC_CLASSES = {'go-panic', 'go-fatal', 'go-throw', 'other'}
GO_REASONS = {'nil-pointer', 'index-out-of-range', 'slice-bounds', 'makeslice',
    'send-on-closed-channel', 'close-closed-channel', 'close-nil-channel',
    'concurrent-map', 'deadlock', 'unexpected-signal', 'interface-conversion',
    'divide-by-zero', 'negative-shift', 'nil-map', 'unlock-unlocked-mutex',
    'negative-waitgroup', 'runtime-error', 'unspecified'}


def safe_go_log(value):
    """Keep only the whitelisted enums and bounded symbols."""
    if not isinstance(value, dict) or value.get('available') is not True:
        return {'available': False}
    panic_class = value.get('panicClass')
    reason = value.get('reason')
    app = value.get('appFunction') or 'none'
    first = value.get('firstFrame') or 'none'
    upstream = value.get('upstreamFrames') or []
    if panic_class not in GO_PANIC_CLASSES or reason not in GO_REASONS:
        return {'available': False}
    # A symbol that fails the syntax check is dropped; the rest of the
    # evidence stays, because one odd frame must not hide the panic kind.
    if not _safe_symbol(app):
        app = 'none'
    if not _safe_symbol(first):
        first = 'none'
    kept = [name for name in upstream[:3]
            if _safe_symbol(name) and name.startswith('tailscale.com/')]
    return {'available': True, 'panicClass': panic_class, 'reason': reason,
            'appFunction': app, 'firstFrame': first, 'upstreamFrames': kept}


SYMBOL_OK = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:[./][A-Za-z0-9_][A-Za-z0-9_-]*)+')


def _safe_symbol(name):
    """A symbol is 'none' or ASCII package/function syntax, bounded."""
    if name == 'none':
        return True
    return isinstance(name, str) and len(name) <= 160 and bool(SYMBOL_OK.fullmatch(name))

def instrument_summary(result):
    raw = result.stdout[:65536]
    codes = re.findall(rb'^INSTRUMENTATION_CODE: (-?[0-9]+)\r?$', raw, re.MULTILINE)
    code = codes[-1].decode() if len(codes) == 1 and codes[0] in (b'-1', b'0', b'1') else 'other'
    summary = {'commandSucceeded': result.returncode == 0, 'finished': len(codes) == 1,
        'returnCode': code, 'processCrash': b'Process crashed' in raw or b'Process crash' in raw,
        'instrumentationFailed': b'INSTRUMENTATION_FAILED' in raw}
    forensics = _redacted_forensics(raw)
    if any(forensics.values()) or summary['processCrash'] or summary['instrumentationFailed']:
        # am-reported "Process crashed" stays separate from hard evidence.
        summary.update(forensics)
        summary['signalEvidence'] = bool(forensics['crashSignals'] or forensics['panicTypes'])
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
        diagnostics_leg = os.environ.get('PROBE_DIAGNOSTICS', 'optin') == 'optin'
        for variant in ('normal', 'qa'):
            row = {'variant': variant, 'diagnosticsLeg': 'optin' if diagnostics_leg else 'plain', 'status': 'failed'}
            stage = Stage()
            output['variants'].append(row)
            apk, libraries = args.apk_root / (variant + '.apk'), getattr(args, variant)
            library_dir = str(libraries)
            row['librariesSha256'] = verify_apk(apk, libraries)
            row['apkSha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
            if adb('shell', 'pm', 'path', PACKAGE).stdout.strip():
                raise ValueError('probe_package_already_present')
            installed = False
            session = AndroidDualOverlaySession(args.bundle, args.work_root, host_source=args.host_source,
                source_checkout=args.source_checkout, lifetime=600)
            try:
                with session:
                    stage.reach('control-before')
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
                    stage.reach('private-ca')
                    prepare_private_ca('adb', SERIAL, session.read_ca(), run=subprocess.run)
                    prefix = ('shell', '-T', 'run-as', PACKAGE)
                    diagnostics_leg = os.environ.get('PROBE_DIAGNOSTICS', 'optin') == 'optin'
                    config = json.dumps({'controlUrl': session.materials['controlUrl'],
                                         'netmonDiagnose': diagnostics_leg}).encode()
                    if adb(*prefix, 'tee', 'files/ts-node-probe-config.json', data=config).returncode:
                        raise ValueError('probe_config_failed')
                    if adb(*prefix, 'chmod', '600', 'files/ts-node-probe-config.json').returncode:
                        raise ValueError('probe_config_failed')
                    try:
                        stage.reach('abi-leg')
                        # ABI leg first, in its own process: it drives the
                        # same libhp_tailscale.so through the plain C ABI
                        # with an in-memory store, so its result isolates the
                        # Go getter path from the Rust/JNI bridge. If it
                        # aborts, this process dies but the bounded result
                        # file survives for the row below.
                        # Clear the crash buffer before the ABI leg as well:
                        # both variants share one package, so a stale
                        # tombstone from the previous variant would be
                        # misattributed to this leg.
                        adb('shell', 'logcat', '-c', '-b', 'crash', timeout=15)
                        adb('shell', 'run-as', PACKAGE, 'rm', '-f',
                            'files/ts-abi-probe-result.json', 'files/ts-abi-probe-pid.txt', timeout=15)
                        adb('shell', 'run-as', PACKAGE, 'rm', '-rf', 'files/hp-probe-abi', timeout=15)
                        result = adb('shell', 'am', 'instrument', '-w', '-r',
                            PACKAGE + '/org.herdr.network.AbiProbeInstrumentation', timeout=120)
                        row['abiInstrumentation'] = instrument_summary(result)
                        abi_pid_response = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-abi-probe-pid.txt')
                        abi_pid = int(abi_pid_response.stdout.decode('ascii', 'replace').strip()) \
                            if abi_pid_response.returncode == 0 and abi_pid_response.stdout.decode('ascii', 'replace').strip().isdigit() else 0
                        abi_report = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-abi-probe-result.json')
                        if abi_report.returncode == 0:
                            try:
                                row['abiProbe'] = safe_abi_probe(json.loads(abi_report.stdout))
                            except (ValueError, TypeError, UnicodeError):
                                row['abiProbe'] = 'schema-rejected'
                        else:
                            row['abiProbe'] = 'cat-failed'
                        row['abiEvidence'] = collect_abi_evidence(
                            adb, row['librariesSha256']['libhp_tailscale.so'])
                        # Crash attribution for the ABI process uses its own
                        # pid file; the main probe writes its own later.
                        if abi_pid:
                            abi_crash = adb('shell', 'logcat', '-d', '-b', 'crash', timeout=30)
                            if abi_crash.returncode == 0:
                                for record in re.split(rb'\*\*\* \*\*\* \*\*\*', abi_crash.stdout):
                                    if not re.search(rb'\bpid: %d\b' % abi_pid, record):
                                        continue
                                    merged = _redacted_forensics(record)
                                    for key in ('crashSignals', 'panicTypes', 'goFrames', 'upstreamFrames'):
                                        combined = sorted(set(
                                            row['abiInstrumentation'].get(key, []) + merged[key]))
                                        row['abiInstrumentation'][key] = combined[:8]
                                    if merged['crashSignals'] or merged['panicTypes']:
                                        row['abiInstrumentation']['signalEvidence'] = True
                                    for thread in _thread_names(record):
                                        threads = row['abiInstrumentation'].setdefault('abortThreads', [])
                                        if thread not in threads and len(threads) < 6:
                                            threads.append(thread)
                                    abort = _abort_class(record)
                                    if abort != 'other':
                                        row['abiInstrumentation'].setdefault('abortClass', abort)
                                    for module in _module_basenames(record):
                                        mods = row['abiInstrumentation'].setdefault('abortModules', [])
                                        if module not in mods and len(mods) < 8:
                                            mods.append(module)
                                    frames = symbolize.bounded_report(
                                        symbolize.extract_frames(record), library_dir)
                                    if frames:
                                        row['abiInstrumentation']['frames'] = frames
                        # The Go runtime writes its panic to logd under the
                        # tag "Go", which carries no package name: read this
                        # process's own lines by pid before the main leg
                        # clears the buffers.
                        row['abiGoLog'] = _go_log_evidence(adb, abi_pid)
                        # Clear the crash buffer before instrumenting: both
                        # variants share one package, so without this the
                        # second variant would re-read the first one's
                        # tombstone. Clearing after would destroy evidence.
                        adb('shell', 'logcat', '-c', '-b', 'crash', timeout=15)
                        stage.reach('main-probe')
                        result = adb('shell', 'am', 'instrument', '-w', '-r', PACKAGE + '/dev.herdr.tsnodeprobe.ProbeInstrumentation', timeout=100)
                        row['instrumentation'] = instrument_summary(result)
                        def variant_pid():
                            try:
                                listing = adb('exec-out', 'run-as', PACKAGE, 'cat', 'files/ts-node-probe-pid.txt')
                                text = listing.stdout.decode('ascii', 'replace').strip()
                                # Remove it: the next variant writes its own;
                                # a stale pid would misattribute its record.
                                adb('shell', 'run-as', PACKAGE, 'rm', '-f', 'files/ts-node-probe-pid.txt', timeout=15)
                                return int(text) if text.isdigit() else 0
                            except Exception:
                                return 0
                        PID = variant_pid()
                        # Read the Go panic lines now: the main buffer can
                        # roll over during the tombstone window below.
                        row['goLog'] = _go_log_evidence(adb, PID)
                        # Tombstone records are attributed whole: Cmdline
                        # binds the record to this run's package while
                        # signal/frame lines carry debuggerd's own PID, so
                        # line filtering shreds the record.
                        # am instrument may return with only the earliest
                        # "F libc" line; debuggerd needs a bounded window to
                        # finish the full tombstone. Re-read until the record
                        # carries hard evidence or the window closes.
                        def mine_record(block):
                            # Both variants share one package, so a record is
                            # only ours when it names this package, this
                            # variant's process header, or our library; the
                            # per-variant pid guards against taking the
                            # other variant's tombstone in the same window.
                            if PID:
                                if not re.search(rb'\bpid: %d\b' % PID, block):
                                    return False
                            return (PACKAGE.encode() in block or b'>>> dev.herdr' in block
                                    or b'>>> ' in block or b'libhp_tailscale' in block)
                        deadline = time.monotonic() + 45
                        while True:
                            crash_log = adb('shell', 'logcat', '-d', '-b', 'crash', timeout=30)
                            if crash_log.returncode == 0:
                                for record in re.split(rb'\*\*\* \*\*\* \*\*\*', crash_log.stdout):
                                    if not mine_record(record):
                                        continue
                                    merged = _redacted_forensics(record)
                                    for key in ('crashSignals', 'panicTypes', 'goFrames', 'upstreamFrames'):
                                        combined = sorted(set(
                                            row['instrumentation'].get(key, []) + merged[key]))
                                        row['instrumentation'][key] = combined[:8]
                                    for thread in _thread_names(record):
                                        threads = row['instrumentation'].setdefault('abortThreads', [])
                                        if thread not in threads and len(threads) < 6:
                                            threads.append(thread)
                                    if merged['crashSignals'] or merged['panicTypes']:
                                        row['instrumentation']['signalEvidence'] = True
                                    abort = _abort_class(record)
                                    if abort != 'other':
                                        row['instrumentation'].setdefault('abortClass', abort)
                                    for module in _module_basenames(record):
                                        mods = row['instrumentation'].setdefault('abortModules', [])
                                        if module not in mods and len(mods) < 8:
                                            mods.append(module)
                                    frames = symbolize.bounded_report(
                                        symbolize.extract_frames(record), library_dir)
                                    if frames:
                                        row['instrumentation']['frames'] = frames
                            # Full record with hard evidence, or window closed.
                            if row['instrumentation'].get('abortClass') or \
                                    row['instrumentation'].get('abortModules') or \
                                    time.monotonic() >= deadline:
                                break
                            time.sleep(3)
                        # ART reports JNI misuse and libc fatal errors in the
                        # main/system buffers, not in the crash tombstone:
                        # read them too, attributed to this package.
                        for buffer in ('main', 'system'):
                            text_log = adb('shell', 'logcat', '-d', '-b', buffer, timeout=30)
                            if text_log.returncode != 0:
                                continue
                            mine = b'\n'.join(line for line in text_log.stdout.splitlines(keepends=True)
                                if PACKAGE.encode() in line or b'libhp_tailscale' in line
                                or b'JNI DETECTED ERROR' in line or b'Fatal signal' in line)
                            if not mine:
                                continue
                            merged = _redacted_forensics(mine)
                            for key in ('crashSignals', 'panicTypes', 'goFrames', 'upstreamFrames'):
                                combined = sorted(set(
                                    row['instrumentation'].get(key, []) + merged[key]))
                                row['instrumentation'][key] = combined[:8]
                            if merged['crashSignals'] or merged['panicTypes']:
                                row['instrumentation']['signalEvidence'] = True
                            for marker, name in ((b'JNI DETECTED ERROR', 'jni-checkjni'),
                                                 (b'art::', 'art-abort'),
                                                 (b'Fatal signal', 'libc-fatal')):
                                if marker in mine:
                                    row['instrumentation'].setdefault('abortClass', name)
                    except subprocess.TimeoutExpired:
                        row['instrumentation'] = {'commandSucceeded': False, 'timedOut': True}
                    row['currentExit'] = _current_exit_info()
                    row['stderrEvidence'] = _stderr_evidence()
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
            except Exception as failure:
                # Record the error category and the step that failed, so a
                # harness regression can never look like a device result.
                row['errorCode'] = 'controlled_variant_probe_failed'
                row.update(stage.report(failure))
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
    except Exception as failure:
        output['errorCode'] = 'controlled_node_probe_failed'
        output['failureClass'] = type(failure).__name__
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
