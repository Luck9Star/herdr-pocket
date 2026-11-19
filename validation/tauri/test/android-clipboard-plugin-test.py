#!/usr/bin/env python3
"""Compile the Kotlin clipboard and keyboard bridges against isolated SDK/Tauri stubs."""
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
    'android/content/Context.java': 'package android.content; public class Context {public static final String CLIPBOARD_SERVICE="clipboard", INPUT_METHOD_SERVICE="input_method";public Object service;public Runnable onService;public Object getSystemService(String key){if(onService!=null)onService.run();return service;}}',
    'android/app/Activity.java': 'package android.app; public class Activity extends android.content.Context {public android.view.WindowManager windowManager=new android.view.WindowManager();public android.view.WindowManager getWindowManager(){return windowManager;}public boolean focus=true,finishing,destroyed;public boolean hasWindowFocus(){return focus;}public boolean isFinishing(){return finishing;}public boolean isDestroyed(){return destroyed;}public boolean queued;public final java.util.ArrayList<Runnable> tasks=new java.util.ArrayList<>();public void runOnUiThread(Runnable task){if(queued)tasks.add(task);else task.run();}public void flush(){while(!tasks.isEmpty())tasks.remove(0).run();}}',
    'android/content/ClipDescription.java': 'package android.content;public class ClipDescription {private final String[] types;public ClipDescription(String[] types){this.types=types;}public boolean hasMimeType(String type){for(String t:types)if(t.equals(type))return true;return false;}public int getMimeTypeCount(){return types.length;}public String getMimeType(int i){return types[i];}}',
    'android/content/ClipData.java': 'package android.content;public class ClipData {public ClipDescription description;public Item[] items;public ClipData(ClipDescription d,Item[] i){description=d;items=i;}public static ClipData newPlainText(CharSequence label,CharSequence text){return new ClipData(new ClipDescription(new String[]{"text/plain"}),new Item[]{new Item(text)});}public ClipDescription getDescription(){return description;}public int getItemCount(){return items.length;}public Item getItemAt(int i){if(i!=0)throw new AssertionError("only first item");return items[i];}public static class Item {private CharSequence text;public Object uri,intent;public Item(CharSequence t){text=t;}public CharSequence getText(){return text;}public Object getUri(){return uri;}public Object getIntent(){return intent;}}}',
    'android/content/ClipboardManager.java': 'package android.content;public class ClipboardManager {public ClipData clip;public int reads,writes,writeCalls;public boolean failWrites;public Runnable afterRead;public void setPrimaryClip(ClipData value){writeCalls++;if(failWrites)throw new IllegalStateException("synthetic private failure");writes++;clip=value;}public ClipDescription getPrimaryClipDescription(){return clip==null?null:clip.description;}public ClipData getPrimaryClip(){reads++;if(afterRead!=null)afterRead.run();return clip;}}',
    'androidx/appcompat/app/AppCompatActivity.java': 'package androidx.appcompat.app;public class AppCompatActivity extends android.app.Activity {private final androidx.lifecycle.Lifecycle lifecycle=new androidx.lifecycle.Lifecycle();public androidx.lifecycle.Lifecycle getLifecycle(){return lifecycle;}}',
    'androidx/lifecycle/Lifecycle.java': 'package androidx.lifecycle;public class Lifecycle {public enum State {DESTROYED,INITIALIZED,CREATED,STARTED,RESUMED;public boolean isAtLeast(State other){return compareTo(other)>=0;}}public State currentState=State.CREATED;public State getCurrentState(){return currentState;}}',
    'app/tauri/plugin/JSObject.java': 'package app.tauri.plugin;public class JSObject extends java.util.HashMap<String,Object> {}',
    'app/tauri/plugin/Invoke.java': 'package app.tauri.plugin;public class Invoke {public Object args; public String rejection; public <T> T parseArgs(Class<T> type){return type.cast(args);} public void reject(String message){rejection=message;} public JSObject result;public void resolve(JSObject value){if(result!=null)throw new AssertionError("double resolve");result=value;}}',
    'app/tauri/plugin/Plugin.java': 'package app.tauri.plugin;public class Plugin {public Plugin(android.app.Activity a){} public void load(android.webkit.WebView view){} public void onPause(androidx.appcompat.app.AppCompatActivity activity){}}',
}
sources.update({
    'android/os/SystemClock.java': 'package android.os; public class SystemClock {public static long now; public static long elapsedRealtime(){return now;}}',
    'android/os/Build.java': 'package android.os; public class Build {public static class VERSION {public static int SDK_INT=35;}}',
    'android/util/DisplayMetrics.java': 'package android.util; public class DisplayMetrics {public float density=2;}',
    'android/content/res/Resources.java': 'package android.content.res; public class Resources {public android.util.DisplayMetrics metrics=new android.util.DisplayMetrics();public android.util.DisplayMetrics getDisplayMetrics(){return metrics;}}',
    'android/graphics/Insets.java': 'package android.graphics; public class Insets {public int top,bottom;public Insets(int top,int bottom){this.top=top;this.bottom=bottom;}}',
    'android/graphics/Rect.java': 'package android.graphics; public class Rect {public int top,bottom;public int height(){return bottom-top;}}',
    'android/view/WindowMetrics.java': 'package android.view; public class WindowMetrics {public android.graphics.Rect bounds=new android.graphics.Rect();public android.graphics.Rect getBounds(){return bounds;}}',
    'android/view/WindowManager.java': 'package android.view; public class WindowManager {public WindowMetrics metrics=new WindowMetrics();public WindowMetrics getCurrentWindowMetrics(){return metrics;}}',
    'android/view/WindowInsets.java': 'package android.view; public class WindowInsets {public int top,imeBottom;public boolean imeVisible;public boolean isVisible(int type){return type==Type.ime()&&imeVisible;}public android.graphics.Insets getInsets(int type){return type==Type.ime()?new android.graphics.Insets(0,imeBottom):new android.graphics.Insets(top,0);}public android.graphics.Insets getInsetsIgnoringVisibility(int type){if(type==Type.ime())throw new IllegalArgumentException();return new android.graphics.Insets(top,0);}public int getSystemWindowInsetTop(){return top;}public int getStableInsetTop(){return top;}public static class Type {public static int statusBars(){return 1;}public static int displayCutout(){return 2;}public static int captionBar(){return 4;}public static int ime(){return 8;}}}',
    'android/os/IBinder.java': 'package android.os; public interface IBinder {}',
    'android/webkit/ValueCallback.java': 'package android.webkit; public interface ValueCallback<T> {void onReceiveValue(T value);}',
    'android/webkit/WebView.java': '''package android.webkit;
        import java.util.ArrayList;
        public class WebView extends android.view.View {
            public ArrayList<ValueCallback<String>> callbacks = new ArrayList<>();
            public String script;
            public void evaluateJavascript(String value,ValueCallback<String> callback){script=value; callbacks.add(callback);}
        }''',
    'android/view/View.java': '''package android.view;
        public class View {
            public boolean focus=true,windowFocus=true,attached=true;
            public int y,height=2340; public View root=this; public WindowInsets insets=new WindowInsets();
            public int visibleTop; public void getWindowVisibleDisplayFrame(android.graphics.Rect out){out.top=visibleTop;}
            public int getWidth(){return 1080;} public int getHeight(){return height;}
            public android.content.res.Resources resources=new android.content.res.Resources();
            public WindowInsets getRootWindowInsets(){return insets;}
            public View getRootView(){return root;}
            public void getLocationOnScreen(int[] out){out[1]=y;}
            public android.content.res.Resources getResources(){return resources;}
            private final android.os.IBinder token=new android.os.IBinder(){};
            public boolean hasFocus(){return focus;}
            public boolean hasWindowFocus(){return windowFocus;}
            public boolean isAttachedToWindow(){return attached;}
            public android.os.IBinder getWindowToken(){return token;}
        }''',
    'android/view/inputmethod/InputMethodManager.java': '''package android.view.inputmethod;
        public class InputMethodManager {
            public int shown,hidden; public android.view.View view; public android.os.IBinder token;
            public boolean showSoftInput(android.view.View target,int flags){if(flags!=0)throw new AssertionError();shown++;view=target;return true;}
            public boolean hideSoftInputFromWindow(android.os.IBinder target,int flags){if(flags!=0)throw new AssertionError();hidden++;token=target;return true;}
        }''',
})
for name in ['Command', 'TauriPlugin', 'InvokeArg']:
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
                    str(Path(__file__).with_name('ClipboardPluginProbe.kt')),
                    str(repo / 'validation/tauri/android/TerminalKeyboardPlugin.kt'),
                    str(Path(__file__).with_name('TerminalKeyboardPluginProbe.kt'))], check=True)
    subprocess.run(['java', '-cp', ':'.join(map(str, [output, classes, *jars])),
                    'org.herdr.pocket.ClipboardPluginProbeKt'], check=True)
    subprocess.run(['java', '-cp', ':'.join(map(str, [output, classes, *jars])),
                    'org.herdr.pocket.TerminalKeyboardPluginProbeKt'], check=True)
