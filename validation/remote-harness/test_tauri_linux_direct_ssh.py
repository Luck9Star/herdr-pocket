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
    GuiFailure,
    ScreenshotGateError,
    capture_terminal,
    capture_outcome,
    decode_viewport_capture,
    port_is_released,
    probe_evidence,
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


class WebDriverTests(unittest.TestCase):
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
