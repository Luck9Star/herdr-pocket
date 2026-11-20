"""Disposable macOS S06 fixture: two private OpenSSH listeners and herdr servers."""

import argparse
import getpass
import hashlib
import importlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument(
    "--project",
    type=Path,
    required=True,
    help="Isolated app from Flutter ci.py prepare",
)
parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
parser.add_argument("--herdr", type=Path, required=True)
parser.add_argument("--flutter", default="flutter")
parser.add_argument("--cjk-font", type=Path)
parser.add_argument(
    "--docker-image",
    help="Local linux/amd64 image with Python and OpenSSH, for guarded herdr",
)
parser.add_argument(
    "--guarded-manifest",
    type=Path,
    help="Source manifest with shared bundle herdr and guard patch hashes",
)
args = parser.parse_args()
repo = args.repo.resolve()
app = args.project.resolve()
evidence = args.output.resolve()
fixture_binary = args.herdr.resolve()
guarded = args.docker_image is not None
if guarded != (args.guarded_manifest is not None):
    parser.error(
        "Provide both --docker-image and --guarded-manifest for guarded testing"
    )
binary_sha = hashlib.sha256(fixture_binary.read_bytes()).hexdigest()
if guarded:
    manifest = json.loads(args.guarded_manifest.read_bytes())
    guard_patch = "validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch"
    patch_sha = hashlib.sha256((repo / guard_patch).read_bytes()).hexdigest()
    if (
        manifest["files"]["herdr"] != binary_sha
        or manifest["materials"][guard_patch] != patch_sha
    ):
        parser.error("Guarded binary or source patch does not match fixture manifest")
evidence.mkdir(mode=0o700)
sys.path.insert(0, str(repo / "validation/remote-harness"))
paired_gui = importlib.import_module("paired_gui")

root = Path(tempfile.mkdtemp(prefix="hp-m105-", dir="/tmp"))
username = "root" if guarded else getpass.getuser()
container = None
children = []
fixture_dirs = []
approvals = []
env = {
    k: v
    for k, v in os.environ.items()
    if not k.startswith("HERDR_")
    and k not in ("SSH_AUTH_SOCK", "SSH_AGENT_PID", "BASH_ENV")
}


def until(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.06)
    raise RuntimeError("timeout")


def spawn(argv, log, **kwargs):
    with log.open("w") as output:
        proc = subprocess.Popen(
            [str(x) for x in argv],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            **kwargs,
        )
    children.append(proc)
    return proc


def run(argv, **kwargs):
    return subprocess.run(
        [str(x) for x in argv],
        capture_output=True,
        timeout=12,
        check=True,
        **kwargs,
    ).stdout


source = repo / "validation/flutter"
source_files = [
    *source.joinpath("lib").rglob("*.dart"),
    source / "test/s06_real_ssh_test.dart",
    source / "test/import_widget_evidence.dart",
]
if not source.joinpath("lib").is_dir() or any(
    path.read_bytes() != (app / path.relative_to(source)).read_bytes()
    for path in source_files
):
    raise RuntimeError("prepared_flutter_sources_do_not_match")
try:
    source_sha = run(["git", "-C", repo, "rev-parse", "HEAD"]).decode().strip()
except subprocess.CalledProcessError:
    source_sha = None


def target(argv, env=None):
    if not guarded:
        return argv, env
    options = [
        part
        for key, value in (env or {}).items()
        if key.startswith("XDG_") or key == "SHELL"
        for part in ("-e", f"{key}={value}")
    ]
    return ["docker", "exec", *options, container, *argv], None


def target_run(argv, env=None):
    command, command_env = target(argv, env)
    return run(command, env=command_env)


def target_spawn(argv, log, env=None):
    command, command_env = target(argv, env)
    return spawn(command, log, env=command_env)


def states(fixtures, approvals):
    result = []
    for fixture, approval in zip(fixtures, approvals):
        log = (fixture / "sshd.log").read_text(errors="replace")
        ports = re.findall(
            r"Accepted publickey for "
            + re.escape(username)
            + r" from ([0-9a-fA-F.:]+) port (\d+) ssh2: ED25519 "
            + re.escape(approval.fingerprint)
            + r"(?:\s|$)",
            log,
        )
        # Independent server log on an isolated listener. Read the close of
        # the exact authenticated client source port, ignoring readiness probes.
        closed = any(
            re.search(
                r"(?:Connection closed by (?:user [^ ]+ )?|Disconnected from user "
                + re.escape(username)
                + r" )"
                + re.escape(address)
                + r" port "
                + port
                + r"(?:\s|$)",
                log,
            )
            for address, port in ports
        )
        result.append({"authentications": len(ports), "closed": closed})
    return result


