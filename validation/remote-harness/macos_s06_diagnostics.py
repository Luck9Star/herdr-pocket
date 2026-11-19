"""Translate private Xcode output to bounded, fixed macOS S06 diagnostics."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

TEST_SELECTION = 'RunnerTests/MacosS06UITests/testTwoPairedPeersInNativeWindow'
STAGES = ('entered', 'channelConfigured', 'releaseRead', 'releaseDecoded', 'targetsValidated',
          'channelRoundTrip', 'display', 'homepage', 'pairA', 'pairB', 'keyA', 'keyB',
          'connectA', 'connectB', 'split', 'frames', 'keyboard', 'resize', 'autoResume', 'stop', 'remove')
PAIR_CONTROLS = {'entry', 'host', 'port', 'user', 'session', 'socket', 'herdr', 'hostKey', 'device',
                 'fingerprint', 'targetReview', 'create', 'copy', 'response', 'preview', 'sourceReview',
                 'accept', 'connect', 'back'}
PAIR_AX_COUNTS = ('named', 'expectedRole', 'withinRegion', 'hittable', 'enabled', 'namedTextViews',
                  'namedEditableChildren', 'formTitleHittable', 'storageUnavailableHittable')
PAIR_INPUT_STEPS = {'click', 'focus', 'selectDefault', 'typing', 'pasting', 'typed', 'copy', 'verified'}
PAIR_DEFAULT_RELATIONS = {'unavailable', 'empty', 'exact', 'defaultValue', 'defaultBefore', 'defaultAfter', 'other'}
PAIR_READ_BITS = ('ownerAXBeforeExact', 'ownerAXAfterExact', 'ownedEditorPresent',
                  'ownedEditorAXExact', 'clipboardChanged', 'clipboardExact')
CHANNEL_FAILURES = {'scope_invalid', 'message_rejected', 'topic_occupied', 'prepare_denied',
                    'item_rejected', 'write_denied', 'read_unavailable', 'cleanup_failed'}
FAILURES = {'private_channel_send_failed', 'private_channel_receive_failed',
            'private_release_unavailable', 'private_channel_receipt_missing', 'private_channel_receipt_mismatch',
            'private_release_decode_failed', 'private_fixture_binding_invalid', 'display_unavailable',
            'isolated_display_too_small', 'native_window_missing', 'native_window_origin_not_reached',
            'native_window_width_not_reached', 'native_window_height_not_reached',
            'unique_visible_control_missing', 'public_value_not_read_back', 'public_request_unavailable',
            'public_clipboard_write_failed', 'public_pair_field_owner_lost', 'public_pair_window_changed',
            'public_pair_click_geometry_unstable', 'public_pair_focus_image_unavailable', 'public_pair_focus_unproven',
            'public_pair_default_not_selected',
            'reviewed_host_response_unavailable', 'reviewed_host_response_invalid',
            'peer_close_unconfirmed_while_window_running', 'peer_close_receipt_invalid', 'native_visible_peer_marker_missing',
            'native_visible_peer_marker_mismatch', 'native_visible_tick_invalid',
            'native_visible_snapshot_field_unavailable', 'native_visible_snapshot_copy_control_unavailable',
            'native_visible_snapshot_copy_unavailable', 'native_resumed_peer_tick_not_fresh',
            'native_tab_focus_unreachable', 'unexpected_native_error'} | {
                'private_channel_' + failure for failure in CHANNEL_FAILURES}
STARTUP = {
    'noTestsSelected': ('no tests were found', 'no tests were run', 'no matching test cases'),
    'runnerLaunchFailed': ('test runner failed to initialize', 'failed to launch test runner',
                           'unable to launch the test runner'),
    'runnerConnectionLost': ('early unexpected exit', 'lost connection to the test runner',
                             'test runner exited'),
    'accessibilityDenied': ('not authorized to use accessibility', 'accessibility access is not enabled',
                             'not authorized to control'),
    'renderDestinationUnavailable': ('unable to find a destination', 'destination is not eligible'),
}
SUMMARY_FIELDS = ('totalTestCount', 'passedTests', 'failedTests', 'skippedTests')
MAX_LOG_BYTES = 4 * 1024 * 1024


def private_log(log):
    try:
        with log.open('rb') as stream:
            head = stream.read(MAX_LOG_BYTES // 2)
            if stream.read(1):
                size = stream.seek(0, 2)
                stream.seek(max(len(head), size - MAX_LOG_BYTES // 2))
                head += b'\n' + stream.read(MAX_LOG_BYTES // 2)
        return head.decode('utf-8', errors='replace')
    except OSError:
        return ''


def log_facts(text):
    observed = re.findall(r'^\s*HP_S06_NATIVE_STAGE=([a-zA-Z0-9]+)\s*$', text, re.M)
    stages = [stage for stage in observed if stage in STAGES]
    failures = re.findall(r'^\s*HP_S06_NATIVE_FAILURE=([a-z_]+)\s*$', text, re.M)
    facts = {'loggedStages': list(dict.fromkeys(stages)),
             'testCaseStarted': bool(re.search(
                 r"^\s*Test Case '[^'\n]*MacosS06UITests[ .]testTwoPairedPeersInNativeWindow[^'\n]*' started\.",
                 text, re.M))}
    if stages:
        facts['lastLoggedStage'] = stages[-1]
    fixed = [failure for failure in failures if failure in FAILURES]
    if fixed:
        facts['fixedFailure'] = fixed[-1]
    events = list(re.finditer(r'^HP_S06_NATIVE_PAIR_CONTROL=([A-Za-z]+)[ \t]*$', text, re.M))
    controls = [event for event in events if event[1] in PAIR_CONTROLS]
    if controls:
        control = controls[-1][1]
        current = text[controls[-1].end():]
        facts['lastPairControl'] = control
        pattern = r'^HP_S06_NATIVE_PAIR_AX=' + control + r'((?:,[0-9]{1,2}){9})[ \t]*$'
        for values in re.findall(pattern, current, re.M):
            counts = list(map(int, values[1:].split(',')))
            if counts[1] >= counts[2] >= counts[3] >= counts[4]:
                facts['pairControlFailure'] = {'control': control, **dict(zip(PAIR_AX_COUNTS, counts))}
        pattern = r'^HP_S06_NATIVE_PAIR_INPUT=' + control + r',([A-Za-z]+)[ \t]*$'
        steps = [step for step in re.findall(pattern, current, re.M) if step in PAIR_INPUT_STEPS]
        if steps:
            facts['lastPairInputStep'] = steps[-1]
        if control in {'port', 'device'}:
            pattern = r'^HP_S06_NATIVE_PAIR_VALUE=' + control + r',(before|after),([A-Za-z]+)[ \t]*$'
            comparisons = {step: relation for step, relation in re.findall(pattern, current, re.M)
                           if relation in PAIR_DEFAULT_RELATIONS}
            if comparisons:
                facts['pairDefaultComparisons'] = comparisons
        pattern = r'^HP_S06_NATIVE_PAIR_READ=' + control + r',([01]{6})[ \t]*$'
        for bits in re.findall(pattern, current, re.M):
            if (bits[3] <= bits[2] and bits[5] <= bits[4]):
                facts['pairReadback'] = {'control': control, **dict(zip(PAIR_READ_BITS, (b == '1' for b in bits)))}
    lower = text.lower()
    facts['startupFlags'] = [name for name, patterns in STARTUP.items() if any(p in lower for p in patterns)]
    lines = {int(line) for line in re.findall(r'RunnerTests\.swift:(\d{1,5}):(?:\d+:)?\s*error:', text)}
    facts['testSourceFailureLines'] = sorted(line for line in lines if 1 <= line <= 9999)[:12]
    return facts


def checked_summary(raw):
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in SUMMARY_FIELDS
            if type(raw.get(key)) is int and 0 <= raw[key] <= 1024}


def xcresult_summary(bundle):
    if not bundle.is_dir():
        return {}
    try:
        with tempfile.TemporaryFile() as stream:
            tool = subprocess.run(
                ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary',
                 '--path', str(bundle), '--format', 'json'],
                stdout=stream, stderr=subprocess.DEVNULL, timeout=15, check=False)
            if tool.returncode != 0:
                return {}
            stream.seek(0)
            data = stream.read(65537)
        return checked_summary(json.loads(data)) if len(data) <= 65536 else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def diagnostics(log: Path, bundle: Path, exit_code):
    report = log_facts(private_log(log))
    report['xcresultPresent'] = bundle.is_dir()
    report['xcresultTestCounts'] = xcresult_summary(bundle)
    if type(exit_code) is int and -255 <= exit_code <= 255:
        report['xcodeExitCode'] = exit_code
    return report
