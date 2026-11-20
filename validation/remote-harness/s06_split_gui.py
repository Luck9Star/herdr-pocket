"""Opt-in desktop S06 acceptance on run-ci.py's disposable two-session host."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time

from paired_gui import (FixtureApproval, GuiFailure, Host, bounded_wire,
                        fixture_terminal_id, owned_process, wait_for)
from guarded_input import DRAFT


REQUIRED = ('normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
            'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus',
            'focusDoesNotRestoreInput', 'lateInputRejected', 'stoppedBoth')
STOCK_CLOSE_CHECK = 'focusedTabClosedPeerAdvanced'
STOCK_FINAL_CLOSE_CHECK = 'stockPeersClosedBeforeDriverExit'
S06_TEST_ID = 'S06-two-real-ssh-herdr-targets'
IMPORT_REPLACE_TEST_ID = 'M1-05-tauri-real-ssh-config-replacement'


def widget_failure(exchange, fallback):
    stages = {'s06_homepage', 's06_pair_0', 's06_pair_1', 's06_connect_0',
              's06_connect_1', 's06_select_0', 's06_select_1', 's06_frames_0', 's06_frames_1',
              's06_split_resume', 's06_input_eligibility', 's06_close_focused_tab',
              's06_stop_both', 's06_confirm_final_close'}
    path = exchange / 'stage'
    if path.is_file():
        stage = bounded_wire(path, 40).decode('ascii', errors='ignore')
        if stage in stages:
            return GuiFailure(f'{fallback}_{stage}')
    return GuiFailure(fallback)


def failure_diagnostics(exchange):
    try:
        value = json.loads(bounded_wire(exchange / 'failure.json', 2048))
        kind, locations = value['kind'], value['locations']
        if (not isinstance(kind, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,60}', kind) or
                not isinstance(locations, list) or len(locations) > 4 or
                any(not isinstance(item, str) or not re.fullmatch(r's06_real_ssh_test\.dart:\d{1,4}:\d{1,4}', item)
                    for item in locations)):
            return {'valid': False}
        clean = {'kind': kind, 'locations': locations}
        for key in ('splitActive',):
            if type(value.get(key)) is bool:
                clean[key] = value[key]
        for key in ('visibleTabs', 'resumeOnstage', 'resumeAnywhere'):
            if type(value.get(key)) is int and 0 <= value[key] <= 8:
                clean[key] = value[key]
        peers = value.get('peers')
        phases = {'idle', 'paused', 'resuming', 'snapshot', 'opening', 'awaiting_full', 'streaming', 'retiring', 'failed'}
        errors = {'none', 'channel_cleanup_timeout', 'observe_ended', 'cancelled', 'watch_retry_exhausted',
                  'connection_failed', 'session_mismatch', 'resume_target_changed', 'timeout', 'other_public_failure'}
        if isinstance(peers, list) and len(peers) <= 2:
            clean['peers'] = []
            for peer in peers:
                if (not isinstance(peer, dict) or peer.get('phase') not in phases or peer.get('error') not in errors or
                        type(peer.get('observationCloseFailed')) is not bool or
                        any(type(peer.get(key)) is not int or not 0 <= peer[key] <= 1_000_000
                            for key in ('connectionCount', 'frameCount', 'deltaFrames'))):
                    return {'valid': False}
                clean['peers'].append({key: peer[key] for key in ('connectionCount', 'frameCount',
                    'deltaFrames', 'phase', 'error', 'observationCloseFailed')})
        return clean
    except (GuiFailure, OSError, ValueError, KeyError, TypeError):
        return {'valid': False}


def checked_widget_result(raw, guarded):
    required = REQUIRED if guarded else (*REQUIRED, STOCK_CLOSE_CHECK, STOCK_FINAL_CLOSE_CHECK)
    if not isinstance(raw, dict) or any(raw.get(key) is not True for key in required):
        raise GuiFailure('s06_widget_checks_incomplete')
    sides = raw.get('sides')
    if not isinstance(sides, list) or len(sides) != 2:
        raise GuiFailure('s06_widget_sides_invalid')
    clean = []
    for side in sides:
        if (not isinstance(side, dict) or type(side.get('connectionCount')) is not int or
                side['connectionCount'] != 1):
            raise GuiFailure('s06_connection_count_invalid')
        full, delta = side.get('frameCount'), side.get('deltaFrames')
        if type(full) is not int or type(delta) is not int or not 1 <= delta < full <= 1_000_000:
            raise GuiFailure('s06_frame_counts_invalid')
        if side.get('inputAccepted') is not guarded:
            raise GuiFailure('s06_input_capability_mismatch')
        clean.append(dict(connectionCount=1, frameCount=full, deltaFrames=delta,
                          inputAccepted=guarded))
    return {**{key: True for key in required}, 'sides': clean}


def stock_peer_states(approvals):
    from s06_tauri_gui import peer_connection_evidence

    states = []
    for approval in approvals:
        peer = peer_connection_evidence(approval)
        if peer['authenticationCount'] == 0:
            states.append('authentication_missing')
        elif peer['authenticationCount'] != 1:
            states.append('multiple_authentications')
        else:
            states.append('closed' if peer['closed'] else 'close_unconfirmed')
    return states


def acknowledge_stock_close(exchange, approvals, proc, deadline, result, *, final):
    marker = 'final-close' if final else 'focused-close'
    phase = 'final' if final else 'focused'
    expected = ['closed', 'closed' if final else 'close_unconfirmed']
    progress = result.setdefault('stockStopEvidence', {})

    def while_running(predicate):
        if proc.poll() is not None:
            raise widget_failure(exchange, f's06_widget_exited_before_{phase}_close')
        return predicate()

    request = exchange / f'{marker}-request'
    wait_for(lambda: while_running(request.is_file), f's06_{phase}_close_request_timeout',
             timeout=deadline - time.monotonic())
    if final:
        # The driver creates this marker after the surviving frame and the UI stop.
        result[STOCK_CLOSE_CHECK] = True
        progress['survivorStopRequested'] = True

    def need_peer_states():
        states = stock_peer_states(approvals)
        progress[f'{phase}PeerStates'] = states
        return states == expected

    unavailable = 's06_stock_final_peer_close_unconfirmed' if final else 's06_focused_peer_close_unconfirmed'
    wait_for(lambda: while_running(need_peer_states), unavailable,
             timeout=min(12, deadline - time.monotonic()))
    (exchange / f'{marker}-ack').touch(exist_ok=False)
    if final:
        result[STOCK_FINAL_CLOSE_CHECK] = True


def run_gui(args, root, env, config, command, final_pty_evidence, *, import_replace=False):
    # run-ci.py owns this host, empty authorization file, server processes and
    # exact two sessions. This module never touches an operator's SSH state.
    if (args.paired_gui not in ('flutter', 'tauri') or root.parent != Path('/tmp') or
            not root.name.startswith('hp-mobile-' + os.environ['GITHUB_RUN_ID'] + '-') or
            config['host'] != '127.0.0.1' or (root / 'authorized_keys').stat().st_size):
        raise GuiFailure('s06_unsafe_fixture')
    guarded = bool(args.input_fixture)
    if import_replace and (args.paired_gui != 'tauri' or guarded):
        raise GuiFailure('s06_import_requires_stock_tauri')
    other = root / 's06-peer-b'
    other.mkdir(mode=0o700)
    exchange = root / 's06-exchange'
    exchange.mkdir(mode=0o700)
    approvals = []
    result = {'adapter': args.paired_gui, 'testId': IMPORT_REPLACE_TEST_ID if import_replace else S06_TEST_ID,
              'status': 'failed'}
    expected = (DRAFT if guarded else b'', b'b' if guarded else b'')
    try:
        shutil.copy2(root / 'capture_input.py', other / 'capture_input.py')
        capture = other / 'capture_input.py'
        capture.write_text(capture.read_text().replace('Synthetic observe tick', 'S06 B tick'))
        pixels = json.loads((root / 'terminal-fixture.json').read_text())
        pixels['frames'][0]['data'] = pixels['frames'][0]['data'].replace(
            'herdr-pocket / same fixture v1', 'herdr-pocket / S06 peer B')
        (other / 'terminal-fixture.json').write_text(json.dumps(pixels))
        second = {**config, 'session': 'pocket-other',
                  'socketPath': str(Path(config['socketPath']).parent.parent / 'pocket-other' / 'herdr.sock')}
        command([config['herdrPath'], '--session', second['session'], 'pane', 'run', config['paneId'],
                 shlex.join(['python3', str(other / 'capture_input.py')])])
        wait_for(lambda: (other / 'capture-ready').is_file(), 's06_second_capture_not_ready', timeout=12)
        terminals = [fixture_terminal_id(item) for item in (config, second)]
        if terminals[0] == terminals[1]:
            raise GuiFailure('s06_distinct_terminal_binding_missing')
        command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C',
                 'ephemeral-s06-device-b', '-f', root / 'client-b'])
        (exchange / 'config.json').write_text(json.dumps([config, second]))
        widget_env = dict(env, HERDR_S06_CONFIG=str(exchange / 'config.json'),
                          HERDR_S06_DIR=str(exchange), HERDR_S06_KEY_A=str(root / 'client'),
                          HERDR_S06_KEY_B=str(root / 'client-b'), HERDR_S06_GUARDED='1' if guarded else '0')
        home = root / 's06-helper'
        home.mkdir(mode=0o700)
        for index, target in enumerate((config, second)):
            scratch = Path(home) / str(index)
            scratch.mkdir(mode=0o700)
            approvals.append(FixtureApproval(root, target,
                Host(scratch, target['username'], target['expectedHostKey'])))
        if args.paired_gui == 'tauri':
            from s06_tauri_gui import exercise
            result.update(exercise(args, root, env, (config, second), approvals, expected,
                                   import_replace=import_replace))
        else:
            argv = ['flutter', 'test', '--no-pub', '--reporter', 'expanded', 'test/s06_real_ssh_test.dart']
            with owned_process(argv, cwd=args.flutter_app, env=widget_env, log=root / 's06-widget.log') as proc:
                for index, approval in enumerate(approvals):
                    request = exchange / f'request-{index}.json'
                    def ready():
                        if proc.poll() is not None:
                            raise widget_failure(exchange, 's06_widget_exited_before_pairing')
                        return request.is_file()
                    wait_for(ready, 's06_pairing_request_timeout', timeout=100)
                    response = approval.approve(bounded_wire(request))
                    pending = exchange / f'response-{index}.new'
                    pending.write_bytes(response)
                    pending.rename(exchange / f'response-{index}.json')
                deadline = time.monotonic() + 160
                if not guarded:
                    acknowledge_stock_close(exchange, approvals, proc, deadline, result, final=False)
                    acknowledge_stock_close(exchange, approvals, proc, deadline, result, final=True)
                try:
                    code = proc.wait(timeout=160 if guarded else max(0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    raise widget_failure(exchange, 's06_widget_completion_timeout') from None
                if code or not (exchange / 'result.json').is_file():
                    raise widget_failure(exchange, 's06_widget_failed')
                result.update(checked_widget_result(json.loads(bounded_wire(exchange / 'result.json', 4096)), guarded))
                if not guarded:
                    states = stock_peer_states(approvals)
                    result['stockStopEvidence']['postDriverPeerStates'] = states
                    if states != ['closed', 'closed']:
                        raise GuiFailure('s06_stock_peer_state_changed_after_ack')
        # Independent server-side attestations, never accepted from widgets.
        if approvals[0].fingerprint == approvals[1].fingerprint:
            raise GuiFailure('s06_distinct_device_keys_missing')
        for index, approval in enumerate(approvals):
            if not approval.fingerprint_authenticated():
                raise GuiFailure('s06_reviewed_device_not_authenticated')
            if fixture_terminal_id((config, second)[index]) != terminals[index]:
                raise GuiFailure('s06_terminal_binding_changed')
        for directory, data in zip((root, other), expected):
            if bounded_wire(directory / 'received.bin', 4096) != data:
                raise GuiFailure('s06_remote_input_target_mismatch')
        result.update(status='passed', matchedDeviceKeyInSshd=True,
                      receivedInputBytes=len(expected[0]), peerInputBytes=[len(data) for data in expected],
                      exactRemoteBytes=True, distinctAuthenticatedDeviceKeys=True,
                      targetBindingsPreserved=True, physicalImeVerified=False,
                      scope=('native Linux GTK WebView config replacement with two real SSH/herdr sessions; process-memory test identities'
                             if import_replace else
                             'native Linux GTK WebView and two real SSH/herdr sessions; process-memory test identities'
                             if args.paired_gui == 'tauri' else
                             'real Flutter widget, two real SSH/herdr sessions; explicit test signers and memory journals'))
    except GuiFailure as error:
        result['errorCode'] = str(error)
        result['widgetFailure'] = failure_diagnostics(exchange)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        result['errorCode'] = 's06_fixture_or_exchange_failed'
    finally:
        revoked = True
        for approval in approvals:
            try:
                approval.revoke()
            except (GuiFailure, OSError, ValueError):
                revoked = False
        result['revokedFixtureKeys'] = revoked and len(approvals) == 2 and all(a.applied for a in approvals)
        if result['status'] == 'passed' and not result['revokedFixtureKeys']:
            result.update(status='failed', errorCode='s06_key_revocation_unconfirmed')
        for name in ('client-b', 'client-b.pub'):
            (root / name).unlink(missing_ok=True)
        (other / 'stop-capture').write_text('stop')
        if (other / 'capture-ready').is_file():
            result['secondSharedPty'] = final_pty_evidence(other)
            if result['status'] == 'passed' and (not result['secondSharedPty']['noObservedResize'] or
                    bounded_wire(other / 'received.bin', 4096) != expected[1]):
                result.update(status='failed', errorCode='s06_second_final_capture_mismatch')
    return result