def peer(index):
    f = root / str(index)
    f.mkdir(mode=0o700)
    fixture_dirs.append(f)
    cfg = f / "config"
    cfg.mkdir()
    (cfg / "herdr").mkdir()
    (cfg / "herdr/config.toml").write_text(
        "[update]\nversion_check = false\nmanifest_check = false\n"
    )
    session = ["pocket-probe", "pocket-other"][index]
    child_env = dict(
        env,
        XDG_CONFIG_HOME=str(cfg),
        XDG_STATE_HOME=str(f / "state"),
        XDG_DATA_HOME=str(f / "data"),
        XDG_CACHE_HOME=str(f / "cache"),
        SHELL="/bin/sh",
    )
    herdr = f / "herdr"
    herdr.symlink_to(root / "herdr")
    target_spawn(
        [herdr, "--session", session, "server"], f / "herdr.log", env=child_env
    )
    sock = cfg / "herdr/sessions" / session / "herdr.sock"

    def ready():
        try:
            target_run(["test", "-S", sock])
            return True
        except subprocess.CalledProcessError:
            return False

    until(ready, 10)
    created = json.loads(
        target_run(
            [
                herdr,
                "--session",
                session,
                "workspace",
                "create",
                "--cwd",
                f,
                "--label",
                session,
            ],
            env=child_env,
        )
    )
    pane = created["result"]["root_pane"]["pane_id"]
    capture = (repo / "validation/remote-harness/capture_input.py").read_text()
    frames = (repo / "validation/shared/fixture.json").read_text()
    if index:
        capture = capture.replace("Synthetic observe tick", "S06 B tick")
        frames = frames.replace(
            "herdr-pocket / same fixture v1", "herdr-pocket / S06 peer B"
        )
    (f / "capture_input.py").write_text(capture)
    (f / "terminal-fixture.json").write_text(frames)
    target_run(
        [
            herdr,
            "--session",
            session,
            "pane",
            "run",
            pane,
            shlex.join(
                ["python3" if guarded else sys.executable, str(f / "capture_input.py")]
            ),
        ],
        env=child_env,
    )
    until((f / "capture-ready").is_file, 10)
    for name in ("host", "client"):
        run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "ephemeral-m105",
                "-f",
                f / name,
            ]
        )
    if guarded:
        target_port = 22221 + index
        published = (
            run(["docker", "port", container, f"{target_port}/tcp"]).decode().strip()
        )
        host, _, text_port = published.rpartition(":")
        if host != "127.0.0.1":
            raise RuntimeError("unsafe_fixture_listener")
        port = int(text_port)
    else:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = target_port = probe.getsockname()[1]
    allow = f / "authorized_keys"
    allow.touch(mode=0o600)
    cfg_path = f / "sshd_config"
    cfg_path.write_text(f"""ListenAddress {"0.0.0.0" if guarded else "127.0.0.1"}
Port {target_port}
HostKey {f}/host
PidFile {f}/sshd.pid
AuthorizedKeysFile {allow}
StrictModes no
UsePAM no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitRootLogin {"prohibit-password" if guarded else "no"}
AllowUsers {username}
PermitTTY no
AllowAgentForwarding no
AllowTcpForwarding local
AllowStreamLocalForwarding local
X11Forwarding no
PrintMotd no
LogLevel VERBOSE
""")
    target_run(["/usr/sbin/sshd", "-t", "-f", cfg_path])
    target_spawn(["/usr/sbin/sshd", "-D", "-e", "-f", cfg_path], f / "sshd.log")
    until(lambda: "Server listening" in (f / "sshd.log").read_text(), 5)
    host_key = " ".join((f / "host.pub").read_text().split()[:2])
    scratch = f / "helper"
    scratch.mkdir(mode=0o700)
    config = {
        "schemaVersion": 1,
        "host": "127.0.0.1",
        "port": port,
        "username": username,
        "expectedHostKey": host_key,
        "socketPath": str(sock),
        "herdrPath": str(herdr),
        "session": session,
        "paneId": pane,
        "reviewConfirmed": True,
    }
    approvals.append(
        paired_gui.FixtureApproval(
            f, config, paired_gui.Host(scratch, username, host_key)
        )
    )
    return config


