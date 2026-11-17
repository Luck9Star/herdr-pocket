"""Independent raster controls; these images are not application evidence."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
from subprocess import CompletedProcess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot


TOKEN = 'ACDEFHJKMN34'
MARKER = 'POCKET-ANDROID-SSH-OK'


class ScreenshotInputTests(unittest.TestCase):
    def test_invalid_token_cannot_disable_freshness_check(self):
        for token in ('', 'POCKET', TOKEN + 'X', TOKEN.lower(), 'A' * 11 + '0'):
            with self.subTest(token=token), self.assertRaisesRegex(ScreenshotGateError, 'token_invalid'):
                verify_terminal_screenshot(b'', expected_token=token, bounds=(0, 0, 20, 20))

    def test_noninteger_rectangle_is_rejected(self):
        for bounds in ((0, 0, 20), (0, 0, 20, True), (0, 0, 20.0, 20), None):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ScreenshotGateError, 'bounds_invalid'):
                verify_terminal_screenshot(b'', expected_token=TOKEN, bounds=bounds)


class ScreenshotRasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = importlib.util.find_spec('PIL') is None or shutil.which('tesseract') is None
        if missing:
            message = 'Pillow and real Tesseract are required for independent raster controls'
            if os.environ.get('HERDR_REQUIRE_SCREENSHOT_OCR') == '1':
                raise RuntimeError(message)
            raise unittest.SkipTest(message)

    def raster(self, lines, *, size=24, green=False, chrome=(), monospace=False):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (820, 540), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=size)
        if monospace:
            for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                         '/System/Library/Fonts/Supplemental/Andale Mono.ttf'):
                if Path(path).exists():
                    font = ImageFont.truetype(path, size)
                    break
        draw.rectangle((10, 150, 809, 509), fill='#0b1018')
        for index, line in enumerate(chrome):
            draw.text((20, 12 + index * (size + 10)), line, fill='black', font=font)
        for index, line in enumerate(lines):
            draw.text((20, 160 + index * (size + 12)), line,
                      fill=('#00cd00' if green and line == MARKER else '#e8edf4'), font=font)
        output = io.BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()

    def verify(self, png, **kwargs):
        return verify_terminal_screenshot(png, expected_token=kwargs.pop('token', TOKEN),
                                          bounds=kwargs.pop('bounds', (10, 150, 800, 360)), **kwargs)

    def test_real_ocr_accepts_independent_positive_at_different_fonts_sizes_and_color(self):
        for size, green, mono in ((20, False, False), (32, True, True)):
            with self.subTest(size=size, green=green, monospace=mono):
                png = self.raster(['POCKET-ANDROID-READY', '$', MARKER, TOKEN, '$'],
                                  size=size, green=green, monospace=mono)
                evidence = self.verify(png)
                self.assertTrue(evidence['markerVisible'])
                self.assertTrue(evidence['tokenVisible'])
                self.assertEqual(evidence['imageSize'], [820, 540])
                self.assertRegex(evidence['imageSha256'], r'^[a-f0-9]{64}$')
                self.assertRegex(evidence['ocrEngine'], r'^tesseract [0-9.]+$')
                self.assertEqual(evidence['expectedMarker'], MARKER)
                self.assertEqual(evidence['expectedToken'], TOKEN)
                public = json.dumps(evidence)
                self.assertNotIn('READY', public)

    def test_real_ocr_rejects_ready_only_and_wrong_echo_word(self):
        for lines in (['POCKET-ANDROID-READY', '$'],
                      ['POCKET-ANDROID-SSH-NO', TOKEN],
                      [MARKER + 'AY', TOKEN]):
            with self.subTest(lines=lines), self.assertRaisesRegex(ScreenshotGateError, 'echo_not_visible'):
                self.verify(self.raster(lines))

    def test_real_ocr_rejects_old_or_partial_token(self):
        for token in ('ACDEFHJKMN37', TOKEN + 'X', TOKEN[:-1]):
            with self.subTest(token=token), self.assertRaisesRegex(ScreenshotGateError, 'token_not_visible'):
                self.verify(self.raster([MARKER, token]))

    def test_real_flutter_bundled_font_pixels_and_wrong_token(self):
        # Real TerminalView raster, Flutter 3.47.9 with the project's licensed
        # ProbeNerd/JetBrainsMono font. Synthetic input; not a device/SSH proof.
        png = Path(__file__).with_name('testdata') / 'flutter-terminal-font-control.png'
        evidence = self.verify(png, bounds=(0, 0, 550, 220))
        self.assertTrue(evidence['markerVisible'])
        self.assertTrue(evidence['tokenVisible'])
        with self.assertRaisesRegex(ScreenshotGateError, 'token_not_visible'):
            self.verify(png, token='ACDEFHJKMN37', bounds=(0, 0, 550, 220))

    def test_recognition_paths_cannot_combine_separate_partial_matches(self):
        replies = [CompletedProcess([], 0, b'tesseract 5.3.4', b''),
                   CompletedProcess([], 0, MARKER.encode(), b''),
                   CompletedProcess([], 0, TOKEN.encode(), b'')]
        with patch('terminal_screenshot_gate.subprocess.run', side_effect=replies):
            with self.assertRaises(ScreenshotGateError) as caught:
                self.verify(self.raster([MARKER, TOKEN]))
        self.assertFalse(caught.exception.evidence['markerVisible'] and
                         caught.exception.evidence['tokenVisible'])

    def test_app_chrome_cannot_substitute_for_terminal_pixels(self):
        png = self.raster(['POCKET-ANDROID-READY', '$'], chrome=[MARKER, TOKEN])
        with self.assertRaisesRegex(ScreenshotGateError, 'echo_not_visible'):
            self.verify(png)

    def test_clipped_token_is_not_visible(self):
        png = self.raster([MARKER, '', '', '', TOKEN])
        with self.assertRaisesRegex(ScreenshotGateError, 'token_not_visible'):
            self.verify(png, bounds=(10, 150, 800, 120))

    def test_bad_image_and_outside_rectangle_fail_closed(self):
        with self.assertRaisesRegex(ScreenshotGateError, 'png_invalid'):
            self.verify(b'not PNG')
        png = self.raster([MARKER, TOKEN])
        for bounds in ((-1, 150, 800, 360), (10, 150, 820, 360), (0, 0, 0, 50)):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(ScreenshotGateError, 'bounds_invalid'):
                self.verify(png, bounds=bounds)

    def test_missing_or_broken_ocr_has_public_failure_without_transcript(self):
        png = self.raster([MARKER, TOKEN])
        with patch('terminal_screenshot_gate.shutil.which', return_value=None):
            with self.assertRaisesRegex(ScreenshotGateError, 'ocr_missing') as caught:
                self.verify(png)
        self.assertFalse(caught.exception.evidence['markerVisible'])
        with patch('terminal_screenshot_gate.subprocess.run', side_effect=OSError('private transcript')):
            with self.assertRaisesRegex(ScreenshotGateError, 'ocr_failed') as caught:
                self.verify(png)
        self.assertNotIn('private transcript', str(caught.exception))
        self.assertNotIn('private transcript', json.dumps(caught.exception.evidence))


@unittest.skipUnless(importlib.util.find_spec('paramiko') is not None, 'Paramiko required')
class ScreenProofFixtureTests(unittest.TestCase):
    def shell_exchange(self, fixture):
        import paramiko
        peer = paramiko.Transport(('127.0.0.1', fixture.port))
        self.addCleanup(peer.close)
        peer.start_client(timeout=5)
        peer.auth_password(fixture.username, fixture.password)
        channel = peer.open_session(timeout=5)
        channel.get_pty(term='xterm-256color', width=80, height=24)
        channel.invoke_shell()
        channel.settimeout(5)
        ready = b''
        while not ready.endswith(b'\r\n$ '):
            chunk = channel.recv(4096)
            self.assertTrue(chunk)
            ready += chunk
        self.assertEqual(ready, b'POCKET-ANDROID-READY\r\n$ ')
        channel.sendall(b'hp-check\r')
        reply = b''
        while not reply.endswith(b'\r\n$ '):
            chunk = channel.recv(4096)
            self.assertTrue(chunk)
            reply += chunk
        return reply

    def test_default_wire_protocol_is_unchanged(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture() as fixture:
            self.assertIsNone(fixture.screen_token)
            self.assertEqual(self.shell_exchange(fixture), b'\r\n\x1b[32mPOCKET-ANDROID-SSH-OK\x1b[0m\r\n$ ')

    def test_opt_in_emits_a_fresh_server_only_token_on_separate_line(self):
        from direct_ssh_fixture import DirectSshFixture
        with DirectSshFixture(screen_proof=True) as first, DirectSshFixture(screen_proof=True) as second:
            self.assertNotEqual(first.screen_token, second.screen_token)
            for fixture in (first, second):
                self.assertRegex(fixture.screen_token, r'^[ACDEFHJKMNPQRTUVWXY34679]{12}$')
                self.assertEqual(self.shell_exchange(fixture),
                                 ('\r\n\x1b[32mPOCKET-ANDROID-SSH-OK\x1b[0m\r\n' +
                                  fixture.screen_token + '\r\n$ ').encode())


if __name__ == '__main__':
    unittest.main()
