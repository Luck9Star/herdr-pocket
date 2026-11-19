#!/usr/bin/env python3
"""Drive widget taps against one isolated Paramiko peer per suite."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, help="isolated Flutter scaffold from ci.py prepare")
    parser.add_argument("output", type=Path, help="new directory for logs and optional PNGs")
    parser.add_argument("--navigation", action="store_true", help="run three cross-width sessions")
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    if not (project / ".herdr-generated-probe.json").is_file():
        parser.error("project is not the generated Flutter scaffold")
    output.mkdir()
    test_file = "direct_ssh_responsive_navigation_test.dart" if args.navigation else "close_layout_pixels_test.dart"
    if not args.navigation:
        shutil.copyfile(ROOT / test_file, project / "test" / test_file)
    expected = 3 if args.navigation else 5
    with subprocess.Popen([sys.executable, "-u", str(project / "test/direct_ssh_fixture.py")],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as peer:
        try:
            first_line = peer.stdout.readline()
            prefix, _, port = first_line.strip().partition(" ")
            if prefix != "PORT" or not port.isdigit():
                raise RuntimeError(f"fixture did not report a port: {first_line}")
            env = dict(os.environ, HERDR_DIRECT_SSH_FIXTURE_PORT=port,
                       HERDR_OUTCOME_PIXELS=str(output))
            with (output / "widgets.log").open("w") as log:
                result = subprocess.run(
                    ["flutter", "test", "--no-pub", "--reporter", "expanded", f"test/{test_file}"],
                    cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        finally:
            peer.terminate()
            peer_log = peer.communicate(timeout=10)[0]
            (output / "peer.log").write_text(peer_log)
    auth = sum(line == "AUTH fixture" for line in peer_log.splitlines())
    pty = sum(line.startswith("PTY ") for line in peer_log.splitlines())
    images = len(list(output.glob("*.png")))
    print(f"Flutter exit={result.returncode}, AUTH={auth}, PTY={pty}, PNG={images}. Logs: {output}")
    if result.returncode or (auth, pty, images) != (expected, expected, 0 if args.navigation else 15):
        sys.exit(1)


if __name__ == "__main__":
    main()
