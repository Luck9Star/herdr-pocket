#!/usr/bin/env python3
"""Run the opt-in M3-05 product Widget against a disposable loopback SSH peer."""

import argparse
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = "flutter_input_receipt_fixture"
TEST = "test/input_receipt_recovery_widget_test.dart"
STAGES = [
    "product_home", "initial_a_full_delta", "unknown_a_target_locked",
    "switch_b_a_lock_retained", "reconnect_a_fresh_full",
    "manual_confirmation_no_replay", "stopped",
]
TERMINALS = ["term_a001", "term_b002", "term_a001"]


class VerificationError(Exception):
    pass


@contextmanager
def owned_process(argv, *, cwd, log, env=None):
    with log.open("wb") as output:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=output,
                                stderr=subprocess.STDOUT, start_new_session=True)
        try:
            yield proc
        finally:
            # Tear down the test engine as well as its launcher on a timeout.
            for signum in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, signum)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    continue
            proc.wait(timeout=5)


def checked(argv, *, cwd, work, label, timeout=180, env=None):
    try:
        with owned_process(argv, cwd=cwd, log=work / f"{label}.log", env=env) as proc:
            if proc.wait(timeout=timeout):
                raise VerificationError(label)
    except subprocess.TimeoutExpired:
        raise VerificationError(f"{label}_timeout") from None


def wait_for(probe, error):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if result := probe():
            return result
        time.sleep(0.025)
    raise VerificationError(error)


