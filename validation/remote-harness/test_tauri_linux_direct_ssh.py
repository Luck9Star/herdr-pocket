"""Loopback and deterministic negative controls for the Linux Tauri lane."""
import base64
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if importlib.util.find_spec('paramiko') is None or importlib.util.find_spec('PIL') is None:
    raise unittest.SkipTest('ordinary SSH and screenshot test dependencies are missing')
import paramiko
from PIL import Image
from screen_proof_token import token_lines
from tauri_linux_direct_ssh import (
    DesktopDriver,
    REVIEW_WITNESS,
    execute,
    DirectSshFixture,
    EncryptedKeyFixture,
    GuiFailure,
    ScreenshotGateError,
    capture_terminal,
    capture_outcome,
    decode_viewport_capture,
    exercise_rotation_review,
    exercise_wrong_passphrase,
    key_session_evidence,
    port_is_released,
    probe_evidence,
    rejected_key_evidence,
    rotation_session_evidence,
    session_evidence,
    wait_for,
)
from terminal_screenshot_gate import ECHO_MARKER


def real_peer_evidence():
    with DirectSshFixture(screen_proof=True, channel_deadline=time.monotonic() + 20) as fixture:
        with paramiko.Transport(('127.0.0.1', fixture.port)) as probe:
            probe.start_client(timeout=3)
            key = probe.get_remote_server_key()
            assert f'{key.get_name()} {key.get_base64()}' == fixture.public_key
        assert fixture.wait_for_connections_closed(1, timeout=4)
        initial = fixture.snapshot()
        with paramiko.Transport(('127.0.0.1', fixture.port)) as session:
            session.start_client(timeout=3)
            session.auth_password(fixture.username, fixture.password)
            with session.open_session(timeout=3) as channel:
                channel.settimeout(3)
                channel.get_pty()
                channel.invoke_shell()
                assert b'POCKET-ANDROID-READY' in channel.recv(1024)
                def shell_with_recorded_output():
                    facts = fixture.snapshot()
                    return facts if facts['connectionEvents'][1]['outputBytes'] > 0 else None

                no_input = wait_for(shell_with_recorded_output, 'test_fixture_shell_no_output', timeout=3)
                channel.sendall(b'hp-check\r')
                expected = (ECHO_MARKER, *token_lines(fixture.screen_token))
                rendered = b''
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not all(term.encode() in rendered for term in expected):
                    rendered += channel.recv(1024)
                assert all(term.encode() in rendered for term in expected)
                pre_close = fixture.snapshot()
        assert fixture.wait_for_connections_closed(2, timeout=4)
        post_close = fixture.snapshot()
    assert fixture.password == '' and port_is_released(fixture.port)
    return initial, no_input, pre_close, post_close


class PeerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial, cls.no_input, cls.pre_close, cls.post_close = real_peer_evidence()

    def test_real_isolated_probe_password_pty_single_line_and_closed_peer(self):
        probe_evidence(self.initial, 1)
        session_evidence(self.no_input, sent=False, closed=False)
        session_evidence(self.pre_close, sent=True, closed=False)
        session_evidence(self.post_close, sent=True, closed=True)

    def test_probe_can_end_after_seeing_host_key_before_key_exchange_completes(self):
        discovery = deepcopy(self.initial)
        discovery['connectionEvents'][0]['handshakeCompleted'] = False
        probe_evidence(discovery, 1)

    def test_probe_with_authentication_or_injected_connection_is_refused(self):
        unexpected = deepcopy(self.initial)
        unexpected['connectionEvents'][0]['authAttempts'] = 1
        with self.assertRaisesRegex(GuiFailure, 'probe_not_empty'):
            probe_evidence(unexpected, 1)
        with self.assertRaisesRegex(GuiFailure, 'connection_count_invalid'):
            probe_evidence(self.pre_close, 1)

    def test_session_replay_missing_marker_and_premature_close_are_refused(self):
        for field, value, code in (('inputBytes', 18, 'unexpected_input'),
                                   ('markerReceived', False, 'unexpected_input'),
                                   ('authAttempts', 2, 'password_shell_unproven'),
                                   ('ptyRequests', 2, 'password_shell_unproven'),
                                   ('shellRequests', 2, 'password_shell_unproven'),
                                   ('closed', True, 'close_order_invalid')):
            with self.subTest(field=field):
                unexpected = deepcopy(self.pre_close)
                unexpected['connectionEvents'][1][field] = value
                with self.assertRaisesRegex(GuiFailure, code):
                    session_evidence(unexpected, sent=True, closed=False)
        mislabeled = deepcopy(self.post_close)
        mislabeled['connectionEvents'][1]['closeReason'] = 'fixture_stopped'
        with self.assertRaisesRegex(GuiFailure, 'close_order_invalid'):
            session_evidence(mislabeled, sent=True, closed=True)


