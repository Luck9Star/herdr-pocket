"""Drive the two production auxiliary key encoders against a new local curses PTY."""
import argparse
import errno
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

from owned_pty import new_pty, restored_modes
from paired_tui import EXPECTED, STEPS


HERE = Path(__file__).resolve().parent
VALIDATION = HERE.parent
KEYS = [key for key, _, _ in STEPS]


def collect(master, screen, seconds, until=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if until and until in screen:
            return
        if not select.select([master], [], [], max(0, deadline - time.monotonic()))[0]:
            return
        try:
            part = os.read(master, 4096)
        except OSError as error:
            if error.errno == errno.EIO:  # Linux PTY at EOF
                return
            raise
        if not part:
            return
        screen.extend(part)
        if len(screen) > 131072:
            raise ValueError('fixture_output_limit')


def drive(keys_for_mode, *, seconds=12, cancel=False):
    """Only the owned PTY is written. The returned report omits input and screen contents."""
    with tempfile.TemporaryDirectory(prefix='hp-phone-tui-') as folder:
        report = Path(folder) / 'result.json'
        with new_pty() as (master, slave):
            original = termios.tcgetattr(slave)
            process = subprocess.Popen(
                [sys.executable, str(HERE / 'phone_tui_fixture.py'), '--report', str(report),
                 '--seconds', str(seconds)], cwd=folder, env={'TERM': 'xterm-256color', 'LC_ALL': 'C'},
                stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            )
            try:
                screen = bytearray()
                collect(master, screen, 5, until=b'F10 Finish')
                if b'Pocket TUI' not in screen or b'F10 Finish' not in screen:
                    raise ValueError('fixture_not_ready')
                application_cursor = b'\x1b[?1h' in screen
                for chunk in keys_for_mode(application_cursor):
                    if not isinstance(chunk, bytes) or not 0 < len(chunk) <= 32:
                        raise ValueError('invalid_fixture_key')
                    if os.write(master, chunk) != len(chunk):
                        raise ValueError('partial_fixture_input')
                    collect(master, screen, 0.05)
                if cancel:
                    process.send_signal(signal.SIGTERM)
                # Drain the PTY while waiting for endwin(); the application can
                # still write its final screen and alternate-buffer exit here.
                deadline = time.monotonic() + seconds + 3
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('fixture_exit_timeout')
                    collect(master, screen, 0.05)
                collect(master, screen, 0.05)
                return {'exitCode': process.returncode, 'applicationCursor': application_cursor,
                        'enteredAlternateScreen': b'\x1b[?1049h' in screen,
                        'leftAlternateScreen': b'\x1b[?1049l' in screen,
                        'modesRestored': restored_modes(termios.tcgetattr(slave)) == restored_modes(original),
                        'viewportUnchanged': os.get_terminal_size(slave) == (80, 24),
                        'application': json.loads(report.read_text(encoding='utf-8'))}
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def production_bytes(route, runtime, application_cursor):
    # Both encoders are the same modules used by the two mobile GUI routes.
    args = [str(int(application_cursor)), *KEYS]
    if route == 'tauri':
        uri = (VALIDATION / 'tauri/src/input-codec.js').as_uri()
        code = f"""import {{ auxiliaryKey }} from {json.dumps(uri)};
const [mode, ...keys] = process.argv.slice(1);
console.log(JSON.stringify(keys.map(key => Array.from(new TextEncoder().encode(auxiliaryKey(key, mode === '1'))))));"""
        result = subprocess.check_output([runtime, '--input-type=module', '-e', code, *args], timeout=15)
    else:
        uri = (VALIDATION / 'flutter/lib/remote_auxiliary.dart').as_uri()
        code = f"""import 'dart:convert';
import '{uri}';
void main(List<String> args) {{
  print(jsonEncode(args.skip(1).map((key) =>
      utf8.encode(auxiliaryKey(key, applicationCursorMode: args.first == '1')!)).toList()));
}}"""
        with tempfile.TemporaryDirectory(prefix='hp-phone-codec-') as folder:
            script = Path(folder) / 'probe.dart'
            script.write_text(code, encoding='utf-8')
            result = subprocess.check_output([runtime, str(script), *args], timeout=15)
    encoded = json.loads(result)
    if len(encoded) != len(KEYS):
        raise ValueError('incomplete_codec_output')
    return [bytes(value) for value in encoded]


def confirmed(result):
    return result['exitCode'] == 0 and result['application'] == EXPECTED and all(
        result[key] is True for key in ('applicationCursor', 'enteredAlternateScreen',
                                       'leftAlternateScreen', 'modesRestored', 'viewportUnchanged'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('route', choices=('flutter', 'tauri'))
    parser.add_argument('--runtime', help='Dart or Node executable used by the candidate')
    args = parser.parse_args()
    runtime = args.runtime or shutil.which('dart' if args.route == 'flutter' else 'node')
    report = {'route': args.route, 'scope': 'production codec to owned local PTY', 'passed': False}
    if runtime:
        try:
            result = drive(lambda mode: production_bytes(args.route, runtime, mode))
            report.update(result, passed=confirmed(result))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['error'] = type(error).__name__
    else:
        report['error'] = 'candidate_runtime_unavailable'
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