try:
    shutil.copyfile(fixture_binary, root / "herdr")
    (root / "herdr").chmod(0o700)
    if guarded:
        container = (
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-d",
                    "--pull",
                    "never",
                    "--platform",
                    "linux/amd64",
                    "--init",
                    "--mount",
                    f"type=bind,source={root},target={root}",
                    "-p",
                    "127.0.0.1::22221",
                    "-p",
                    "127.0.0.1::22222",
                    args.docker_image,
                    "sleep",
                    "600",
                ]
            )
            .decode()
            .strip()
        )
    configs = [peer(i) for i in range(2)]
    if configs[0]["paneId"] != configs[1]["paneId"]:
        raise RuntimeError("fixture_pane_ids_differ")
    if (
        not guarded
        and len({paired_gui.fixture_terminal_id(config) for config in configs}) != 2
    ):
        raise RuntimeError("fixture_terminal_ids_overlap")
    exchange = root / "exchange"
    exchange.mkdir(mode=0o700)
    config = exchange / "config.json"
    config.write_text(json.dumps(configs))
    widget_env = dict(
        env,
        HERDR_S06_CONFIG=str(config),
        HERDR_S06_DIR=str(exchange),
        HERDR_S06_KEY_A=str(fixture_dirs[0] / "client"),
        HERDR_S06_KEY_B=str(fixture_dirs[1] / "client"),
        HERDR_S06_GUARDED="1" if guarded else "0",
        HERDR_S06_IMPORT_REPLACE="1",
    )
    if args.cjk_font:
        widget_env["HERDR_S06_CJK_FONT"] = str(args.cjk_font.resolve())
    widget = spawn(
        [
            args.flutter,
            "test",
            "--no-pub",
            "--reporter",
            "expanded",
            "test/s06_real_ssh_test.dart",
        ],
        evidence / "widget.log",
        cwd=app,
        env=widget_env,
    )

    def widget_stage(predicate):
        if widget.poll() is not None:
            raise RuntimeError("widget_exited")
        return predicate()

    for i, approval in enumerate(approvals):
        request = exchange / f"request-{i}.json"
        until(lambda request=request: widget_stage(request.is_file), 65)
        response = approval.approve(request.read_bytes())
        tmp = exchange / f"response-{i}.new"
        tmp.write_bytes(response)
        tmp.rename(exchange / f"response-{i}.json")
    peer_observations = {}
    receipt_checkpoints = {}
    for name, expected in [
        (
            "focused",
            [
                {"authentications": 1, "closed": True},
                {"authentications": 1, "closed": False},
            ],
        ),
        (
            "final",
            [
                {"authentications": 1, "closed": True},
                {"authentications": 1, "closed": True},
            ],
        ),
    ]:
        until(
            lambda name=name: widget_stage(
                (exchange / f"{name}-close-request").is_file
            ),
            90,
        )
        until(
            lambda expected=expected: widget_stage(
                lambda: states(fixture_dirs, approvals) == expected
            ),
            15,
        )
        checkpoint = "afterImportBeforeSurvivorInput" if name == "focused" else "final"
        peer_observations[checkpoint] = states(fixture_dirs, approvals)
        receipts = [(f / "received.bin").read_bytes() for f in fixture_dirs]
        expected_receipts = (
            ["Pocket测".encode(), b"b" if name == "focused" else b"bs"]
            if guarded
            else [b"", b""]
        )
        if receipts != expected_receipts:
            raise RuntimeError("fixture_received_bytes_mismatch")
        receipt_checkpoints[checkpoint] = list(map(len, receipts))
        (exchange / f"{name}-close-ack").touch(exist_ok=False)
    if widget.wait(timeout=30):
        raise RuntimeError("widget_failed")
    widget_result = json.loads((exchange / "result.json").read_text())
    if widget_result.get("replacedTabRetainedAndPeerAdvanced") is not True:
        raise RuntimeError("widget_import_evidence_missing")
    report = {
        "status": "passed",
        "sourceSHA": source_sha,
        "preparedSourceMatched": True,
        "widget": widget_result,
        "separatePeerListeners": True,
        "peerObservations": peer_observations,
        "receiptByteCounts": receipt_checkpoints,
        "exactExpectedReceipts": True,
        "herdrSha256": binary_sha,
        "guarded": guarded,
        "herdrVersion": target_run([root / "herdr", "--version"]).decode().strip(),
    }
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
except Exception:
    if approvals and all(a.fingerprint for a in approvals):
        (evidence / "peer-status.json").write_text(
            json.dumps(states(fixture_dirs, approvals))
        )
    raise
finally:
    if (root / "exchange").is_dir():
        for name in ("stage", "failure.json", "import-before.png", "import-after.png"):
            src = root / "exchange" / name
            if src.is_file():
                shutil.copy2(src, evidence / name)
    for proc in reversed(children):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for proc in reversed(children):
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)
    if container:
        run(["docker", "rm", "-f", container])
    shutil.rmtree(root)
