#!/usr/bin/env python3
"""Compile actual Kotlin reader against isolated SDK/Tauri stubs; never read a host clip."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('tools', type=Path, help='Existing pinned Kotlin probe compiler jars')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
jars = []
for entry in json.loads((repo / 'validation/flutter/tool/kotlin-probe-tools.json').read_text()):
    path = args.tools / entry['file']
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit('tool hash mismatch: ' + entry['file'])
    jars.append(path.resolve())

sources = {
    'android/content/Context.java': 'package android.content; public class Context {public static final String CLIPBOARD_SERVICE="clipboard";public Object service;public Object getSystemService(String key){return service;}}',
    'android/app/Activity.java': 'package android.app; public class Activity extends android.content.Context {public boolean focus=true,finishing,destroyed;public boolean hasWindowFocus(){return focus;}public boolean isFinishing(){return finishing;}public boolean isDestroyed(){return destroyed;}public void runOnUiThread(Runnable task){task.run();}}',
    'android/content/ClipDescription.java': 'package android.content;public class ClipDescription {private final String[] types;public ClipDescription(String[] types){this.types=types;}public boolean hasMimeType(String type){for(String t:types)if(t.equals(type))return true;return false;}public int getMimeTypeCount(){return types.length;}public String getMimeType(int i){return types[i];}}',
    'android/content/ClipData.java': 'package android.content;public class ClipData {public ClipDescription description;public Item[] items;public ClipData(ClipDescription d,Item[] i){description=d;items=i;}public ClipDescription getDescription(){return description;}public int getItemCount(){return items.length;}public Item getItemAt(int i){if(i!=0)throw new AssertionError("only first item");return items[i];}public static class Item {private CharSequence text;public Object uri,intent;public Item(CharSequence t){text=t;}public CharSequence getText(){return text;}public Object getUri(){return uri;}public Object getIntent(){return intent;}}}',
    'android/content/ClipboardManager.java': 'package android.content;public class ClipboardManager {public ClipData clip;public int reads;public Runnable afterRead;public ClipDescription getPrimaryClipDescription(){return clip==null?null:clip.description;}public ClipData getPrimaryClip(){reads++;if(afterRead!=null)afterRead.run();return clip;}}',
    'androidx/appcompat/app/AppCompatActivity.java': 'package androidx.appcompat.app;public class AppCompatActivity extends android.app.Activity {private final androidx.lifecycle.Lifecycle lifecycle=new androidx.lifecycle.Lifecycle();public androidx.lifecycle.Lifecycle getLifecycle(){return lifecycle;}}',
    'androidx/lifecycle/Lifecycle.java': 'package androidx.lifecycle;public class Lifecycle {public enum State {DESTROYED,INITIALIZED,CREATED,STARTED,RESUMED;public boolean isAtLeast(State other){return compareTo(other)>=0;}}public State currentState=State.CREATED;public State getCurrentState(){return currentState;}}',
    'app/tauri/plugin/JSObject.java': 'package app.tauri.plugin;public class JSObject extends java.util.HashMap<String,Object> {}',
    'app/tauri/plugin/Invoke.java': 'package app.tauri.plugin;public class Invoke {public JSObject result;public void resolve(JSObject value){if(result!=null)throw new AssertionError("double resolve");result=value;}}',
    'app/tauri/plugin/Plugin.java': 'package app.tauri.plugin;public class Plugin {public Plugin(android.app.Activity a){}}',
}
for name in ['Command', 'TauriPlugin']:
    sources[f'app/tauri/annotation/{name}.java'] = f'package app.tauri.annotation; public @interface {name} {{}}'

with tempfile.TemporaryDirectory(prefix='herdr-clipboard-stubs-') as temporary:
    root = Path(temporary)
    for name, content in sources.items():
        path = root / 'stubs' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    classes = root / 'classes'
    classes.mkdir()
    subprocess.run(['javac', '-d', str(classes), *[str(root / 'stubs' / n) for n in sources]], check=True)
    output = root / 'compiled'
    output.mkdir()
    subprocess.run(['java', '-cp', ':'.join(map(str, jars)), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                    '-no-stdlib', '-no-reflect', '-classpath', ':'.join(map(str, [classes, *jars])),
                    '-d', str(output), str(repo / 'validation/tauri/android/ClipboardPlugin.kt'),
                    str(Path(__file__).with_name('ClipboardPluginProbe.kt'))], check=True)
    subprocess.run(['java', '-cp', ':'.join(map(str, [output, classes, *jars])),
                    'org.herdr.pocket.ClipboardPluginProbeKt'], check=True)
