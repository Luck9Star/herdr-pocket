#!/usr/bin/env python3
"""Build and probe the pinned ZeroTier candidate on Darwin arm64 only.

This is a local source build, not an upstream or product build. It mirrors the
fixed libzt CMake source globs and compile definitions without installing or
invoking CMake. All results are written to a fresh directory outside the source
tree, with per-translation-unit commands, source digests, and complete logs.
The native probe never starts a ZeroTier node or opens a network socket.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

EXPECTED_CMAKE_SHA256 = "bf7b5801d4a715689a75014f92f317a2ec27d955e801bd856e3d2fde12306602"
MAX_JOBS = 4


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_candidate_verifier():
    verifier_path = Path(__file__).with_name("zerotier_candidate.py").resolve()
    spec = importlib.util.spec_from_file_location("zerotier_candidate", verifier_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the existing ZeroTier candidate verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_candidate


def safe_directory(path, label, must_not_exist=False):
    path = Path(path).expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError(label + " path contains a symbolic link")
    if must_not_exist and path.exists():
        raise ValueError(label + " directory already exists; refusing overwrite")
    return path


def inside(path, root):
    try:
        Path(path).relative_to(Path(root))
        return True
    except ValueError:
        return False


def append_json_line(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def environment_for(output):
    # Deliberately do not inherit HOME, proxy settings, signing variables,
    # SDK credentials, or other ambient environment state.
    path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    return {"PATH": path, "TMPDIR": str(output / "tmp")}


def gather_sources(source):
    zto = source / "ext/ZeroTierOne"
    lwip = source / "ext/lwip/src"
    port = source / "ext/lwip-contrib/ports/unix/port"
    libzt = source / "src"
    natpmp = [zto / "ext/libnatpmp/natpmp.c",
              zto / "ext/libnatpmp/getgateway.c"]
    mini_names = [
        "connecthostport.c", "igd_desc_parse.c", "minisoap.c", "minissdpc.c",
        "miniupnpc.c", "miniwget.c", "minixml.c", "portlistingparse.c",
        "receivedata.c", "upnpcommands.c", "upnpdev.c", "upnperrors.c",
        "upnpreplyparse.c",
    ]
    groups = {
        "ztcore": sorted((zto / "node").glob("*.cpp")) + [
            zto / "osdep/OSUtils.cpp", zto / "osdep/PortMapper.cpp"],
        "natpmp": natpmp,
        "miniupnpc": [zto / "ext/miniupnpc" / name for name in mini_names],
        "lwip": sorted((lwip / "netif").glob("*.c"))
                + sorted((lwip / "api").glob("*.c"))
                + [port / "sys_arch.c"]
                + sorted((lwip / "core").glob("*.c"))
                + sorted((lwip / "core/ipv4").glob("*.c"))
                + sorted((lwip / "core/ipv6").glob("*.c")),
        "libzt": sorted(libzt.glob("*.cpp")),
    }
    groups["lwip"] = [p for p in groups["lwip"] if p.name != "slipif.c"]
    for group, paths in groups.items():
        if not paths or any(not p.is_file() or p.is_symlink() for p in paths):
            missing = [str(p) for p in paths if not p.is_file() or p.is_symlink()]
            raise ValueError("CMake source glob is empty or has missing files in "
                             + group + (": " + ", ".join(missing) if missing else ""))
    # CMake's non-Windows libnatpmp glob removes wingettimeofday.c.
    if any(p.name == "wingettimeofday.c" for p in groups["natpmp"]):
        raise AssertionError("Darwin natpmp source selection unexpectedly includes wingettimeofday.c")
    return groups


def includes(source):
    return [
        source / "ext/ZeroTierOne",
        source / "ext/ZeroTierOne/include",
        source / "ext/ZeroTierOne/node",
        source / "ext/ZeroTierOne/osdep",
        source / "ext/ZeroTierOne/ext/libnatpmp",
        source / "ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/core/include",
        source / "ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/simpleapi/include",
        source / "src",
        source / "include",
        source / "ext/concurrentqueue",
        source / "ext/lwip/src/include",
        source / "ext/lwip-contrib/ports/unix/port/include",
    ]


def common_flags(compiler_kind, include_dirs):
    flags = ["-fPIC", "-fstack-protector", "-fsanitize=address,undefined",
             "-fno-omit-frame-pointer"]
    for path in include_dirs:
        flags += ["-I", str(path)]
    # CMake appends ZT_FLAGS to the global C/C++ flags, so these apply to every
    # source group, in addition to each target's group-specific options.
    flags += ["-DZT_SDK=1", "-DZT_USE_MINIUPNPC=1",
              "-D_USING_LWIP_DEFINITIONS_=0", "-DOMIT_JSON_SUPPORT=1",
              "-Wno-unused-parameter"]
    if compiler_kind == "cxx":
        flags += ["-std=c++11", "-Wall", "-Wextra", "-DZTS_DISABLE_CENTRAL_API=1",
                  "-DZTS_C_API_ONLY=1"]
    return flags


def group_flags(group):
    if group in {"ztcore", "libzt"}:
        return []
    if group == "natpmp":
        return ["-DNATPMP_EXPORTS"]
    if group == "lwip":
        return ["-DLWIP_DBG_TYPES_ON=0",
                "-Wno-tautological-constant-out-of-range-compare",
                "-Wno-parentheses-equality"]
    if group == "miniupnpc":
        return ["-DMACOSX", "-DZT_USE_MINIUPNPC", "-DMINIUPNP_STATICLIB",
                "-D_DARWIN_C_SOURCE", "-DMINIUPNPC_SET_SOCKET_TIMEOUT",
                "-DMINIUPNPC_GET_SRC_ADDR", "-D_BSD_SOURCE", "-D_DEFAULT_SOURCE",
                '-DMINIUPNPC_VERSION_STRING="2.0"',
                '-DUPNP_VERSION_STRING="UPnP/1.1"', "-DENABLE_STRNATPMPERR",
                '-DOS_STRING="Darwin/15.0.0"']
    raise ValueError("unknown CMake source group: " + group)


def run_process(argv, cwd, env):
    return subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=False)


def compile_one(source, group, output, include_dirs, clang, clangxx, env):
    source_hash = sha(source)
    label = group + "-" + hashlib.sha256(str(source).encode()).hexdigest()[:16]
    obj = output / "objects" / (label + ".o")
    obj.parent.mkdir(parents=True, exist_ok=True)
    kind = "cxx" if source.suffix == ".cpp" else "c"
    compiler = clangxx if kind == "cxx" else clang
    argv = [str(compiler)] + common_flags(kind, include_dirs) + group_flags(group)
    argv += ["-c", str(source), "-o", str(obj)]
    started = time.time()
    result = run_process(argv, output, env)
    elapsed = round(time.time() - started, 3)
    log_path = output / "logs" / (label + ".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout, encoding="utf-8")
    return {"source": str(source), "sourceSha256": source_hash, "group": group,
            "compiler": str(compiler), "argv": argv, "exitCode": result.returncode,
            "seconds": elapsed, "object": str(obj) if result.returncode == 0 else None,
            "log": str(log_path)}, obj if result.returncode == 0 else None


def compile_all(groups, output, source, clang, clangxx, env):
    include_dirs = includes(source)
    results = []
    jobs = [(group, path) for group, paths in groups.items() for path in paths]
    with ThreadPoolExecutor(max_workers=MAX_JOBS) as executor:
        futures = [executor.submit(compile_one, path, group, output, include_dirs,
                                   clang, clangxx, env) for group, path in jobs]
        for future in as_completed(futures):
            record, obj = future.result()
            append_json_line(output / "translation-units.jsonl", record)
            results.append((record, obj))
    results.sort(key=lambda item: (item[0]["group"], item[0]["source"]))
    failures = [record for record, _ in results if record["exitCode"]]
    return [obj for _, obj in results if obj is not None], [record for record, _ in results], failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path,
                        help="verified ZeroTier candidate work directory")
    parser.add_argument("--output", required=True, type=Path,
                        help="fresh output directory outside the candidate source tree")
    args = parser.parse_args()
    verify_candidate = load_candidate_verifier()
    work = safe_directory(args.work, "work")
    output = safe_directory(args.output, "output", must_not_exist=True)
    source = work / "libzt"
    if not source.is_dir() or inside(output, source) or output == source:
        parser.error("--output must be fresh and outside --work/libzt")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("this builder supports only the host Darwin arm64 machine")
    for binary in ("clang", "clang++"):
        if shutil.which(binary) is None:
            parser.error("required existing compiler is unavailable: " + binary)

    output.mkdir(parents=True)
    (output / "logs").mkdir()
    (output / "tmp").mkdir()
    env = environment_for(output)
    for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS"):
        env[key] = "halt_on_error=1:abort_on_error=1:print_stacktrace=1"
    summary = {
        "schemaVersion": 1,
        "status": "running",
        "scope": "local Darwin arm64 build of pinned libzt CMake sources; not official upstream/product build",
        "nodeStarted": False,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "work": str(work),
        "source": str(source),
        "output": str(output),
        "cmakeSha256": None,
        "candidateVerifyBefore": None,
        "candidateVerifyAfter": None,
        "sourceGlobs": {},
        "translationUnits": [],
        "library": None,
        "probe": None,
        "failure": None,
    }
    summary_path = output / "build-report.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    exit_code = 1
    try:
        summary["candidateVerifyBefore"] = verify_candidate(work)
        cmake_file = source / "CMakeLists.txt"
        summary["cmakeSha256"] = sha(cmake_file)
        if summary["cmakeSha256"] != EXPECTED_CMAKE_SHA256:
            raise ValueError("fixed CMakeLists.txt SHA-256 mismatch")
        required_candidate = [source / "src/hp_zt_manager.cpp",
                              source / "src/hp_zt_manager.h",
                              source / "src/hp_zt.h",
                              source / "src/hp_zt_lifecycle.cpp"]
        absent = [str(path) for path in required_candidate if not path.is_file()]
        if absent:
            raise ValueError("candidate manager/lifecycle copy missing: " + ", ".join(absent))
        groups = gather_sources(source)
        summary["sourceGlobs"] = {
            group: [{"path": str(path), "sha256": sha(path)} for path in paths]
            for group, paths in groups.items()
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        clang = Path(shutil.which("clang")).resolve()
        clangxx = Path(shutil.which("clang++")).resolve()
        objects, records, failures = compile_all(groups, output, source,
                                                clang, clangxx, env)
        summary["translationUnits"] = records
        summary["translationUnitCount"] = len(records)
        summary["translationUnitFailures"] = len(failures)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if failures:
            raise RuntimeError("translation-unit compilation failed; inspect per-TU logs")
        library = output / "libhp_zerotier.dylib"
        link_argv = [str(clangxx), "-dynamiclib", "-fsanitize=address,undefined",
                     "-fno-omit-frame-pointer", "-fstack-protector", "-pthread",
                     "-o", str(library)] + [str(obj) for obj in objects]
        link = run_process(link_argv, output, env)
        (output / "logs/link.log").write_text(link.stdout, encoding="utf-8")
        summary["link"] = {"argv": link_argv, "exitCode": link.returncode,
                           "log": str(output / "logs/link.log")}
        if link.returncode:
            raise RuntimeError("shared library link failed; inspect logs/link.log")
        summary["library"] = {"path": str(library), "bytes": library.stat().st_size,
                              "sha256": sha(library)}

        probe_source = Path(__file__).resolve().parents[1] / "zerotier-runtime/tests/library_probe.cpp"
        if not probe_source.is_file():
            raise ValueError("native probe source is missing: " + str(probe_source))
        probe = output / "library-probe"
        probe_argv = [str(clangxx), "-std=c++11", "-Wall", "-Wextra", "-Werror",
                      "-O1", "-g", "-fsanitize=address,undefined",
                      "-fno-omit-frame-pointer", "-I", str(source / "src"),
                      "-I", str(Path(__file__).resolve().parents[1] / "zerotier-runtime"),
                      "-I", str(source / "include"), str(probe_source),
                      "-L", str(output), "-lhp_zerotier", "-pthread",
                      "-Wl,-rpath," + str(output), "-o", str(probe)]
        probe_compile = run_process(probe_argv, output, env)
        (output / "logs/probe-compile.log").write_text(probe_compile.stdout, encoding="utf-8")
        summary["probeCompile"] = {"argv": probe_argv, "exitCode": probe_compile.returncode,
                                   "log": str(output / "logs/probe-compile.log")}
        if probe_compile.returncode:
            raise RuntimeError("native probe compile failed; inspect logs/probe-compile.log")
        run = run_process([str(probe)], output, env)
        # A regression may put a temporary private arithmetic operand into a
        # sanitizer diagnostic. Preserve its location and failure, not operands.
        probe_output = re.sub(r"runtime error:.*", "runtime error: [operands redacted]", run.stdout)
        (output / "logs/probe-run.log").write_text(probe_output, encoding="utf-8")
        summary["probe"] = {"argv": [str(probe)], "exitCode": run.returncode,
                            "log": str(output / "logs/probe-run.log"),
                            "nodeStarted": False}
        if run.returncode:
            raise RuntimeError("native library probe failed; inspect logs/probe-run.log")
        summary["status"] = "passed"
        exit_code = 0
    except Exception as error:
        summary["status"] = "failed"
        summary["failure"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            summary["candidateVerifyAfter"] = verify_candidate(work)
        except Exception as error:
            summary["candidateVerifyAfter"] = {"error": type(error).__name__,
                                               "message": str(error)}
            summary["status"] = "failed"
            summary["failure"] = summary["failure"] or {
                "type": type(error).__name__, "message": "candidate verification failed after build"}
            exit_code = 1
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "report": str(summary_path),
                      "nodeStarted": False}, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
