#!/usr/bin/env python3
"""Compare exact reconstructed upstream source with the local-close candidate.

Uses only temporary copies, fixed cached Cargo dependencies, self-created
loopback peers and temporary fixture keys. Never installs SDKs or edits registry.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
TEST = "controlled::tests::pause_resume_reuses_authenticated_ssh_and_other_connection_is_independent"


def run(manifest, log, target):
    environment = dict(os.environ, CARGO_TARGET_DIR=str(target))
    command = ["cargo", "test", "--locked", "--offline", "--manifest-path", str(manifest), TEST, "--", "--exact", "--nocapture"]
    result = subprocess.run(command, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
    log.write_text(result.stdout)
    return result.returncode, result.stdout


def main(options):
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("verified_russh", HERE / "verify-russh.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    checked = verifier.verify(options.archive)
    assert shutil.which("ssh-keygen"), "self-created fixture requires existing ssh-keygen"
    logs = Path(options.log_dir) if options.log_dir else Path(tempfile.mkdtemp(prefix="herdr-russh-close-logs-"))
    logs.mkdir(parents=True, exist_ok=True)
    target = Path(options.target_dir)
    with tempfile.TemporaryDirectory(prefix="herdr-russh-upstream-") as temporary:
        temporary = Path(temporary)
        upstream = temporary / "upstream"
        shutil.copytree(verifier.SOURCE, upstream)
        subprocess.run(["git", "apply", "--reverse", str(HERE / "russh-0.65.0-local-close.patch")], cwd=upstream, check=True)
        expected = json.loads((HERE / "russh-0.65.0-upstream-files.json").read_text())
        assert verifier.hashes(upstream) == expected
        package = temporary / "validation/transport-rust"
        package.mkdir(parents=True)
        shutil.copytree(REPO / "validation/transport-rust/src", package / "src")
        shutil.copyfile(REPO / "validation/transport-rust/Cargo.lock", package / "Cargo.lock")
        shared = package.parent / "shared"
        shared.mkdir()
        for name in ["dashboard-snapshot.json", "config-transfer-v1.json", "config-transfer-v2.json"]:
            shutil.copyfile(REPO / "validation/shared" / name, shared / name)
        manifest = (REPO / "validation/transport-rust/Cargo.toml").read_text()
        original = 'russh = { path = "../vendor/russh-0.65.0" }'
        assert manifest.count(original) == 1
        manifest = manifest.replace(original, "russh = { path = " + json.dumps(str(upstream)) + " }")
        original = 'path = "../overlay-runtime"'
        assert manifest.count(original) == 1
        manifest = manifest.replace(original, "path = " + json.dumps(str(REPO / "validation/overlay-runtime")))
        (package / "Cargo.toml").write_text(manifest)
        upstream_code, upstream_log = run(package / "Cargo.toml", logs / "upstream.log", target)
        assert upstream_code == 101 and "pause Err" in upstream_log and 'task Ok(Err("timeout"))' in upstream_log, "upstream result did not reproduce the expected local-close timeout; inspect log"
        candidate_code, candidate_log = run(REPO / "validation/transport-rust/Cargo.toml", logs / "candidate.log", target)
        assert candidate_code == 0 and "1 passed; 0 failed" in candidate_log, "candidate did not pass the same loopback test; inspect log"
    result = {
        "sourceFilesVerified": checked["officialSourceFilesRecovered"],
        "archiveVerified": checked["archiveVerified"],
        "test": TEST,
        "upstream": {"version": "0.65.0", "expectedFailureReproduced": True, "exitCode": upstream_code},
        "candidate": {"version": "0.65.0", "sameTestPassed": True, "exitCode": candidate_code},
        "logDirectory": str(logs),
        "scope": "self-created loopback SSH; no user credentials, authorization files, overlay nodes or device evidence",
    }
    if options.output:
        Path(options.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--log-dir")
    parser.add_argument("--target-dir", default=str(Path(tempfile.gettempdir()) / "herdr-transport-overlay-target"))
    parser.add_argument("--output")
    main(parser.parse_args())
