#!/usr/bin/env python3
"""Prepare fixed ZeroTier sources for offline checks; never run a network node.

Fetch downloads only the pinned public archives/patches into an explicit cache.
This tool installs no toolchains and does not consult ambient credentials. A fresh
work directory and a complete file inventory make partial preparation visible.
"""
import argparse
import hashlib
import json
import posixpath
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import urllib.request

NATIVE = Path(__file__).resolve().parents[1]
MANIFEST = NATIVE / "zerotier-runtime-source.json"
CANDIDATE = NATIVE / "zerotier-candidate.json"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 50000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("source must be a regular file without symbolic parents")
    return path


def checked_cache(cache, name, expected):
    path = regular(Path(cache) / name)
    if path.stat().st_size > MAX_ARCHIVE_BYTES or sha(path) != expected:
        raise ValueError("fixed source checksum/size mismatch: " + name)
    return path


def fetch(cache):
    manifest = json.loads(regular(MANIFEST).read_text())
    cache = Path(cache).absolute()
    if any(p.is_symlink() for p in (cache, *cache.parents)):
        raise ValueError("symbolic source cache")
    cache.mkdir(parents=True, exist_ok=True)
    reference = manifest["reference"]
    raw = "https://raw.githubusercontent.com/" + reference["repository"] + "/" + reference["commit"] + "/"
    items = [(s["name"] + ".tar.gz", "https://codeload.github.com/" + s["repository"] + "/tar.gz/" + s["commit"], s["sha256"], False)
             for s in manifest["sources"]]
    items += [(Path(p["path"]).name, raw + p["path"], p["sha256"], False) for p in manifest["upstreamPatches"]]
    items += [("sources.lock", raw + "sources.lock", reference["lockGitBlob"], True)]
    result = []
    for name, url, expected, git_blob in items:
        path = cache / name
        if path.exists() or path.is_symlink():
            regular(path)
            if path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("cached source too large")
            data = path.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("source download too large")
        actual = (hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                  if git_blob else hashlib.sha256(data).hexdigest())
        if actual != expected:
            raise ValueError("source download/cache checksum mismatch: " + name)
        if not path.exists():
            with path.open("xb") as output:
                output.write(data)
        result.append({"file": name, "bytes": len(data), "digest": actual})
    verify_lock(cache / "sources.lock", manifest)
    return {"cache": str(cache), "verifiedInputs": result, "nodeStarted": False}


def verify_lock(path, manifest):
    data = regular(path).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != manifest["reference"]["lockGitBlob"]:
        raise ValueError("reference sources.lock blob mismatch")
    values = dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"$', data.decode(), re.M))
    for source, prefix in zip(manifest["sources"], ("LIBZT", "ZEROTIERONE", "LWIP", "LWIP_CONTRIB"), strict=True):
        if values.get(prefix + "_COMMIT") != source["commit"]:
            raise ValueError("reference submodule commit mismatch")
        if values.get(prefix + "_REPO") != "https://github.com/" + source["repository"]:
            raise ValueError("reference repository mismatch")
    patches = " ".join(Path(item["path"]).name + ":" + item["sha256"] for item in manifest["upstreamPatches"])
    if values.get("ZEROTIER_PATCHES") != patches:
        raise ValueError("reference patches differ")


def archive_members(archive, expected_root):
    """Validate before extraction; materialize only internal regular-file links."""
    members = archive.getmembers()
    if len(members) > MAX_MEMBERS:
        raise ValueError("too many archive entries")
    seen, files, total = set(), set(), 0
    output = []
    for entry in members:
        raw = entry.name.rstrip("/")
        parts = raw.split("/")
        if not raw or any(part in {"", ".", ".."} for part in parts) or "\\" in raw:
            raise ValueError("unsafe archive path")
        if parts[0] != expected_root or raw in seen:
            raise ValueError("unexpected archive root or duplicate path")
        if not (entry.isdir() or entry.isfile() or entry.issym()):
            raise ValueError("archive hard links/devices are not allowed")
        seen.add(raw)
        if len(parts) == 1:
            if not entry.isdir():
                raise ValueError("archive root must be a directory")
            continue
        if any("/".join(parts[:i]) in files for i in range(1, len(parts))):
            raise ValueError("file used as a directory")
        if not entry.isdir():
            if any(old.startswith(raw + "/") for old in seen):
                raise ValueError("directory replaced by file")
            files.add(raw)
            if entry.size < 0:
                raise ValueError("negative archive size")
            total += entry.size
            if total > MAX_EXPANDED_BYTES:
                raise ValueError("expanded archive too large")
        output.append((entry, PurePosixPath(*parts[1:])))
    if not files:
        raise ValueError("empty source archive")
    by_name = {entry.name.rstrip("/"): entry for entry in members}
    for entry, _ in output:
        if not entry.issym():
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(entry.name), entry.linkname))
        source = by_name.get(target)
        if (entry.linkname.startswith("/") or "\\" in entry.linkname
                or not target.startswith(expected_root + "/")
                or source is None or not source.isfile()):
            raise ValueError("symbolic link must target a regular file inside the archive")
        total += source.size
        if total > MAX_EXPANDED_BYTES:
            raise ValueError("materialized archive too large")
    return output


