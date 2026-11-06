#!/usr/bin/env python3
"""Compile real Swift journal/CAS with channel/error stubs; run temp-file probes."""
from pathlib import Path
import subprocess
import tempfile

here = Path(__file__).resolve().parent
native = here.parent
with tempfile.TemporaryDirectory(prefix="herdr-swift-journal-probe-") as tmp:
    root = Path(tmp)
    stub = root / "DeviceKeyError.swift"
    stub.write_text("import Foundation\nenum DeviceKeyError: Error { case invalidHandle }\n", encoding="utf-8")
    executable = root / "input-journal-probe"
    subprocess.run([
        "swiftc", "-module-cache-path", str(root / "module-cache"),
        str(here / "FlutterChannelStubs.swift"), str(stub),
        str(native / "HostCatalogFile.swift"), str(native / "InputJournalFile.swift"),
        str(here / "InputJournalProbe.swift"), "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
    host_executable = root / "host-catalog-probe"
    subprocess.run([
        "swiftc", "-module-cache-path", str(root / "module-cache"),
        str(here / "FlutterChannelStubs.swift"), str(stub),
        str(native / "HostCatalogFile.swift"), str(here / "HostCatalogProbe.swift"),
        "-o", str(host_executable),
    ], check=True)
    subprocess.run([str(host_executable)], check=True)