def real_encrypted_peer_evidence(*, rotating=False):
    with EncryptedKeyFixture(screen_proof=True, rotate_after_probe=rotating,
                             channel_deadline=time.monotonic() + 20) as fixture:
        prefix = []
        public_keys = [fixture.public_key, fixture.rotated_public_key, fixture.rotated_public_key] if rotating else [
            fixture.public_key, fixture.public_key]
        for connection, expected_key in enumerate(public_keys, 1):
            with paramiko.Transport(('127.0.0.1', fixture.port)) as rejected:
                rejected.start_client(timeout=3)
                host_key = rejected.get_remote_server_key()
                assert f'{host_key.get_name()} {host_key.get_base64()}' == expected_key
                if connection == 2 and not rotating:
                    # Wrong passphrase is local to the client after key exchange.
                    try:
                        paramiko.Ed25519Key(file_obj=io.StringIO(fixture.private_key), password=fixture.wrong_passphrase)
                    except paramiko.SSHException:
                        pass
                    else:
                        raise AssertionError('the fixture accepted the wrong passphrase')
            assert fixture.wait_for_connections_closed(connection, timeout=3)
            prefix.append(fixture.snapshot())
        key = paramiko.Ed25519Key(file_obj=io.StringIO(fixture.private_key), password=fixture.passphrase)
        with paramiko.Transport(('127.0.0.1', fixture.port)) as session:
            session.start_client(timeout=3)
            session.auth_publickey(fixture.username, key)
            with session.open_session(timeout=3) as channel:
                channel.settimeout(3)
                channel.get_pty()
                channel.invoke_shell()
                assert b'POCKET-ANDROID-READY' in channel.recv(1024)

                def with_output():
                    facts = fixture.snapshot()
                    return facts if facts['connectionEvents'][-1]['outputBytes'] > 0 else None

                no_input = wait_for(with_output, 'test_key_shell_no_output', timeout=3)
                channel.sendall(b'hp-check\r')
                expected = (ECHO_MARKER, *token_lines(fixture.screen_token))
                rendered = b''
                while not all(text.encode() in rendered for text in expected):
                    block = channel.recv(1024)
                    assert block
                    rendered += block
                pre_close = fixture.snapshot()
                channel.shutdown_write()
                assert fixture.wait_for_connections_closed(len(prefix) + 1, timeout=3)
        post_close = fixture.snapshot()
    assert not any((fixture.private_key, fixture.passphrase, fixture.wrong_passphrase, fixture.password))
    assert port_is_released(fixture.port)
    return prefix, no_input, pre_close, post_close


class EncryptedPeerEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prefix, cls.no_input, cls.pre_close, cls.post_close = real_encrypted_peer_evidence()
        cls.rejected = prefix[1]

    def test_real_encrypted_peer_rejection_and_single_successful_public_key_session(self):
        rejected_key_evidence(self.rejected, 2)
        key_session_evidence(self.no_input, sent=False, closed=False)
        key_session_evidence(self.pre_close, sent=True, closed=False)
        key_session_evidence(self.post_close, sent=True, closed=True)

    def test_rejects_wrong_passphrase_paths_with_authentication_or_terminal_activity(self):
        for change in ({'handshakeCompleted': False}, {'closed': False}, {'authAttempts': 1},
                       {'ptyRequests': 1}, {'shellRequests': 1}, {'inputBytes': 1}, {'outputBytes': 1}):
            with self.subTest(change=change), self.assertRaisesRegex(GuiFailure, 'wrong_passphrase_peer_not_empty'):
                drift = deepcopy(self.rejected)
                drift['connectionEvents'][1].update(change)
                rejected_key_evidence(drift, 2)

    def test_rejects_equal_length_nonmatching_command_or_early_disconnect(self):
        drift = deepcopy(self.pre_close)
        drift['connectionEvents'][-1]['singleMarkerLineExact'] = False
        with self.assertRaisesRegex(GuiFailure, 'unexpected_input'):
            key_session_evidence(drift, sent=True, closed=False)
        with self.assertRaisesRegex(GuiFailure, 'close_order_invalid'):
            key_session_evidence(self.post_close, sent=True, closed=False)

    def test_wrong_passphrase_click_is_single_and_evidence_has_no_credentials(self):
        driver = Mock()
        driver.observe.return_value = True
        fixture = Mock(private_key='fixture-pem', wrong_passphrase='fixture-wrong',
                       passphrase='fixture-correct', password='fixture-password')
        fixture.wait_for_connections_closed.return_value = True
        fixture.snapshot.return_value = self.rejected
        report = {}
        exercise_wrong_passphrase(driver, fixture, 'fixture@127.0.0.1:2222', report)
        driver.click.assert_called_once_with('#ssh-connect')
        self.assertEqual([call.args for call in driver.fill.call_args_list],
                         [('#ssh-key', fixture.private_key), ('#ssh-passphrase', fixture.wrong_passphrase)])
        self.assertTrue(report['wrongPassphrase']['handshakeCompleted'])
        self.assertEqual(report['wrongPassphrase']['authenticationAttempts'], 0)
        self.assertNotIn('fixture-', json.dumps(report))


class RotationEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix, cls.no_input, cls.pre_close, cls.post_close = real_encrypted_peer_evidence(rotating=True)

    def test_four_real_transports_bind_rotated_key_and_original_signed_session(self):
        self.assertEqual([e['hostKey'] for e in self.post_close['connectionEvents']], ['A', 'B', 'B', 'B'])
        rotation_session_evidence(self.no_input, sent=False, closed=False)
        rotation_session_evidence(self.pre_close, sent=True, closed=False)
        rotation_session_evidence(self.post_close, sent=True, closed=True)

    def test_refuses_new_input_or_wrong_key_before_explicit_approval(self):
        for change in ({'authAttempts': 1}, {'inputBytes': 1}, {'hostKey': 'A'}, {'closed': False}):
            with self.subTest(change=change), self.assertRaisesRegex(GuiFailure, 'rotation_preapproval_peer_not_empty'):
                altered = deepcopy(self.no_input)
                altered['connectionEvents'][1].update(change)
                rotation_session_evidence(altered, sent=False, closed=False)
        altered = deepcopy(self.no_input)
        altered['connectionEvents'][-1]['hostKey'] = 'A'
        with self.assertRaisesRegex(GuiFailure, 'key_shell_unproven'):
            rotation_session_evidence(altered, sent=False, closed=False)

    def run_review(self, checkpoints):
        driver = Mock()
        driver.observe.return_value = True
        fixture = Mock(fingerprint='SHA256:old-fixture', rotated_fingerprint='SHA256:new-fixture',
                       rotated_public_key='ssh-rsa fixture', private_key='fixture-key', passphrase='fixture-pass')
        fixture.wait_for_connections_closed.return_value = True
        fixture.rotation_evidence.side_effect = checkpoints
        fixture.snapshot.return_value = self.prefix[0]
        target = (('#ssh-host', '127.0.0.1'), ('#ssh-port', '2222'), ('#ssh-user', 'fixture'))
        return driver, fixture, target

    def test_capture_then_cancel_retain_and_review_fresh_b_before_confirmation(self):
        old, new = {'stage': 2}, {'stage': 3}
        driver, fixture, target = self.run_review([old, old, old, new])
        report = {}
        endpoint = 'fixture@127.0.0.1:2222'
        with patch('tauri_linux_direct_ssh.capture_outcome', return_value=(b'png', {'bounds': [0, 0, 1, 1]})):
            exercise_rotation_review(driver, fixture, endpoint, target, report)
        self.assertEqual([c.args[0] for c in driver.click.call_args_list],
                         ['#ssh-connect', '#ssh-key-cancel', '#ssh-probe', '#ssh-trust-confirm', '#ssh-auth-key'])
        self.assertEqual([c.args for c in fixture.rotation_evidence.call_args_list], [(2,), (2,), (2,), (3,)])
        self.assertTrue(report['rotation']['cancelKeptOldTrust'])
        self.assertEqual(report['rotation']['freshProbe'], new)
        self.assertNotIn(fixture.private_key, json.dumps(report))
        driver.send_test_line.assert_not_called()

    def test_cancellation_drift_stops_before_another_probe_or_confirmation(self):
        old = {'stage': 2}
        driver, fixture, target = self.run_review([old, old, {'stage': 2, 'changed': True}])
        with patch('tauri_linux_direct_ssh.capture_outcome', return_value=(b'png', {})), \
             self.assertRaisesRegex(GuiFailure, 'rotation_cancel_dialed'):
            exercise_rotation_review(driver, fixture, 'fixture@127.0.0.1:2222', target, {})
        self.assertEqual([c.args[0] for c in driver.click.call_args_list], ['#ssh-connect', '#ssh-key-cancel'])
        driver.send_test_line.assert_not_called()


