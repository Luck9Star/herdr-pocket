#!/usr/bin/env python3
"""Offline real Kotlin plugin compile + synthetic Android/Tauri behavior probe.
No Android SDK, native library, credential, identity, Activity or network is used.
"""
from pathlib import Path
import argparse, hashlib, json, subprocess, tempfile
parser=argparse.ArgumentParser();parser.add_argument('tools',type=Path);args=parser.parse_args()
repo=Path(__file__).resolve().parents[3]
manifest=repo/'validation/flutter/tool/kotlin-probe-tools.json'
jars=[]
for entry in json.loads(manifest.read_text()):
    path=args.tools/entry['file']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise SystemExit('tool hash mismatch: '+entry['file'])
    jars.append(path.resolve())
with tempfile.TemporaryDirectory(prefix='herdr-tauri-kotlin-') as temporary:
    root=Path(temporary)
    sources={
    'android/content/Context.java':'package android.content; public class Context {public Context getApplicationContext(){return this;} public java.io.File getNoBackupFilesDir(){return new java.io.File("/synthetic-unused");}}',
    'android/app/Activity.java':'package android.app; public class Activity extends android.content.Context {public int opens;public boolean finishing,destroyed;public boolean isFinishing(){return finishing;}public boolean isDestroyed(){return destroyed;}public void runOnUiThread(Runnable task){task.run();}public void startActivity(android.content.Intent intent){opens++;}}',
    'android/content/Intent.java':'package android.content; public class Intent {public static final String ACTION_VIEW="view";public Intent(String action,android.net.Uri uri){}}',
    'android/net/Uri.java':'package android.net;public class Uri {public static Uri parse(String value){return new Uri();}}',
    'android/os/Build.java':'package android.os;public class Build {public static class VERSION {public static int SDK_INT=35;}}',
    'android/webkit/WebView.java':'package android.webkit;public class WebView {}',
    'android/util/Base64.java':'package android.util;public class Base64 {public static final int NO_WRAP=2;public static byte[] decode(String s,int flags){return java.util.Base64.getDecoder().decode(s);}public static String encodeToString(byte[] b,int flags){return java.util.Base64.getEncoder().encodeToString(b);}}',
    'androidx/appcompat/app/AppCompatActivity.java':'package androidx.appcompat.app;public class AppCompatActivity extends android.app.Activity {}',
    'app/tauri/plugin/JSObject.java':'package app.tauri.plugin;public class JSObject extends java.util.HashMap<String,Object> {}',
    'app/tauri/plugin/Invoke.java':'''package app.tauri.plugin; public class Invoke {public final Object args;public app.tauri.plugin.JSObject result;public String error;private final java.util.concurrent.CountDownLatch done=new java.util.concurrent.CountDownLatch(1);public Invoke(Object args){this.args=args;}public <T>T parseArgs(Class<T> type){return type.cast(args);}public void resolve(JSObject value){result=value;done.countDown();}public void reject(String code){error=code;done.countDown();}public void await()throws Exception {if(!done.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new Exception("probe timeout");}}''',
    'app/tauri/plugin/Plugin.java':'package app.tauri.plugin;public class Plugin {public Plugin(android.app.Activity a){}public void load(android.webkit.WebView w){}public void onDestroy(androidx.appcompat.app.AppCompatActivity a){}}',
    'org/herdr/network/AndroidEasyTierConfig.java':'package org.herdr.network;public class AndroidEasyTierConfig {public static int binds;public static boolean bindNative(android.content.Context c){binds++;return false;}}',
    'org/herdr/network/AndroidTailscaleConfig.java':'package org.herdr.network;public class AndroidTailscaleConfig {public static int binds;public static boolean bindNative(android.content.Context c){binds++;return false;}}',
    'org/herdr/network/AndroidNetworkSecretStore.java':'''package org.herdr.network;public class AndroidNetworkSecretStore {public AndroidNetworkSecretStore(android.content.Context c){}public enum SecretMode {PRIVATE,PUBLIC_NO_SECRET}public static class Result {public String profileId,provider,handle,instanceId;public SecretMode mode;}public Result status(String p,String provider){return null;}public Result create(String p,String provider,SecretMode mode,byte[] b){return null;}public void delete(String p,String provider,String handle){}}''',
    'org/herdr/network/AndroidTailscaleStateStore.java':'''package org.herdr.network;public class AndroidTailscaleStateStore {public static int creates,deletes;public static final String HANDLE="11111111-1111-4111-8111-111111111111";public AndroidTailscaleStateStore(android.content.Context c){}public static class Result {public String profileId,provider="tailscale",handle=HANDLE,instanceId="22222222-2222-4222-8222-222222222222";public Result(String p){profileId=p;}}public Result status(String p){return new Result(p);}public Result create(String p){creates++;return new Result(p);}public void delete(String p,String h){if(!HANDLE.equals(h))throw new IllegalArgumentException();deletes++;}}''',
    'org/herdr/pairing/AndroidDeviceKeyStore.java':'package org.herdr.pairing;public class AndroidDeviceKeyStore {public static final int MAX_MESSAGE_BYTES=65536;public AndroidDeviceKeyStore(android.app.Activity a){}public static class Key {public String handle,publicKey;}public Key create(){return new Key();}public String publicKey(String h){return "";}public byte[] sign(String h,byte[] b){return new byte[64];}public void delete(String h){}}',
    }
    for name in ['Command','InvokeArg','TauriPlugin']:sources[f'app/tauri/annotation/{name}.java']=f'package app.tauri.annotation; public @interface {name} {{}}'
    for name,value in sources.items():
        p=root/'stubs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
    classes=root/'classes';classes.mkdir()
    subprocess.run(['javac','-d',str(classes),*[str(root/'stubs'/n) for n in sources]],check=True)
    out=root/'compiled';out.mkdir()
    subprocess.run(['java','-cp',':'.join(map(str,jars)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',':'.join(map(str,[classes,*jars])),'-d',str(out),str(repo/'validation/tauri/android/DeviceKeysPlugin.kt'),str(repo/'validation/tauri/android/NetworkAuthReview.kt'),str(Path(__file__).with_name('NetworkPluginProbe.kt'))],check=True)
    subprocess.run(['java','-cp',':'.join(map(str,[out,classes,*jars])),'org.herdr.pocket.NetworkPluginProbeKt'],check=True)
    print('Real Kotlin plugin + URL validator compiled; synthetic SDK/Tauri/store behavior probe passed. Not an Android SDK/device/JNI/keystore proof.')
