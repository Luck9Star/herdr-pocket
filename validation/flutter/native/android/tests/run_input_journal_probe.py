#!/usr/bin/env python3
"""Run real Kotlin journal/CAS on JVM; Android Context/Os are synthetic stubs."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--kotlin-dir", required=True, type=Path,
                    help="local Kotlin compiler jars and json-20250517.jar; no downloads")
args = parser.parse_args()
jar_dir = args.kotlin_dir.resolve()
jars = sorted(jar_dir.glob("*.jar"))
assert (jar_dir / "kotlin-stdlib-2.2.21.jar").is_file()
assert (jar_dir / "json-20250517.jar").is_file()
assert (jar_dir / "kotlin-compiler-embeddable-2.2.21.jar").is_file()
here = Path(__file__).resolve().parent
native = here.parent
with tempfile.TemporaryDirectory(prefix="herdr-kotlin-journal-probe-") as tmp:
    root = Path(tmp)
    sources = {
        "android/content/Context.java": """package android.content;
import java.io.File;
public class Context { private final File base; public Context() { this.base=new File(System.getProperty("java.io.tmpdir")); }
public Context(File base) { this.base=base; } public Context getApplicationContext() { return this; }
public File getNoBackupFilesDir() { return base; } }""",
        "android/content/Intent.java": "package android.content; public class Intent {}",
        "io/flutter/plugin/common/BinaryMessenger.java": "package io.flutter.plugin.common; public interface BinaryMessenger {}",
        "io/flutter/plugin/common/MethodCall.java": """package io.flutter.plugin.common;
public class MethodCall { public String method; public <T> T argument(String key) { return null; } }""",
        "io/flutter/plugin/common/MethodChannel.java": """package io.flutter.plugin.common;
public class MethodChannel { public MethodChannel(BinaryMessenger messenger,String name) {}
public interface Result { void success(Object x); void error(String c,String m,Object d); void notImplemented(); }
public interface Handler { void onMethodCall(MethodCall call,Result result); }
public void setMethodCallHandler(Handler handler) {} }""",
        "io/flutter/embedding/engine/FlutterEngine.java": """package io.flutter.embedding.engine;
import io.flutter.plugin.common.BinaryMessenger;
public class FlutterEngine { public DartExecutor getDartExecutor() { return new DartExecutor(); }
public static class DartExecutor { public BinaryMessenger getBinaryMessenger() { return null; } } }""",
        "io/flutter/embedding/android/FlutterActivity.java": """package io.flutter.embedding.android;
import android.content.Context; import android.content.Intent; import io.flutter.embedding.engine.FlutterEngine;
public class FlutterActivity extends Context { public void configureFlutterEngine(FlutterEngine engine) {}
public void runOnUiThread(Runnable task) { task.run(); }
protected void onActivityResult(int requestCode,int resultCode,Intent data) {} protected void onDestroy() {} }""",
        "dev/herdr/herdr_flutter_probe/PairScanChannel.java": """package dev.herdr.herdr_flutter_probe;
import io.flutter.plugin.common.BinaryMessenger; import android.content.Intent; import io.flutter.embedding.android.FlutterActivity;
public class PairScanChannel { public PairScanChannel(FlutterActivity a,BinaryMessenger b) {} public boolean handle(int x,int y,Intent i) { return false; } public void close() {} }""",
        "dev/herdr/herdr_flutter_probe/ConfigDocumentChannel.java": """package dev.herdr.herdr_flutter_probe;
import io.flutter.plugin.common.BinaryMessenger; import android.content.Intent; import io.flutter.embedding.android.FlutterActivity;
public class ConfigDocumentChannel { public ConfigDocumentChannel(FlutterActivity a,BinaryMessenger b) {} public boolean handle(int x,int y,Intent i) { return false; } public void close() {} }""",
        "dev/herdr/herdr_flutter_probe/NetworkIdentityChannel.java": """package dev.herdr.herdr_flutter_probe;
import io.flutter.plugin.common.BinaryMessenger; import io.flutter.embedding.android.FlutterActivity;
public class NetworkIdentityChannel { public NetworkIdentityChannel(FlutterActivity a,BinaryMessenger b) {} public void close() {} }""",
        "dev/herdr/pocket/NetworkRuntimeChannel.java": """package dev.herdr.pocket;
import io.flutter.plugin.common.BinaryMessenger; import io.flutter.embedding.android.FlutterActivity;
public class NetworkRuntimeChannel { public NetworkRuntimeChannel(FlutterActivity a,BinaryMessenger b) {} public void close() {} }""",
        "org/herdr/pairing/AndroidDeviceKeyStore.java": """package org.herdr.pairing;
import android.content.Context;
public class AndroidDeviceKeyStore { public AndroidDeviceKeyStore(Context context) {} public static class Created { public String getHandle() { return "fixture"; } }
public Created create() { return new Created(); } public String publicKey(String handle) { return ""; }
public byte[] sign(String handle,byte[] payload) { return payload; } public void delete(String handle) {} }""",
        "android/system/OsConstants.java": """package android.system;
public class OsConstants { public static final int O_RDONLY=0, O_NOFOLLOW=0, O_NONBLOCK=0;
public static boolean S_ISDIR(int mode) { return true; } }""",
        "android/system/Os.java": """package android.system;
import java.io.FileDescriptor;
public class Os { public static class Stat { public int st_mode=1; }
public static FileDescriptor open(String path,int flags,int mode) { return new FileDescriptor(); }
public static Stat fstat(FileDescriptor fd) { return new Stat(); }
public static void fsync(FileDescriptor fd) {} public static void close(FileDescriptor fd) {} }""",
    }
    for name, content in sources.items():
        path = root / "stubs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    classes = root / "classes"
    classes.mkdir()
    subprocess.run(["javac", "-d", str(classes), *[str(root / "stubs" / n) for n in sources]], check=True)
    out = root / "out"
    out.mkdir()
    compiler_cp = ":".join(map(str, jars))
    compile_cp = ":".join(map(str, [classes, *jars]))
    subprocess.run([
        "java", "-cp", compiler_cp, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect",
        "-classpath", compile_cp, "-d", str(out), str(native / "HostCatalogFile.kt"),
        str(native / "InputJournalFile.kt"), str(native / "MainActivity.kt"), str(here / "InputJournalProbe.kt"),
    ], check=True)
    run_cp = ":".join(map(str, [out, classes, jar_dir / "kotlin-stdlib-2.2.21.jar", jar_dir / "json-20250517.jar"]))
    subprocess.run(["java", "-cp", run_cp, "dev.herdr.herdr_flutter_probe.InputJournalProbe"], check=True)
