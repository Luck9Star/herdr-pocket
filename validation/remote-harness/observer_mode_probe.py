#!/usr/bin/env python3
"""Read-only observer mode probe on a disposable local herdr session.

Requires an explicitly selected herdr binary. No SSH, user identity or live
session is read. Output is a bounded JSON result, never terminal contents.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

FIXTURE = r"""import curses
import json
import os
import time
from pathlib import Path

root = Path(__file__).parent
sizes = []
last_sample = 0


def sample():
    global last_sample
    size = os.get_terminal_size(1)
    sizes.append([size.columns, size.lines])
    last_sample = time.monotonic()


def wait(name):
    end = time.monotonic() + 30
    while time.monotonic() < end:
        if (root / name).exists():
            return
        if (root / "abort").exists():
            raise SystemExit(0)
        if time.monotonic() - last_sample >= 0.05:
            sample()
        time.sleep(0.01)
    raise RuntimeError("fixture_timeout")


def app(screen):
    curses.setupterm(term="xterm-256color", fd=1)
    screen.keypad(True)
    screen.addstr(0, 0, "HPREADY")
    screen.refresh()
    sample()
    if b"\x1b[?1l" not in curses.tigetstr("rmkx") or b"\x1b[?1h" not in curses.tigetstr(
        "smkx"
    ):
        raise RuntimeError("terminfo_mode_invalid")
    (root / "ready").touch()
    for i in range(1, 5):
        wait("step-" + str(i))
        if i == 1:
            os.write(1, b"\x1b[?2004h")
        elif i == 2:
            os.write(1, curses.tigetstr("rmkx"))
        elif i == 3:
            os.write(1, b"\x1b[?2004l")
        else:
            os.write(1, curses.tigetstr("smkx"))
        sample()
        (root / ("done-" + str(i))).touch()
        wait("show-" + str(i))
        screen.addstr(5 + i, 0, "HPVIS%02d" % i)
        screen.refresh()
        sample()
        (root / ("shown-" + str(i))).touch()
    wait("stop")


try:
    curses.wrapper(app)
finally:
    (root / "sizes.json").write_text(json.dumps(sizes))
    (root / "fixture-exited").touch()
