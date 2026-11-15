"""Opt-in S06 widget/real-SSH acceptance on run-ci.py's disposable Linux host."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from paired_gui import (FixtureApproval, GuiFailure, Host, bounded_wire,
                        fixture_terminal_id, owned_process, wait_for)
from guarded_input import DRAFT


REQUIRED = ('normalHomepage', 'twoReviewedIdentities', 'samePaneDifferentTerminal',
            'bothVisible', 'independentFrames', 'bothAdvanced', 'singleInputFocus',
            'focusDoesNotRestoreInput', 'lateInputRejected', 'stoppedBoth')


def widget_failure(exchange, fallback):
    stages = {'s06_homepage', 's06_pair_0', 's06_pair_1', 's06_connect_0',
              's06_connect_1', 's06_select_0', 's06_select_1', 's06_frames_0', 's06_frames_1',
              's06_split_resume', 's06_input_eligibility', 's06_stop_both'}
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
    if not isinstance(raw, dict) or any(raw.get(key) is not True for key in REQUIRED):
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
    return {**{key: True for key in REQUIRED}, 'sides': clean}


def run_gui(args, root, env, config, command, final_pty_evidence):
    # run-ci.py owns this host, empty authorization file, server processes and
    # exact two sessions. This module never touches an operator's SSH state.
    if (args.paired_gui != 'flutter' or root.parent != Path('/tmp') or
            not root.name.startswith('hp-mobile-' + os.environ['GITHUB_RUN_ID'] + '-') or
            config['host'] != '127.0.0.1' or (root / 'authorized_keys').stat().st_size):
        raise GuiFailure('s06_unsafe_fixture')
    guarded = bool(args.input_fixture)
    other = root / 's06-peer-b'
    other.mkdir(mode=0o700)
    exchange = root / 's06-exchange'
    exchange.mkdir(mode=0o700)
    approvals = []
    result = {'adapter': 'flutter', 'testId': 'S06-two-real-ssh-herdr-targets', 'status': 'failed'}
    expected = (DRAFT if guarded else b'', b'b' if guarded else b'')
    try:
        shutil.copy2(root / 'capture_input.py', other / 'capture_input.py')
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
            try:
                code = proc.wait(timeout=160)
            except subprocess.TimeoutExpired:
                raise widget_failure(exchange, 's06_widget_completion_timeout') from None
            if code or not (exchange / 'result.json').is_file():
                raise widget_failure(exchange, 's06_widget_failed')
            result.update(checked_widget_result(json.loads(bounded_wire(exchange / 'result.json', 4096)), guarded))
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
                      scope='real Flutter widget, two real SSH/herdr sessions; explicit test signers and memory journals')
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