class WebDriverTests(unittest.TestCase):
    def test_encrypted_pem_line_breaks_use_native_enter_and_require_exact_readback(self):
        driver = DesktopDriver()
        driver.click = Mock()
        driver.element = Mock(return_value='/owned/key')
        driver.call = Mock()
        value = 'fixture-header\nfixture-body\n'
        driver.read = Mock(return_value=value)
        driver.fill('#ssh-key', value)
        driver.click.assert_called_once_with('#ssh-key')
        driver.read.assert_called_once_with('#ssh-key', 'value')
        strokes = 'fixture-header\ue007fixture-body\ue007'
        self.assertEqual([call.args for call in driver.call.call_args_list], [
            ('POST', '/owned/key/clear', {}),
            ('POST', '/owned/key/value', {'text': strokes, 'value': list(strokes)}),
        ])
        driver.read.return_value = value.replace('\n', '')
        with self.assertRaisesRegex(GuiFailure, 'form_input_mismatch_ssh-key'):
            driver.fill('#ssh-key', value)

    def test_native_webkit_session_uses_production_binary_and_public_capabilities(self):
        driver = DesktopDriver()
        binary = Path('/isolated/herdr-pocket-tauri-probe')
        driver.call = Mock(side_effect=[{'ready': False}, {'ready': True}, {'sessionId': 'fixture'}])
        driver.start(binary)
        self.assertEqual(driver.session, '/session/fixture')
        self.assertEqual([call.args for call in driver.call.call_args_list], [
            ('GET', '/status'), ('GET', '/status'),
            ('POST', '/session', {'capabilities': {'alwaysMatch': {
                'webkitgtk:browserOptions': {'binary': str(binary.resolve()), 'args': []},
            }}}),
        ])

    def test_native_click_and_physical_keys_are_each_sent_once(self):
        driver = DesktopDriver()
        driver.session = '/session/fixture'
        driver.call = Mock(side_effect=[True, [{'element-6066-11e4-a52e-4f735466cecf': 'screen'}], None, None])
        driver.click('#ssh-terminal .xterm-screen')
        driver.send_test_line()
        calls = [call.args for call in driver.call.call_args_list]
        self.assertEqual(calls[1][2], {'using': 'css selector', 'value': '#ssh-terminal .xterm-screen'})
        self.assertEqual(calls[2], ('POST', '/session/fixture/element/screen/click', {}))
        self.assertEqual(calls[3][:2], ('POST', '/session/fixture/actions'))
        keys = calls[3][2]['actions'][0]['actions']
        self.assertEqual(''.join(key['value'] for key in keys[::2]), 'hp-check\ue007')
        self.assertTrue(all(down['type'] == 'keyDown' and up == dict(down, type='keyUp')
                            for down, up in zip(keys[::2], keys[1::2])))
        self.assertEqual(len(calls), 4)