def extract_commit(revision, destination):
    archive = subprocess.check_output(
        ["git", "archive", revision, "validation", "design"], cwd=ROOT, timeout=30,
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        source.extractall(destination, filter="data")


def prepare_scaffold(source, app, revision, archive):
    sys.path.insert(0, str(source / "validation/flutter/tool"))
    try:
        import ci

        flutter = json.loads(subprocess.check_output(["flutter", "--version", "--machine"],
                                                    cwd=source, timeout=30))
        if (flutter.get("frameworkVersion") != ci.VERSION
                or flutter.get("frameworkRevision") != ci.COMMIT):
            raise VerificationError("flutter_sdk_mismatch")
        def scaffold_command(args, cwd=None):
            checked([str(arg) for arg in args], cwd=cwd or source, work=app.parent,
                    label="flutter_scaffold")

        with (patch.dict(os.environ, {"GITHUB_SHA": revision}),
              patch.object(ci, "run", scaffold_command)):
            if archive is None:
                ci.prepare(app)
            else:
                # The standard scaffold validates the pinned archive SHA and
                # the upstream/patch file SHA values, even with a local cache.
                def open_cache(url, *, timeout):
                    if url != "https://pub.dev/api/archives/terminal_view-0.5.0.tar.gz":
                        raise VerificationError("unexpected_terminal_archive_url")
                    return archive.open("rb")

                with patch.object(ci.terminal_view_ime.urllib.request, "urlopen", open_cache):
                    ci.prepare(app)
        return flutter["frameworkVersion"]
    finally:
        sys.path.pop(0)


def port_ready(proc, port_file):
    if proc.poll() is not None:
        raise VerificationError("peer_exited")
    line = port_file.read_text().strip()
    if re.fullmatch(r"\d{1,5}", line) and 1 <= int(line) <= 65535:
        return int(line)
    return None


def read_audit(path):
    with path.open("rb") as stream:
        wire = stream.read(8193)
    if len(wire) > 8192:
        raise VerificationError("peer_audit_limit")
    return [json.loads(line) for line in wire.split(b"\n")[:-1]]


def evidence(audit, widget_stages):
    if widget_stages != STAGES:
        raise VerificationError("widget_stages")
    observed = [event["terminal"] for event in audit if event["kind"] == "observe"]
    if observed != TERMINALS:
        raise VerificationError("peer_observation_order")
    expected = [
        ["connection", "fixture_auth", "observe", "input", "receipt_dropped", "closed"],
        ["connection", "fixture_auth", "observe", "closed"],
        ["connection", "fixture_auth", "observe", "closed"],
    ]
    for connection, kinds in enumerate(expected, 1):
        if [event["kind"] for event in audit if event["connection"] == connection] != kinds:
            raise VerificationError("peer_connection_event_order")
    if len(audit) != sum(map(len, expected)):
        raise VerificationError("unexpected_peer_events")
    sent = next(event for event in audit if event["kind"] == "input")
    lost = next(event for event in audit if event["kind"] == "receipt_dropped")
    if (sent.get("exactFixtureInput") is not True or sent.get("size") != 6
            or not isinstance(sent.get("request"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", sent["request"])
            or sent["request"] != lost.get("request")):
        raise VerificationError("peer_input_receipt_mismatch")
    return dict(
        widgetStages=widget_stages, observedTargets=["A", "B", "A"],
        authenticatedSshConnections=3, confirmedSshClosures=3,
        recordedInputRequests=1, exactInputBytes=6, droppedReceipts=1,
        resolvedManuallyWithoutReplay=True,
    )


def run(revision, archive, offline):
    with tempfile.TemporaryDirectory(prefix="herdr-input-receipt-") as temp:
        work = Path(temp)
        source, app, exchange = (work / name for name in ("source", "app", "peer"))
        source.mkdir()
        exchange.mkdir(mode=0o700)
        extract_commit(revision, source)
        flutter_version = prepare_scaffold(source, app, revision, archive)
        args = ["flutter", "pub", "get", "--enforce-lockfile"]
        checked(args + (["--offline"] if offline else []), cwd=app, work=work, label="flutter_pub")
        transport = source / "validation/transport-rust"
        target = work / "cargo-target"
        env = {**os.environ, "CARGO_TARGET_DIR": str(target)}
        args = ["cargo", "build", "--locked", "--example", EXAMPLE]
        checked(args + (["--offline"] if offline else []), cwd=transport, work=work,
                label="build_peer", timeout=600, env=env)

        for name in ("host", "client"):
            checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(exchange / name)],
                    cwd=exchange, work=work, label=f"fixture_{name}_key")
        peer_args = [target / "debug/examples" / EXAMPLE, exchange / "host",
                     exchange / "client.pub", exchange / "peer.jsonl"]
        port_file = exchange / "port"
        with owned_process(peer_args, cwd=exchange, log=port_file) as peer:
            port = wait_for(lambda: port_ready(peer, port_file), "peer_start_timeout")
            stages_file = exchange / "ui-stages"
            try:
                checked(["flutter", "test", "--no-pub", "--reporter", "expanded", TEST],
                        cwd=app, work=work, label="flutter_widget",
                        env={**os.environ, "HERDR_INPUT_RECEIPT_FIXTURE": str(exchange)})
            except VerificationError as error:
                completed = stages_file.read_text().splitlines() if stages_file.exists() else []
                last = completed[-1] if completed and completed[-1] in STAGES else "start"
                raise VerificationError(f"{error}_after_{last}") from None

            def closed_audit():
                audit = read_audit(exchange / "peer.jsonl")
                return audit if sum(event["kind"] == "closed" for event in audit) >= 3 else None
            audit = wait_for(closed_audit, "peer_ssh_close_timeout")
            result = evidence(audit, stages_file.read_text().splitlines())
        if peer.poll() is None:
            raise VerificationError("peer_process_still_running")
        with socket.socket() as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise VerificationError("peer_listener_still_running")

    if work.exists():
        raise VerificationError("temporary_directory_removal")
    return {
        "test": "M3-05 Flutter input receipt recovery",
        "sourceSHA": revision, "flutterVersion": flutter_version,
        "hostPlatform": platform.system(), "status": "passed",
        "scope": "production Flutter app widgets and adapter; loopback TCP/SSH; synthetic herdr RPC and native journal IPC",
        **result, "cleanup": {"peerExited": True, "listenerClosed": True, "temporaryDirectoryRemoved": True},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD", help="Git commit to materialize")
    parser.add_argument("--terminal-archive", type=Path, help="cached pinned terminal_view 0.5.0 archive")
    parser.add_argument("--offline", action="store_true", help="use local package caches")
    parser.add_argument("--output", type=Path, help="write the sanitized report to a new file")
    args = parser.parse_args()
    if os.name != "posix" or sys.version_info < (3, 12):
        parser.error("a POSIX host and Python 3.12 or newer are required")
    if args.offline and args.terminal_archive is None:
        parser.error("--offline requires --terminal-archive")
    revision = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{args.revision}^{{commit}}"],
        cwd=ROOT, text=True, timeout=10,
    ).strip()
    try:
        result = run(revision, args.terminal_archive, args.offline)
        output = json.dumps(result, indent=2) + "\n"
        if args.output is None:
            print(output, end="")
        else:
            with args.output.open("x", encoding="utf-8") as report:
                report.write(output)
    except VerificationError as error:
        raise SystemExit(f"M3-05 verification failed: {error}") from None
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"M3-05 fixture setup or exchange failed: {type(error).__name__}") from None


if __name__ == "__main__":
    main()
