#!/usr/bin/env python3
"""Offline source reconstruction and optional locked Cargo graph verification."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ARCHIVE_SHA = "3bb77a4b259312b2abbc541bca1c13cb4e9b61c560a7fd894068c3b92e0c9dc3"
SOURCE = HERE / "russh-0.65.0"
ROOTS = ["validation/transport-rust", "validation/tauri/src-tauri", "validation/flutter-network-runtime"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hashes(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        assert not path.is_symlink(), f"unexpected source symlink: {path}"
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = sha(path.read_bytes())
    return result


def verify(archive=None, metadata=False):
    manifest = json.loads((HERE / "russh-0.65.0-source.json").read_text())
    assert manifest["schemaVersion"] == 1 and manifest["name"] == "russh" and manifest["version"] == "0.65.0"
    assert manifest["upstream"]["archiveSha256"] == ARCHIVE_SHA
    upstream_path = HERE / manifest["upstreamFiles"]["path"]
    assert sha(upstream_path.read_bytes()) == manifest["upstreamFiles"]["sha256"]
    upstream = json.loads(upstream_path.read_text())
    assert len(upstream) == manifest["upstreamFiles"]["count"] == 90
    for group in ["patch", "license", "notice"]:
        value = manifest[group]
        assert sha((HERE / value["path"]).read_bytes()) == value["sha256"], f"{group} hash mismatch"
    assert manifest["license"]["spdx"] == "Apache-2.0"
    license_text = (HERE / manifest["license"]["path"]).read_text()
    assert "Apache License" in license_text and "END OF TERMS AND CONDITIONS" in license_text
    baseline = tomllib.loads((REPO / "validation/ssh/Cargo.lock").read_text())
    registry = [p for p in baseline["package"] if p["name"] == "russh"]
    assert len(registry) == 1 and registry[0]["version"] == "0.65.0" and registry[0]["checksum"] == ARCHIVE_SHA
    patched = hashes(SOURCE)
    assert set(patched) == set(upstream), "missing or additional candidate source files"
    changed = {name for name in upstream if patched[name] != upstream[name]}
    assert changed == {"src/client/mod.rs"}, f"unexpected source changes: {changed}"
    assert len(manifest["patch"]["changedFiles"]) == 1
    entry = manifest["patch"]["changedFiles"][0]
    assert entry["path"] == "src/client/mod.rs"
    assert entry["beforeSha256"] == upstream[entry["path"]]
    assert entry["afterSha256"] == patched[entry["path"]]
    # Reverse the checked-in exact patch in a self-created copy. A matching
    # after-hash alone cannot hide additional edits from this full comparison.
    with tempfile.TemporaryDirectory(prefix="russh-source-check-") as temporary:
        copied = Path(temporary) / "candidate"
        shutil.copytree(SOURCE, copied)
        patch = str(HERE / manifest["patch"]["path"])
        subprocess.run(["git", "apply", "--reverse", "--check", patch], cwd=copied, check=True)
        subprocess.run(["git", "apply", "--reverse", patch], cwd=copied, check=True)
        assert hashes(copied) == upstream, "reverse patch did not recover every official source file"
    if archive:
        path = Path(archive)
        assert sha(path.read_bytes()) == ARCHIVE_SHA, "official archive checksum mismatch"
        members = {}
        with tarfile.open(path) as source:
            for member in source.getmembers():
                parts = Path(member.name).parts
                assert parts and parts[0] == "russh-0.65.0" and ".." not in parts and not Path(member.name).is_absolute()
                assert member.isdir() or member.isfile(), "unexpected archive link/device"
                if member.isfile():
                    members[Path(*parts[1:]).as_posix()] = sha(source.extractfile(member).read())
        assert members == upstream, "official archive member hashes differ"
    graphs = []
    if metadata:
        version = subprocess.check_output(["rustc", "-vV"], text=True)
        host = next(line.removeprefix("host: ") for line in version.splitlines() if line.startswith("host: "))
        for root in ROOTS:
            output = subprocess.check_output(["cargo", "metadata", "--locked", "--offline", "--format-version", "1", "--filter-platform", host, "--manifest-path", str(REPO / root / "Cargo.toml")], text=True)
            graph = json.loads(output)
            packages = [p for p in graph["packages"] if p["name"] == "russh"]
            assert len(packages) == 1 and packages[0]["version"] == "0.65.0", f"duplicate/missing russh: {root}"
            package = packages[0]
            assert package["source"] is None and Path(package["manifest_path"]).resolve() == SOURCE / "Cargo.toml", f"wrong candidate: {root}"
            graphs.append({"root": root, "russhCopies": 1, "version": "0.65.0", "source": "verified-local-candidate"})
    return {"officialSourceFilesRecovered": len(upstream), "modifiedFiles": sorted(changed), "archiveVerified": bool(archive), "cargoGraphs": graphs}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", help="optional official .crate path for independent archive verification")
    parser.add_argument("--metadata", action="store_true", help="also verify all three host Cargo resolution graphs")
    options = parser.parse_args()
    print(json.dumps(verify(options.archive, options.metadata), sort_keys=True))
