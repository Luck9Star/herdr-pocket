"""Translate private Xcode output to bounded, fixed macOS S06 diagnostics."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

TEST_SELECTION = 'RunnerTests/MacosS06UITests/testTwoPairedPeersInNativeWindow'
STAGES = ('entered', 'exchangeResolved', 'exchangeWritable', 'releaseRead', 'releaseDecoded',
          'targetsValidated', 'display', 'homepage', 'pairA', 'pairB', 'keyA', 'keyB',
          'connectA', 'connectB', 'split', 'frames', 'keyboard', 'resize', 'resume', 'stop', 'remove')
FAILURES = {'private_exchange_path_invalid', 'exchange_stage_write_failed', 'private_release_read_failed',
            'private_release_decode_failed', 'private_fixture_binding_invalid', 'display_unavailable',
            'isolated_display_too_small', 'native_window_missing', 'native_window_origin_not_reached',
            'native_window_width_not_reached', 'native_window_height_not_reached',
            'unique_visible_control_missing', 'public_value_not_read_back', 'public_request_unavailable',
            'reviewed_host_response_unavailable', 'native_visible_peer_marker_missing',
            'native_tab_focus_unreachable', 'unexpected_native_error'}
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


def diagnostics(log: Path, bundle: Path, exit_code, stage):
    report = log_facts(private_log(log))
    report['xcresultPresent'] = bundle.is_dir()
    report['xcresultTestCounts'] = xcresult_summary(bundle)
    if type(exit_code) is int and -255 <= exit_code <= 255:
        report['xcodeExitCode'] = exit_code
    if stage in STAGES:
        report['atomicStage'] = stage
    return report
