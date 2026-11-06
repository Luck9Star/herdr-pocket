#!/usr/bin/env python3
"""Prepare/build a pinned, explicit-auth tsnet candidate in a fresh directory.

Never starts a node. No ambient authentication is passed to child processes.
Uses an existing Go toolchain; no SDK or Go toolchain installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import time

NATIVE = Path(__file__).resolve().parents[1]
MODULE = NATIVE / "tailscale-runtime"
MANIFEST = NATIVE / "tailscale-runtime-source.json"
REPLACE = "\n// Prepared fixed-source candidate; only this owned copy is patched.\nreplace tailscale.com => ./upstream/tailscale\n"
RESERVED = {"upstream", "logs", "candidate-source.json", "module-sources.json"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_sources():
    source = json.loads(MANIFEST.read_text())
    for path, expected in [(MODULE / "go.mod", source["goModSha256"]),
                           (MODULE / "go.sum", source["goSumSha256"]),
                           (NATIVE / source["patch"]["path"], source["patch"]["sha256"]),
                           (NATIVE / source["patchTests"]["path"], source["patchTests"]["sha256"])]:
        if digest(path) != expected:
            raise ValueError("fixed source mismatch: " + str(path.relative_to(NATIVE)))
    return source


def environment(cache):
    go = shutil.which("go")
    if go is None:
        raise RuntimeError("existing Go toolchain required; this tool does not install one")
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    # Deliberately omit HOME, TS_*, cloud credentials, custom GOPROXY and Go env
    # files. All writable Go state remains in this explicitly supplied cache.
    path = os.pathsep.join(dict.fromkeys([str(Path(go).parent), *os.defpath.split(os.pathsep)]))
    return go, {"PATH": path, "GOTOOLCHAIN": "local", "GOENV": "off",
                "GOMODCACHE": str(cache / "modules"), "GOCACHE": str(cache / "build"),
                "GOPATH": str(cache / "gopath"), "GOPROXY": "https://proxy.golang.org",
                "GOSUMDB": "sum.golang.org", "CGO_ENABLED": "1", "GOFLAGS": "-mod=readonly"}


def run(args, cwd, env, log, timeout=1200):
    started = time.monotonic()
    with Path(log).open("w") as stream:
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    print(json.dumps({"command": list(map(str, args)), "exitCode": result.returncode,
                      "seconds": round(time.monotonic() - started, 2), "log": str(log)}), flush=True)
    if result.returncode:
        raise RuntimeError("command failed; inspect " + str(log))


def module_files():
    files = []
    for path in sorted(MODULE.rglob("*")):
        if path.is_symlink():
            raise ValueError("candidate module must not contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(MODULE)
        if relative.parts[0] in RESERVED:
            raise ValueError("reserved candidate path in source module")
        if path.suffix not in {".go", ".h", ".md"} and relative.as_posix() not in {"go.mod", "go.sum"}:
            raise ValueError("unexpected file in source module: " + relative.as_posix())
        files.append({"path": relative.as_posix(), "sha256": digest(path)})
    return files


def owned_source_path(work, name):
    relative = Path(name)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.parts[0] in RESERVED:
        raise ValueError("unsafe candidate source record")
    path = work
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("unsafe candidate source destination")
    return path


def verify_candidate(work, source):
    if json.loads((work / "candidate-source.json").read_text()) != source:
        raise ValueError("candidate metadata does not match current fixed sources")
    upstream = work / "upstream/tailscale"
    if digest(upstream / source["source"]["path"]) != source["source"]["patchedSha256"]:
        raise ValueError("candidate tsnet source changed")
    if digest(upstream / "tsnet/herdr_explicit_auth_test.go") != source["patchTests"]["sha256"]:
        raise ValueError("candidate patch tests changed")
    files = module_files()
    if json.loads((work / "module-sources.json").read_text()) != files:
        raise ValueError("source changed since candidate preparation; explicitly sync before testing")
    for item in files:
        target = owned_source_path(work, item["path"])
        expected = item["sha256"]
        if item["path"] == "go.mod":
            expected = hashlib.sha256((MODULE / "go.mod").read_bytes() + REPLACE.encode()).hexdigest()
        if digest(target) != expected:
            raise ValueError("candidate source changed: " + item["path"])


def sync_sources(work, source):
    work = Path(work).resolve()
    if json.loads((work / "candidate-source.json").read_text()) != source:
        raise ValueError("not an owned candidate for these fixed sources")
    files = module_files()
    record = work / "module-sources.json"
    previous = json.loads(record.read_text()) if record.exists() else []
    wanted = {item["path"] for item in files}
    # Validate the whole previous/new inventory before touching any destination.
    for item in previous + files:
        owned_source_path(work, item["path"])
    for item in previous:
        if item["path"] not in wanted:
            owned_source_path(work, item["path"]).unlink()
    for item in files:
        target = owned_source_path(work, item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MODULE / item["path"], target)
    with (work / "go.mod").open("a") as output:
        output.write(REPLACE)
    record.write_text(json.dumps(files, indent=2) + "\n")
    print(json.dumps({"syncedSourceFiles": len(files), "work": str(work)}), flush=True)


def prepare(work, cache):
    source = verify_sources()
    work = Path(work).absolute()
    if work.exists() or work.is_symlink():
        raise ValueError("refusing to overwrite an existing candidate directory")
    module_files()  # Reject symlinks/build output before copying anything.
    go, env = environment(cache)
    shutil.copytree(MODULE, work, ignore=shutil.ignore_patterns("*.dylib", "*.so", "*.dll", "__pycache__"))
    logs = work / "logs"
    logs.mkdir()
    run([go, "version"], work, env, logs / "go-version.log", 30)
    run([go, "mod", "download", "-json", "tailscale.com@" + source["tailscaleVersion"]],
        work, env, logs / "module-download.json")
    downloaded = json.loads((logs / "module-download.json").read_text())
    if downloaded.get("Error") or downloaded.get("Path") != "tailscale.com" or downloaded.get("Version") != source["tailscaleVersion"]:
        raise ValueError("module download did not match fixed version")
    sums = dict(line.rsplit(" ", 1) for line in (MODULE / "go.sum").read_text().splitlines())
    for suffix, key in [("", "Sum"), ("/go.mod", "GoModSum")]:
        if downloaded.get(key) != sums.get("tailscale.com " + source["tailscaleVersion"] + suffix):
            raise ValueError("downloaded module sum mismatch")
    for name, key in [("go.mod", "goModSha256"), ("go.sum", "goSumSha256")]:
        if digest(work / name) != source[key]:
            raise ValueError("download modified a fixed module lock")
    upstream = work / "upstream" / "tailscale"
    shutil.copytree(downloaded["Dir"], upstream)
    # Only the owned copy is writable; never patch the global module cache.
    for current, dirs, files in os.walk(upstream):
        Path(current).chmod(0o755)
        for name in files:
            path = Path(current) / name
            if not path.is_symlink():
                path.chmod(0o644)
    target = upstream / source["source"]["path"]
    if digest(target) != source["source"]["sha256"]:
        raise ValueError("fixed tsnet source mismatch")
    patch = NATIVE / source["patch"]["path"]
    run(["git", "apply", "--check", patch], upstream, env, logs / "patch-check.log", 30)
    run(["git", "apply", patch], upstream, env, logs / "patch-apply.log", 30)
    if digest(target) != source["source"]["patchedSha256"]:
        raise ValueError("patched tsnet source mismatch")
    shutil.copy2(NATIVE / source["patchTests"]["path"], upstream / "tsnet" / "herdr_explicit_auth_test.go")
    (work / "candidate-source.json").write_text(json.dumps(source, indent=2) + "\n")
    sync_sources(work, source)
    print(json.dumps({"prepared": str(work), "source": source["tailscaleCommit"],
                      "nodeStarted": False, "ambientCredentialsPassed": False}), flush=True)


def check_or_build(work, cache, build):
    source = verify_sources()
    work = Path(work).resolve()
    verify_candidate(work, source)
    go, env = environment(cache)
    logs = work / "logs"
    run([go, "test", "tailscale.com/tsnet", "-run", "^TestHerdr", "-count=1", "-v"],
        work, env, logs / "explicit-auth-test.log")
    run([go, "test", "-race", "-tags", "hp_ts_test", "./...", "-count=1", "-v"], work, env, logs / "runtime-tests.log")
    if build:
        suffix = {"Darwin": ".dylib", "Linux": ".so", "Windows": ".dll"}[platform.system()]
        library = work / ("libhp_tailscale" + suffix)
        run([go, "build", "-buildmode=c-shared", "-o", library, "."], work, env, logs / "shared-build.log")
        # Child process: reserve/status/retire without calling node_start.
        import sys
        run([sys.executable, NATIVE / "tool/check_tailscale_abi.py", library],
            work, env, logs / "shared-load.log", 30)
        print(json.dumps({"library": str(library), "sha256": digest(library), "nodeStarted": False}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "sync", "check", "build"])
    parser.add_argument("work", type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.work, args.cache)
    elif args.action == "sync":
        sync_sources(args.work, verify_sources())
    else:
        check_or_build(args.work, args.cache, args.action == "build")


if __name__ == "__main__":
    main()
