#!/usr/bin/env python3
"""Offline Kotlin channel/CAS fixture; synthetic Android/Flutter/service, no SDK/JNI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--kotlin-dir', required=True, type=Path)
args = parser.parse_args()
native = Path(__file__).resolve().parent.parent
manifest = native.parents[1] / 'tool/kotlin-probe-tools.json'
jars = []
for record in json.loads(manifest.read_text()):
    path = args.kotlin_dir / record['file']
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise SystemExit('Tool checksum mismatch: ' + record['file'])
    jars.append(path.resolve())
sources = {
    'android/content/Context.java': '''package android.content; import java.io.File;
public class Context { private final File root; public Context(File root){this.root=root;}
public Context getApplicationContext(){return this;} public File getNoBackupFilesDir(){return root;} }''',
    'android/app/Activity.java': '''package android.app; import java.io.File;
public class Activity extends android.content.Context { public Activity(File root){super(root);}
private final java.util.concurrent.ExecutorService ui=java.util.concurrent.Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"fixture-ui");t.setDaemon(true);return t;});
public void runOnUiThread(Runnable r){ui.execute(r);} }''',
    'android/system/OsConstants.java': '''package android.system; public class OsConstants {
public static final int O_RDONLY=0,O_NOFOLLOW=0,O_NONBLOCK=0; public static boolean S_ISDIR(int mode){return true;} }''',
    'android/system/Os.java': '''package android.system; import java.io.FileDescriptor;
public class Os { public static class Stat {public int st_mode=1;} public static FileDescriptor open(String p,int f,int m){return new FileDescriptor();}
public static Stat fstat(FileDescriptor f){return new Stat();} public static void fsync(FileDescriptor f){} public static void close(FileDescriptor f){} }''',
    'io/flutter/plugin/common/BinaryMessenger.java': 'package io.flutter.plugin.common; public interface BinaryMessenger {}',
    'io/flutter/plugin/common/MethodCall.java': '''package io.flutter.plugin.common; public class MethodCall {
public final String method; public final Object arguments; public MethodCall(String method,Object arguments){this.method=method;this.arguments=arguments;} }''',
    'io/flutter/plugin/common/MethodChannel.java': '''package io.flutter.plugin.common; public class MethodChannel {
private static final java.util.Map<String,MethodCallHandler> handlers=new java.util.concurrent.ConcurrentHashMap<>(); private final String name;
public MethodChannel(BinaryMessenger messenger,String name){this.name=name;} public interface MethodCallHandler {void onMethodCall(MethodCall c,Result r);}
public interface Result {void success(Object v);void error(String c,String m,Object d);void notImplemented();}
public void setMethodCallHandler(MethodCallHandler h){if(h==null)handlers.remove(name);else handlers.put(name,h);}
public static void fire(String name,MethodCall c,Result r){handlers.get(name).onMethodCall(c,r);} }''',
    'org/herdr/network/AndroidZeroTierDeviceService.java': '''package org.herdr.network; import java.util.*; import java.util.concurrent.*;
public class AndroidZeroTierDeviceService { public static volatile boolean available,recoverWrongHandle; public static volatile int writes; public static volatile String threadName,pendingPhase,pendingHandle;
public static volatile CountDownLatch entered=new CountDownLatch(0),release=new CountDownLatch(0);
private static void waitForFixture() throws Exception {threadName=Thread.currentThread().getName();entered.countDown();if(!release.await(5,TimeUnit.SECONDS))throw new Exception("fixture wait");}
public static Map<String,Object> status() throws Exception {waitForFixture();Map<String,Object> v=new HashMap<>();v.put("available",available);v.put("device",null);v.put("pendingCreation",null);v.put("pendingDeletion",null);return v;}
public static Map<String,String> write(String action,String handle,String instanceId,String expectedPhase) throws Exception {waitForFixture();if(!available)throw new Exception("unavailable");
if(action.equals("create")||action.equals("forget")){if(expectedPhase!=null)throw new Exception("phase");}
else if(!Objects.equals(pendingPhase,expectedPhase)||!Objects.equals(pendingHandle,handle)||instanceId!=null)throw new Exception("pending changed");writes++;
if(action.equals("create")||action.equals("recoverPendingCreation")){Map<String,String> v=new HashMap<>();v.put("handle",action.equals("recoverPendingCreation")&&recoverWrongHandle?"c0000000-0000-4000-8000-000000000003":"a0000000-0000-4000-8000-000000000001");v.put("instanceId","b0000000-0000-4000-8000-000000000002");return v;}return null;} }''',
}
with tempfile.TemporaryDirectory(prefix='herdr-kotlin-zt-device-') as tmp:
    root = Path(tmp)
    paths = []
    for name, content in sources.items():
        path = root / 'stubs' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        paths.append(path)
    classes = root / 'classes'
    classes.mkdir()
    subprocess.run(['javac', '-d', str(classes), *map(str, paths)], check=True)
    cp = ':'.join(map(str, [classes, *jars]))
    out = root / 'out'
    out.mkdir()
    subprocess.run(['java', '-cp', ':'.join(map(str, jars)), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                    '-no-stdlib', '-no-reflect', '-classpath', cp, '-d', str(out),
                    str(native / 'HostCatalogFile.kt'), str(native / 'ZeroTierDeviceChannel.kt'),
                    str(native / 'tests/ZeroTierDeviceProbe.kt')], check=True)
    subprocess.run(['java', '-cp', ':'.join(map(str, [out, classes, *jars])),
                    'dev.herdr.herdr_flutter_probe.ZeroTierDeviceProbeKt'], check=True)