def extract(archive_path, destination, expected_root):
    destination = Path(destination)
    links = []
    with tarfile.open(regular(archive_path), "r:gz") as archive:
        entries = archive_members(archive, expected_root)
        destination.mkdir(parents=True, exist_ok=True)
        for entry, relative in entries:
            target = destination / relative
            if entry.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                source = entry
                if entry.issym():
                    name = posixpath.normpath(posixpath.join(posixpath.dirname(entry.name), entry.linkname))
                    source = archive.getmember(name)
                    links.append({"path": relative.as_posix(), "target": entry.linkname,
                                  "treatment": "copied bytes from in-archive regular file"})
                target.parent.mkdir(parents=True, exist_ok=True)
                # x prevents an archive from replacing any previous source.
                with target.open("xb") as out, archive.extractfile(source) as inp:
                    shutil.copyfileobj(inp, out)
                target.chmod(0o755 if source.mode & 0o111 else 0o644)
    return links


def inventory(tree):
    records = []
    for path in sorted(Path(tree).rglob("*")):
        if path.is_symlink():
            raise ValueError("symbolic link in prepared source")
        if path.is_file():
            records.append({"path": path.relative_to(tree).as_posix(), "sha256": sha(path)})
    return records


def apply_patch(tree, patch, log):
    commands = []
    for args in (["git", "apply", "--check", str(patch)], ["git", "apply", str(patch)]):
        result = subprocess.run(args, cwd=tree, capture_output=True, text=True, timeout=60)
        commands.append({"argv": args, "exitCode": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        log.write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise ValueError("patch rejected; inspect " + str(log))


def prepare(work, cache, manifest_path=MANIFEST):
    manifest = json.loads(regular(manifest_path).read_text())
    cache = Path(cache).absolute()
    inputs = {}
    for source in manifest["sources"]:
        name = source["name"] + ".tar.gz"
        inputs[name] = checked_cache(cache, name, source["sha256"])
    for patch in manifest["upstreamPatches"]:
        name = Path(patch["path"]).name
        inputs[name] = checked_cache(cache, name, patch["sha256"])
    verify_lock(cache / "sources.lock", manifest)
    inputs["sources.lock"] = regular(cache / "sources.lock")
    work = Path(work).absolute()
    if any(p.is_symlink() for p in (work, *work.parents)) or work.exists():
        raise ValueError("refusing to overwrite or follow an existing work directory")
    work.mkdir(parents=True)
    materials = work / "materials"
    materials.mkdir()
    (work / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name, source in inputs.items():
        shutil.copy2(source, materials / name)
    tree = work / "libzt"
    links = []
    for source in manifest["sources"]:
        root = source["repository"].split("/")[-1] + "-" + source["commit"]
        for link in extract(materials / (source["name"] + ".tar.gz"), tree / source["destination"], root):
            links.append({"source": source["name"], **link})
    for i, patch in enumerate(manifest["upstreamPatches"]):
        apply_patch(tree, materials / Path(patch["path"]).name, work / ("patch-" + str(i + 1) + ".json"))
    record = {"schemaVersion": 1, "nodeStarted": False, "status": "prepared",
              "scope": "fixed upstream source plus four Heeler patches; no product candidate patches or build",
              "materializedLinks": links, "files": inventory(tree)}
    (work / "prepared-source.json").write_text(json.dumps(record, indent=2) + "\n")
    return {"work": str(work), "files": len(record["files"]), "nodeStarted": False}


def verify_materials(work):
    work = Path(work).absolute()
    manifest = json.loads(regular(work / "source-manifest.json").read_text())
    if manifest != json.loads(MANIFEST.read_text()):
        raise ValueError("source manifest changed")
    for source in manifest["sources"]:
        checked_cache(work / "materials", source["name"] + ".tar.gz", source["sha256"])
    for patch in manifest["upstreamPatches"]:
        checked_cache(work / "materials", Path(patch["path"]).name, patch["sha256"])
    verify_lock(work / "materials/sources.lock", manifest)
    return work


def verify(work):
    work = verify_materials(work)
    recorded = json.loads(regular(work / "prepared-source.json").read_text())
    if recorded["status"] != "prepared" or recorded["nodeStarted"] is not False or recorded["files"] != inventory(work / "libzt"):
        raise ValueError("prepared source inventory changed; rebuild in a fresh directory")
    return {"verifiedFiles": len(recorded["files"]), "nodeStarted": False}


def within(root, relative):
    parts = relative.split("/")
    if not parts or any(p in {"", ".", ".."} for p in parts) or "\\" in relative or ":" in relative:
        raise ValueError("unsafe candidate path")
    path = Path(root).absolute().joinpath(*parts)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symbolic candidate path")
    return path


def candidate_inputs():
    manifest = json.loads(regular(CANDIDATE).read_text())
    if manifest["baseManifestSha256"] != sha(MANIFEST):
        raise ValueError("candidate base changed")
    for entry in manifest["patches"] + manifest["copies"] + manifest["validationFiles"]:
        if sha(regular(within(NATIVE, entry["path"]))) != entry["sha256"]:
            raise ValueError("candidate input checksum mismatch: " + entry["path"])
    for entry in manifest["copies"]:
        within(NATIVE, entry["destination"])
    for path in manifest["beforeFiles"].keys() | manifest["afterFiles"].keys():
        within(NATIVE, path)
    return manifest


def apply_candidate(work):
    verify(work)
    manifest = candidate_inputs()
    work = Path(work).absolute()
    receipt = work / "candidate-source.json"
    if receipt.exists():
        raise ValueError("candidate already applied; use a fresh directory")
    tree = work / "libzt"
    before = {row["path"]: row["sha256"] for row in inventory(tree)}
    for path, expected in manifest["beforeFiles"].items():
        if before.get(path) != expected:
            raise ValueError("candidate original mismatch: " + path)
    for i, entry in enumerate(manifest["patches"]):
        apply_patch(tree, within(NATIVE, entry["path"]), work / ("candidate-patch-" + str(i + 1) + ".json"))
    for entry in manifest["copies"]:
        target = within(tree, entry["destination"])
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as out, regular(within(NATIVE, entry["path"])).open("rb") as inp:
            shutil.copyfileobj(inp, out)
    rows = inventory(tree)
    after = {row["path"]: row["sha256"] for row in rows}
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    if changed != set(manifest["afterFiles"]) or any(after.get(path) != value for path, value in manifest["afterFiles"].items()):
        raise ValueError("candidate changed unexpected files or bytes; retain this failed workspace")
    receipt.write_text(json.dumps({"schemaVersion": 1, "candidate": manifest,
                                  "nodeStarted": False, "files": rows}, indent=2) + "\n")
    return {"candidateFiles": len(changed), "verifiedFiles": len(rows), "nodeStarted": False}


def verify_candidate(work):
    work = verify_materials(work)
    manifest = candidate_inputs()
    record = json.loads(regular(work / "candidate-source.json").read_text())
    if record["candidate"] != manifest or record["nodeStarted"] is not False or record["files"] != inventory(work / "libzt"):
        raise ValueError("candidate source changed; prepare a fresh directory")
    return {"verifiedFiles": len(record["files"]), "nodeStarted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--cache", type=Path, required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    for name in ("verify", "apply", "verify-candidate"):
        p = sub.add_parser(name)
        p.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        result = fetch(args.cache)
    elif args.command == "prepare":
        result = prepare(args.work, args.cache)
    else:
        result = {"verify": verify, "apply": apply_candidate, "verify-candidate": verify_candidate}[args.command](args.work)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
