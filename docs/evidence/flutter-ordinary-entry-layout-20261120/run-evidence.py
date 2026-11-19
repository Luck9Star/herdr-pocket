#!/usr/bin/env python3
"""Measure desktop SSH entry against the frozen geometry using a disposable peer."""
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
    parser.add_argument("geometry", type=Path, help="geometry.json from direct-ssh-desktop.mjs")
    parser.add_argument("output", type=Path, help="new directory for PNGs and logs")
    parser.add_argument("--verify", default="", help="comma-separated states to check within 2pt")
    args = parser.parse_args()
    project, output = args.project.resolve(), args.output.resolve()
    if not (project / ".herdr-generated-probe.json").is_file():
        parser.error("project is not the generated Flutter scaffold")
    output.mkdir()
    test_file = "entry_geometry_test.dart"
    shutil.copyfile(ROOT / test_file, project / "test" / test_file)
    fixture = project / "test/direct_ssh_fixture.py"
    with subprocess.Popen([sys.executable, "-u", str(fixture)], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True) as peer:
        try:
            first_line = peer.stdout.readline()
            prefix, _, port = first_line.strip().partition(" ")
            if prefix != "PORT" or not port.isdigit():
                raise RuntimeError(f"fixture did not report a port: {first_line}")
            env = dict(os.environ, HERDR_DIRECT_SSH_FIXTURE_PORT=port, HERDR_ENTRY_PIXELS=str(output),
                       HERDR_ENTRY_DESIGN=str(args.geometry.resolve()), HERDR_ENTRY_VERIFY=args.verify)
            with (output / "widgets.log").open("w") as log:
                result = subprocess.run(
                    ["flutter", "test", "--no-pub", "--reporter", "expanded", f"test/{test_file}"],
                    cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
        finally:
            peer.terminate()
            peer_log = peer.communicate(timeout=10)[0]
            (output / "peer.log").write_text(peer_log)
    auth = sum(line.startswith(("AUTH ", "PUBLICKEY ")) for line in peer_log.splitlines())
    pty = sum(line.startswith("PTY ") for line in peer_log.splitlines())
    images = len(list(output.glob("*.png")))
    print(f"Flutter exit={result.returncode}, AUTH={auth}, PTY={pty}, PNG={images}. Logs: {output}")
    if result.returncode or (auth, pty, images) != (0, 0, 18):
        sys.exit(1)


if __name__ == "__main__":
    main()