"""


def fail(code):
    raise RuntimeError(code)


def wait_file(path, process, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            fail("server_exited")
        if path.exists():
            return
        time.sleep(0.02)
    fail("fixture_timeout")


class Frames:
    def __init__(self, process, cols, rows):
        self.process = process
        self.cols = cols
        self.rows = rows
        self.last = None
        self.pending = b""
        self.selector = selectors.DefaultSelector()
        os.set_blocking(process.stdout.fileno(), False)
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def read_for(self, seconds):
        end = time.monotonic() + seconds
        result = []
        while time.monotonic() < end:
            for key, _ in self.selector.select(
                min(0.1, max(0, end - time.monotonic()))
            ):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    fail("observer_ended")
                self.pending += chunk
                if len(self.pending) > 262144:
                    fail("frame_limit")
                while b"\n" in self.pending:
                    line, self.pending = self.pending.split(b"\n", 1)
                    try:
                        f = json.loads(line)
                        data = base64.b64decode(f["bytes"], validate=True)
                        seq = f["seq"]
                        if (
                            f.get("type") != "terminal.frame"
                            or f.get("encoding") != "ansi"
                            or type(seq) is not int
                            or seq < 0
                            or type(f.get("full")) is not bool
                            or type(f.get("width")) is not int
                            or type(f.get("height")) is not int
                            or (f["width"], f["height"]) != (self.cols, self.rows)
                            or len(data) > 65536
                            or (self.last is None and not f["full"])
                            or (self.last is not None and seq != self.last + 1)
                        ):
                            fail("invalid_frame")
                    except (KeyError, TypeError, ValueError):
                        fail("invalid_frame")
                    self.last = seq
                    result.append((seq, f["full"], data))
                    if len(result) > 128:
                        fail("frame_limit")
        return result

    def close(self):
        self.selector.close()


def same_typed(actual, expected):
    return (
        isinstance(actual, dict)
        and set(actual) == set(expected)
        and all(
            type(actual[k]) is type(v) and actual[k] == v for k, v in expected.items()
        )
    )


def mode_frame_seen(frames, before, state):
    return any(
        seq > before and full and data.endswith(mode_bytes(*state))
        for seq, full, data in frames
    )


def has_mode_bytes(frames):
    return any(
        any(
            code in data
            for code in (b"\x1b[?1h", b"\x1b[?1l", b"\x1b[?2004h", b"\x1b[?2004l")
        )
        for _, _, data in frames
    )


def fresh_visual_seen(frames, before, marker):
    return any(seq > before and marker in data for seq, _, data in frames)


def mode_bytes(cursor, paste):
    return (
        b"\x1b[?1"
        + (b"h" if cursor else b"l")
        + b"\x1b[?2004"
        + (b"h" if paste else b"l")
    )


def observe(args):
    binary = Path(args.binary).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        fail("binary_unavailable")
    if not (
        2 <= args.cols <= 512
        and 1 <= args.rows <= 512
        and args.cols * args.rows <= 65536
    ):
        fail("invalid_canvas")
    with tempfile.TemporaryDirectory(
        prefix="hpom-", dir="/tmp" if Path("/tmp").is_dir() else None
    ) as directory:
        root = Path(directory)
        home = root / "home"
        config = root / "config"
        runtime = root / "runtime"
        for path in (home, config, runtime, config / "herdr"):
            path.mkdir()
        (config / "herdr/config.toml").write_text("")
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_RUNTIME_DIR": str(runtime),
            "HERDR_CONFIG_PATH": str(config / "herdr/config.toml"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "SHELL": "/bin/sh",
            "LANG": "en_US.UTF-8",
            "TERM": "xterm-256color",
            "TMPDIR": str(root),
        }
        version = (
            subprocess.check_output(
                [str(binary), "--version"],
                env=env,
                cwd=root,
                stderr=subprocess.PIPE,
                timeout=10,
            )
            .decode("ascii")
            .strip()
        )
        if version != "herdr 0.9.5":
            fail("version_mismatch")
        with binary.open("rb") as stream:
            binary_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        session = "probe-" + uuid.uuid4().hex[:12]

        def call(*argv):
            return subprocess.check_output(
                [str(binary), "--session", session, *argv],
                env=env,
                cwd=root,
                stderr=subprocess.PIPE,
                timeout=20,
            )

        def request(method):
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(1)
            try:
                sock.connect(str(config / "herdr/sessions" / session / "herdr.sock"))
                sock.sendall(
                    (
                        json.dumps(
                            {"id": "observer-probe", "method": method, "params": {}}
                        )
                        + "\n"
                    ).encode()
                )
                value = b""
                while b"\n" not in value and len(value) < 131072:
                    block = sock.recv(65536)
                    if not block:
                        break
                    value += block
                if b"\n" not in value:
                    fail("invalid_rpc")
                response = json.loads(value.split(b"\n", 1)[0])
                if (
                    not isinstance(response, dict)
                    or response.get("id") != "observer-probe"
                ):
                    fail("invalid_rpc")
                return response
            finally:
                sock.close()

        processes = []
        reader = None
        fixture_started = False
        try:
            with (root / "server.log").open("wb") as log:
                server = subprocess.Popen(
                    [str(binary), "--session", session, "server"],
                    env=env,
                    cwd=root,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                processes.append(server)
                for _ in range(100):
                    if server.poll() is not None:
                        fail("server_exited")
                    try:
                        snapshot = request("session.snapshot").get("result", {})
                        if (
                            snapshot.get("type") == "session_snapshot"
                            and snapshot.get("snapshot", {}).get("version") == "0.9.5"
                            and type(snapshot["snapshot"].get("protocol")) is int
                            and snapshot["snapshot"]["protocol"] == 22
                        ):
                            break
                    except OSError:
                        pass
                    time.sleep(0.05)
                else:
                    fail("server_not_ready")
                capability = request("pocket.input.capabilities")
                expected_cap = {
                    "type": "pocket_input_capabilities",
                    "version": 1,
                    "protocol": 22,
                    "atomic_terminal_guard": True,
                    "raw_bytes": True,
                    "max_input_bytes": 4096,
                }
                if args.expect == "candidate" and not same_typed(
                    capability.get("result"), expected_cap
                ):
                    fail("candidate_capability_mismatch")
                if args.expect == "stock" and (
                    not isinstance(capability.get("error"), dict)
                    or capability["error"].get("code")
                    not in ("invalid_request", "unknown_method")
                ):
                    fail("stock_capability_unexpected")
                result = json.loads(
                    call(
                        "workspace",
                        "create",
                        "--cwd",
                        str(root),
                        "--label",
                        "observer-mode-fixture",
                    )
                )
                pane = result["result"]["root_pane"]["pane_id"]
                terminal = result["result"]["root_pane"]["terminal_id"]
                if (
                    not isinstance(pane, str)
                    or not isinstance(terminal, str)
                    or not terminal.startswith("term_")
                ):
                    fail("target_invalid")
                fixture = root / "fixture.py"
                fixture.write_text(FIXTURE)
                call(
                    "pane",
                    "run",
                    pane,
                    shlex.quote(sys.executable) + " " + shlex.quote(str(fixture)),
                )
                fixture_started = True
                wait_file(root / "ready", server)

                def start_observer():
                    observer = subprocess.Popen(
                        [
                            str(binary),
                            "--session",
                            session,
                            "terminal",
                            "session",
                            "observe",
                            terminal,
                            "--cols",
                            str(args.cols),
                            "--rows",
                            str(args.rows),
                        ],
                        env=env,
                        cwd=root,
                        stdout=subprocess.PIPE,
                        stderr=log,
                        start_new_session=True,
                    )
                    processes.append(observer)
                    return observer, Frames(observer, args.cols, args.rows)

                # A separate read-only observer confirms the fixture is parsed before
                # the measured observer's first full frame is requested.
                warm, warm_reader = start_observer()
                try:
                    warm_frames = []
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        warm_frames.extend(warm_reader.read_for(0.2))
                        if any(b"HPREADY" in frame[2] for frame in warm_frames):
                            break
                    else:
                        fail("initial_marker_missing")
                finally:
                    warm_reader.close()
                    if warm.poll() is None:
                        os.killpg(warm.pid, signal.SIGTERM)
                        warm.wait(timeout=4)
                observer, reader = start_observer()
                initial = []
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    initial.extend(reader.read_for(0.2))
                    if any(b"HPREADY" in frame[2] for frame in initial):
                        break
                else:
                    fail("initial_marker_missing")
                if not initial or not initial[0][1] or b"HPREADY" not in initial[0][2]:
                    fail("initial_full_missing")
                modes = [
                    (True, False),
                    (True, True),
                    (False, True),
                    (False, False),
                    (True, False),
                ]
                expected = mode_bytes(*modes[0])
                initial_synced = initial[0][2].endswith(expected)
                if args.expect == "candidate" and not initial_synced:
                    fail("initial_modes_missing")
                if args.expect == "stock" and has_mode_bytes(initial):
                    fail("stock_initial_mode_present")
                steps = []
                for i, state in enumerate(modes[1:], 1):
                    # Drain previously available frames before the fixture issues the next mode.
                    drained = reader.read_for(0.25)
                    if args.expect == "stock" and has_mode_bytes(drained):
                        fail("stock_mode_update_present")
                    before = reader.last
                    (root / f"step-{i}").touch()
                    wait_file(root / f"done-{i}", server)
                    mode_frames = reader.read_for(1.0)
                    actual = mode_frame_seen(mode_frames, before, state)
                    if args.expect == "candidate" and not actual:
                        fail("mode_only_update_missing")
                    if args.expect == "stock" and has_mode_bytes(mode_frames):
                        fail("stock_mode_update_present")
                    (root / f"show-{i}").touch()
                    wait_file(root / f"shown-{i}", server)
                    visual = []
                    marker = f"HPVIS{i:02d}".encode()
                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        visual.extend(reader.read_for(0.15))
                        if fresh_visual_seen(visual, before, marker):
                            break
                    else:
                        fail("fresh_visual_missing")
                    if args.expect == "candidate" and any(
                        full and not data.endswith(mode_bytes(*state))
                        for _, full, data in visual
                    ):
                        fail("full_frame_modes_missing")
                    if args.expect == "stock" and has_mode_bytes(visual):
                        fail("stock_mode_update_present")
                    steps.append(
                        {"modeOnlyFrameObserved": actual, "freshVisualObserved": True}
                    )
                (root / "stop").touch()
                wait_file(root / "fixture-exited", server)
                sizes = json.loads((root / "sizes.json").read_text())
                if (
                    not isinstance(sizes, list)
                    or len(sizes) < 9
                    or any(
                        not isinstance(size, list)
                        or len(size) != 2
                        or any(type(n) is not int or n < 1 for n in size)
                        for size in sizes
                    )
                    or any(size != sizes[0] for size in sizes)
                ):
                    fail("pty_size_changed")
                return {
                    "status": "passed",
                    "scope": "isolated local CLI observer; no SSH or shared PTY resize",
                    "expectation": args.expect,
                    "binarySha256": binary_hash,
                    "version": version,
                    "capabilityVerified": args.expect == "candidate",
                    "canvas": {"cols": args.cols, "rows": args.rows},
                    "initialFull": True,
                    "initialVisible": True,
                    "initialModeSynchronized": initial_synced,
                    "steps": steps,
                    "sequenceContiguous": True,
                    "sharedPtySizeUnchanged": True,
                    "ptySampleCount": len(sizes),
                }
        finally:
            if fixture_started and not (root / "fixture-exited").exists():
                (root / "abort").touch()
                deadline = time.monotonic() + 2
                while (
                    time.monotonic() < deadline
                    and not (root / "fixture-exited").exists()
                ):
                    time.sleep(0.02)
            if reader:
                reader.close()
            for process in reversed(processes):
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expect", choices=("stock", "candidate"), required=True)
    parser.add_argument("--cols", type=int, default=120)
    parser.add_argument("--rows", type=int, default=40)
    args = parser.parse_args()
    try:
        print(json.dumps(observe(args), sort_keys=True))
    except (
        OSError,
        subprocess.SubprocessError,
        RuntimeError,
        KeyError,
        ValueError,
    ) as error:
        allowed = {
            "binary_unavailable",
            "invalid_canvas",
            "version_mismatch",
            "invalid_rpc",
            "candidate_capability_mismatch",
            "stock_capability_unexpected",
            "server_exited",
            "server_not_ready",
            "target_invalid",
            "fixture_timeout",
            "observer_ended",
            "frame_limit",
            "invalid_frame",
            "initial_marker_missing",
            "initial_full_missing",
            "initial_modes_missing",
            "stock_initial_mode_present",
            "mode_only_update_missing",
            "stock_mode_update_present",
            "fresh_visual_missing",
            "full_frame_modes_missing",
            "pty_size_changed",
        }
        code = (
            str(error)
            if isinstance(error, RuntimeError) and str(error) in allowed
            else "observer_probe_failed"
        )
        print(json.dumps({"status": "failed", "error": code}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
