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
'android/app/Activity.java':'package android.app; public class Activity extends android.content.Context { public void runOnUiThread(Runnable task){ task.run(); } public void startActivity(android.content.Intent intent){} }',
'android/content/Intent.java':'package android.content; public class Intent { public static final String ACTION_VIEW="view"; public Intent(String action,android.net.Uri uri){} }',
'android/net/Uri.java':'package android.net; public class Uri { public static Uri parse(String text){return new Uri();} }',
'android/os/Build.java':'package android.os; public class Build { public static class VERSION { public static int SDK_INT=35; } }',
'io/flutter/plugin/common/BinaryMessenger.java':'package io.flutter.plugin.common; public interface BinaryMessenger {}',
'io/flutter/plugin/common/MethodCall.java':'package io.flutter.plugin.common; public class MethodCall { public String method; public Object arguments; public MethodCall(String m,Object a){method=m;arguments=a;} }',
'io/flutter/plugin/common/MethodChannel.java':'''package io.flutter.plugin.common; public class MethodChannel { private static final java.util.Map<String,MethodCallHandler> handlers=new java.util.concurrent.ConcurrentHashMap<>(); private final String name; public MethodChannel(BinaryMessenger messenger,String name){this.name=name;} public interface MethodCallHandler { void onMethodCall(MethodCall call, Result result); } public interface Result { void success(Object value); void error(String code,String message,Object details); void notImplemented(); } public void setMethodCallHandler(MethodCallHandler h){if(h==null)handlers.remove(name);else handlers.put(name,h);} public static void fire(String name, MethodCall call, Result result){handlers.get(name).onMethodCall(call,result);} }''',
'org/herdr/network/AndroidTailscaleConfig.java':'package org.herdr.network; public class AndroidTailscaleConfig { public static boolean bindNative(android.content.Context c){ return false; } }',
'org/herdr/network/AndroidTailscaleStateStore.java':'package org.herdr.network; public class AndroidTailscaleStateStore { public static int creates,deletes; public AndroidTailscaleStateStore(android.content.Context c){} public static class Result { public String profileId,provider="tailscale",handle="11111111-1111-4111-8111-111111111111",instanceId="22222222-2222-4222-8222-222222222222"; public Result(String p){profileId=p;} } public Result create(String profile){creates++;return new Result(profile);} public Result status(String profile){return new Result(profile);} public void delete(String profile,String handle){if(!handle.equals(new Result(profile).handle))throw new IllegalArgumentException();deletes++;} }',
'org/herdr/network/AndroidEasyTierConfig.java':'package org.herdr.network; public class AndroidEasyTierConfig { public static boolean bindNative(android.content.Context c){ return false; } }',
'org/herdr/network/AndroidNetworkSecretStore.java':'''package org.herdr.network; public class AndroidNetworkSecretStore { public AndroidNetworkSecretStore(android.content.Context c){} public enum SecretMode { PRIVATE,PUBLIC_NO_SECRET } public static class Result { public String profileId,provider,handle,instanceId; public SecretMode mode; } public Result status(String profile,String provider){return null;} public Result create(String profile,String provider,SecretMode mode,byte[] secret){return null;} public void delete(String profile,String provider,String handle){} }'''
}
for name,text in sources.items():
 p=root/'stubs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
classes=root/'stub-classes';classes.mkdir(exist_ok=True)
subprocess.run(['javac','-d',str(classes),*[str(root/'stubs'/n) for n in sources]],check=True)
cp=':'.join(map(str,[classes,*jars]));out=root/'compiled';out.mkdir(exist_ok=True)
source=Path(__file__).resolve().parents[1] / 'native/android/NetworkRuntimeChannel.kt'
subprocess.run(['java','-cp',':'.join(map(str,jars)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',cp,'-d',str(out),str(source),str(source.with_name('NetworkIdentityChannel.kt')),str(source.parent / 'tests/NetworkLoginGateProbe.kt'),str(source.parent / 'tests/NetworkIdentityProbe.kt')],check=True)
result=subprocess.check_output(['javap','-classpath',str(out),'-p','dev.herdr.pocket.NetworkRuntimeChannel'],text=True)
for signature in ['public static final native long nativeCreateScope();','public static final native java.lang.String nativeReserveOpen(long, java.lang.String);','public static final native java.lang.Object[] nativeCall(long, java.lang.String, java.lang.String, byte[]);','public static final native java.lang.String nativeCloseScope(long);']:
 assert signature in result,signature
subprocess.run(['java','-cp',':'.join(map(str,[out,*jars])),'dev.herdr.pocket.NetworkLoginGateProbeKt'],check=True)
subprocess.run(['java','-cp',':'.join(map(str,[out,classes,*jars])),'dev.herdr.herdr_flutter_probe.NetworkIdentityProbeKt'],check=True)
print('Kotlin 2.2.21 JVM compile with synthetic Android/Flutter stubs passed; 4 exact JNI static signatures confirmed (not Android SDK/device).')
temporary.cleanup()
