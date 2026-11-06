#!/usr/bin/env python3
"""Offline signature/compile probe. Never installs SDKs or loads an overlay library."""
from pathlib import Path
import subprocess, json, argparse, hashlib, tempfile
parser = argparse.ArgumentParser(description="Compile the real channel against synthetic JVM stubs; not Android SDK validation")
parser.add_argument('tools', type=Path, help='directory containing jars from kotlin-probe-tools.json')
args = parser.parse_args()
manifest = Path(__file__).with_name('kotlin-probe-tools.json')
jars = []
for entry in json.loads(manifest.read_text()):
    jar = args.tools / entry['file']
    if hashlib.sha256(jar.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit('tool hash mismatch: ' + entry['file'])
    jars.append(jar.resolve())
temporary = tempfile.TemporaryDirectory(prefix='herdr-kotlin-probe-')
root = Path(temporary.name)
sources={
'android/content/Context.java':'package android.content; public class Context { public Context getApplicationContext(){return this;} }',
'android/app/Activity.java':'package android.app; public class Activity extends android.content.Context { public void runOnUiThread(Runnable task){ task.run(); } }',
'android/os/Build.java':'package android.os; public class Build { public static class VERSION { public static int SDK_INT=35; } }',
'io/flutter/plugin/common/BinaryMessenger.java':'package io.flutter.plugin.common; public interface BinaryMessenger {}',
'io/flutter/plugin/common/MethodCall.java':'package io.flutter.plugin.common; public class MethodCall { public String method; public Object arguments; }',
'io/flutter/plugin/common/MethodChannel.java':'''package io.flutter.plugin.common; public class MethodChannel { public MethodChannel(BinaryMessenger messenger,String name){} public interface MethodCallHandler { void onMethodCall(MethodCall call, Result result); } public interface Result { void success(Object value); void error(String code,String message,Object details); void notImplemented(); } public void setMethodCallHandler(MethodCallHandler h){} }''',
'org/herdr/network/AndroidEasyTierConfig.java':'package org.herdr.network; public class AndroidEasyTierConfig { public static boolean bindNative(android.content.Context c){ return false; } }',
'org/herdr/network/AndroidNetworkSecretStore.java':'''package org.herdr.network; public class AndroidNetworkSecretStore { public AndroidNetworkSecretStore(android.content.Context c){} public enum SecretMode { PRIVATE,PUBLIC_NO_SECRET } public static class Result { public String handle; public SecretMode mode; } public Result status(String profile,String provider){return null;} }'''
}
for name,text in sources.items():
 p=root/'stubs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
classes=root/'stub-classes';classes.mkdir(exist_ok=True)
subprocess.run(['javac','-d',str(classes),*[str(root/'stubs'/n) for n in sources]],check=True)
cp=':'.join(map(str,[classes,*jars]));out=root/'compiled';out.mkdir(exist_ok=True)
source=Path(__file__).resolve().parents[1] / 'native/android/NetworkRuntimeChannel.kt'
subprocess.run(['java','-cp',':'.join(map(str,jars)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',cp,'-d',str(out),str(source)],check=True)
result=subprocess.check_output(['javap','-classpath',str(out),'-p','dev.herdr.pocket.NetworkRuntimeChannel'],text=True)
for signature in ['public static final native long nativeCreateScope();','public static final native java.lang.String nativeReserveOpen(long, java.lang.String);','public static final native java.lang.Object[] nativeCall(long, java.lang.String, java.lang.String, byte[]);','public static final native java.lang.String nativeCloseScope(long);']:
 assert signature in result,signature
print('Kotlin 2.2.21 JVM compile with synthetic Android/Flutter stubs passed; 4 exact JNI static signatures confirmed (not Android SDK/device).')
temporary.cleanup()