class ReviewFlowTests(unittest.TestCase):
    def test_waits_for_isolated_empty_board_instead_of_locking_onto_startup_header(self):
        driver = Mock()
        fixture = Mock(username='fixture', port=49821, public_key='ssh-rsa AAAA')
        snapshots = []

        def observe(script, *_):
            if '#host-empty-add' in script:
                snapshots.append('empty-board')
                return len(snapshots) > 1
            return True

        def click(selector):
            if selector == '#host-open-remote':
                raise GuiFailure('control_unavailable_host-open-remote')
            if selector == '#add-ssh':
                raise GuiFailure('test_stop_at_open_ssh')

        driver.observe.side_effect = observe
        driver.click.side_effect = click
        with self.assertRaisesRegex(GuiFailure, '^test_stop_at_open_ssh$'):
            execute(driver, fixture, {})
        self.assertEqual(snapshots, ['empty-board', 'empty-board'])
        self.assertEqual([call.args[0] for call in driver.click.call_args_list], ['#host-empty-add', '#add-ssh'])

    def test_physical_confirmation_occurs_after_probe_evidence(self):
        events = []
        driver = Mock()
        driver.observe.return_value = True
        driver.click.side_effect = lambda selector: events.append(('click', selector))
        driver.send_test_line.side_effect = lambda: events.append(('type', 'terminal'))
        fixture = Mock(username='fixture', port=49821, fingerprint='SHA256:example',
                       public_key='ssh-rsa AAAA', password='temporary')
        fixture.wait_for.return_value = True
        fixture.wait_for_connections_closed.return_value = True
        fixture.snapshot.return_value = {'connectionEvents': [{}, {'outputBytes': 1}]}
        with patch('tauri_linux_direct_ssh.probe_evidence', side_effect=lambda *_: events.append(('peer', 'probe'))), \
             patch('tauri_linux_direct_ssh.session_evidence'), \
             patch('tauri_linux_direct_ssh.capture_terminal', return_value=(b'terminal', {})), \
             patch('tauri_linux_direct_ssh.capture_outcome', return_value=(b'outcome', {})):
            execute(driver, fixture, {})
        self.assertNotIn(('click', '#ssh-review'), events)
        self.assertEqual(events.count(('click', '#ssh-trust-confirm')), 1)
        self.assertLess(events.index(('peer', 'probe')), events.index(('click', '#ssh-trust-confirm')))
        self.assertLess(events.index(('click', '#ssh-trust-confirm')), events.index(('click', '#ssh-connect')))
        self.assertNotIn(('click', '#ssh-focus'), events)
        self.assertEqual(events.count(('click', '#ssh-terminal .xterm-screen')), 1)
        self.assertLess(events.index(('click', '#ssh-terminal .xterm-screen')), events.index(('type', 'terminal')))
        self.assertIn(('click', '#ssh-disconnect'), events)
        self.assertIn(('click', '#ssh-return-home'), events)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the DOM witness negative controls')
    def test_review_witness_rejects_wrong_hidden_clipped_duplicate_or_covered_evidence(self):
        script = r'''const names=['#ssh-step-title','#ssh-reviewed-target','#ssh-reviewed-endpoint',
          '#ssh-reviewed-key','#ssh-reviewed-algorithm','#ssh-reviewed-fingerprint','#ssh-trust-confirm',
          '#ssh-review','#ssh-password','#ssh-connect'];
        const nodes=Object.fromEntries(names.map(name=>[name,{name,innerText:'',disabled:false,checked:false,shown:true,
          getBoundingClientRect(){return {left:10,top:10,right:110,bottom:30,width:100,height:20};},
          contains(e){return e===this || (this.name==='#ssh-reviewed-target'&&e===nodes['#ssh-reviewed-endpoint']) ||
            (this.name==='#ssh-reviewed-key'&&[nodes['#ssh-reviewed-algorithm'],nodes['#ssh-reviewed-fingerprint']].includes(e));}}]));
        nodes['#ssh-step-title'].innerText='核对主机密钥';nodes['#ssh-reviewed-endpoint'].innerText='user@host:49821';
        nodes['#ssh-reviewed-algorithm'].innerText='ssh-rsa';nodes['#ssh-reviewed-fingerprint'].innerText='SHA256:expected';
        nodes['#ssh-trust-confirm'].innerText='指纹一致，确认继续';nodes['#ssh-review'].shown=false;
        nodes['#ssh-password'].disabled=nodes['#ssh-connect'].disabled=true;
        let duplicate=false,covered=false,clipped=false;
        globalThis.innerWidth=500;globalThis.innerHeight=500;
        globalThis.node=s=>nodes[s];globalThis.visible=e=>!!e&&e.shown;
        globalThis.document={querySelectorAll:s=>duplicate&&s==='#ssh-trust-confirm'?[nodes[s],nodes[s]]:[nodes[s]],
          createRange:()=>({selectNodeContents(){},getClientRects(){return [{left:10,top:10,right:clipped?510:110,bottom:30,width:100,height:20}];}}),
          elementFromPoint:()=>covered?{}:nodes['#ssh-reviewed-fingerprint']};
        const check=new Function('return (function(){'+WITNESS+'}).apply(null,arguments)');
        const run=()=>check('user@host:49821','ssh-rsa','SHA256:expected');
        const out=[run()];
        nodes['#ssh-reviewed-endpoint'].innerText='wrong';out.push(run());nodes['#ssh-reviewed-endpoint'].innerText='user@host:49821';
        nodes['#ssh-reviewed-algorithm'].innerText='wrong';out.push(run());nodes['#ssh-reviewed-algorithm'].innerText='ssh-rsa';
        nodes['#ssh-reviewed-fingerprint'].innerText='SHA256:partial';out.push(run());nodes['#ssh-reviewed-fingerprint'].innerText='SHA256:expected';
        nodes['#ssh-trust-confirm'].disabled=true;out.push(run());nodes['#ssh-trust-confirm'].disabled=false;
        nodes['#ssh-reviewed-fingerprint'].shown=false;out.push(run());nodes['#ssh-reviewed-fingerprint'].shown=true;
        duplicate=true;out.push(run());duplicate=false;clipped=true;out.push(run());clipped=false;covered=true;out.push(run());
        console.log(JSON.stringify(out));'''
        script = 'const WITNESS=' + json.dumps(REVIEW_WITNESS) + ';\n' + script
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [True] + [False] * 8)


