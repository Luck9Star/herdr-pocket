#!/usr/bin/env python3
"""Capture real ordinary SSH live layouts in an isolated prepared app."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("geometry", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    app, output = args.app.resolve(), args.output.resolve()
    if not (app / ".herdr-generated-probe.json").is_file():
        parser.error("app is not an isolated scaffold")
    output.mkdir()
    test = "live_geometry_test.dart"
    shutil.copyfile(HERE / test, app / "test" / test)
    with subprocess.Popen([sys.executable, "-u", str(HERE / "live_peer.py"), str(app / "test/direct_ssh_fixture.py")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as peer:
        try:
            first_line = peer.stdout.readline()
            prefix, _, port = first_line.strip().partition(" ")
            if prefix != "PORT" or not port.isdigit():
                raise RuntimeError(f"fixture did not report a port: {first_line}")
            env = dict(os.environ, HERDR_DIRECT_SSH_FIXTURE_PORT=port, HERDR_WORKFLOW_CAPTURE=str(output),
                       HERDR_ENTRY_DESIGN=str(args.geometry.resolve()), HERDR_LIVE_VERIFY=str(int(args.verify)))
            with (output / "widgets.log").open("w") as log:
                result = subprocess.run(["flutter", "test", "--no-pub", "--reporter", "expanded", f"test/{test}"],
                                        cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        finally:
            peer.terminate()
            peer_log = peer.communicate(timeout=10)[0]
            (output / "peer.log").write_text(peer_log)
    lines = peer_log.splitlines()
    auth = lines.count("AUTH fixture")
    pty = sum(line.startswith("PTY ") for line in lines)
    eof = lines.count("STDIN_EOF")
    inputs = [line for line in lines if line.startswith("INPUT ")]
    pngs = len(list(output.glob("*.png")))
    print(f"Flutter exit={result.returncode}, AUTH={auth}, PTY={pty}, EOF={eof}, INPUT={len(inputs)}, PNG={pngs}. Logs: {output}")
    expected = (3, 3, 3, ["INPUT b'Q'"] * 3, 12) if args.verify else (3, 3, 3, [], 3)
    if result.returncode or (auth, pty, eof, inputs, pngs) != expected:
        sys.exit(1)


if __name__ == "__main__":
    main()