class ScreenshotBindingTests(unittest.TestCase):
    def setUp(self):
        buffer = io.BytesIO()
        Image.new('RGB', (400, 160)).save(buffer, 'PNG')
        self.png = buffer.getvalue()
        self.encoded = base64.b64encode(self.png).decode('ascii')
        self.driver = Mock(session='/session/fixture')
        self.driver.call.return_value = self.encoded
        self.geometry = {'viewport': [400, 160], 'bounds': [0, 0, 400, 150], 'endpointBounds': [0, 0, 90, 22]}

    def test_malformed_or_unregistered_image_fails_before_ocr(self):
        for encoded, size in (('%%%%', [400, 160]), (self.encoded, [800, 320]), ('', [400, 160])):
            with self.subTest(size=size), self.assertRaisesRegex(GuiFailure, 'viewport_png_invalid'):
                decode_viewport_capture(encoded, size)

    def test_outcome_capture_binds_original_viewport_and_rejects_geometry_change(self):
        geometry = {'viewport': [400, 160], 'bounds': [20, 20, 200, 60]}
        self.driver.observe.return_value = geometry
        png, evidence = capture_outcome(self.driver, '#ssh-closed-feedback')
        self.assertEqual(png, self.png)
        self.assertEqual(evidence['bounds'], geometry['bounds'])
        self.assertEqual(len(evidence['imageSha256']), 64)
        self.driver.observe.side_effect = [geometry, dict(geometry, bounds=[21, 20, 200, 60])]
        with self.assertRaisesRegex(GuiFailure, 'outcome_geometry_changed'):
            capture_outcome(self.driver, '#ssh-closed-feedback')

    @patch('tauri_linux_direct_ssh.verify_terminal_screenshot')
    @patch('tauri_linux_direct_ssh.terminal_geometry')
    def test_target_or_geometry_change_during_capture_fails_before_ocr(self, geometry, verify):
        geometry.side_effect = [self.geometry, dict(self.geometry, bounds=[0, 0, 400, 149])]
        with self.assertRaisesRegex(GuiFailure, 'geometry_changed'):
            capture_terminal(self.driver, 'fixture@127.0.0.1:2222', 'public-screen-token')
        verify.assert_not_called()

    @patch('tauri_linux_direct_ssh.time.sleep')
    @patch('tauri_linux_direct_ssh.verify_terminal_screenshot')
    @patch('tauri_linux_direct_ssh.terminal_geometry')
    def test_missing_visual_proof_only_rechecks_original_pixels(self, geometry, verify, _):
        geometry.return_value = self.geometry
        verify.side_effect = [ScreenshotGateError('terminal_screenshot_echo_not_visible'), {'verified': True}]
        png, proof = capture_terminal(self.driver, 'fixture@127.0.0.1:2222', 'public-screen-token')
        self.assertEqual(png, self.png)
        self.assertEqual(proof['captureAttempt'], 2)
        self.assertEqual(verify.call_args.kwargs, {'expected_token': 'public-screen-token', 'bounds': [0, 0, 400, 150]})
        self.assertEqual([call.args for call in self.driver.call.call_args_list],
                         [('GET', '/session/fixture/screenshot'), ('GET', '/session/fixture/screenshot')])


if __name__ == '__main__':
    unittest.main()
