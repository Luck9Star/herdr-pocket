#!/usr/bin/env python3
"""Real Tauri Kotlin -> real Java service/store/core; only platform/KeyStore stubs.

No SDK, JNI, native identity generator, real authorization or network is used.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('tools', type=Path)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[3]
here = Path(__file__).resolve().parent
android = repo / 'validation/network-profiles/native/android'
jars = []
for record in json.loads((repo / 'validation/flutter/tool/kotlin-probe-tools.json').read_text()):
    path = args.tools / record['file']
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise SystemExit('tool hash mismatch: ' + record['file'])
    jars.append(path.resolve())

# Reuse the existing platform-only fixtures, without executing its probe or its
# synthetic service. The service below is always the production Java source.
tree = ast.parse((here / 'android-network-plugin-test.py').read_text())
sources = ast.literal_eval(next(node.value for node in ast.walk(tree)
    if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'sources'
                                           for target in node.targets)))
sources.pop('org/herdr/network/AndroidZeroTierDeviceService.java', None)
sources['android/content/Context.java'] = '''package android.content;
public class Context {
 private final java.io.File root; private final android.app.KeyguardManager lock;
 public Context(){this(null,new android.app.KeyguardManager());}
 public Context(java.io.File root,android.app.KeyguardManager lock){this.root=root;this.lock=lock;}
 public Context getApplicationContext(){return this;}
 public java.io.File getNoBackupFilesDir(){if(root==null)throw new IllegalStateException("fixture root not set");return root;}
 public <T>T getSystemService(Class<T> cls){return cls.cast(lock);}
}'''
for name in ('Command', 'InvokeArg', 'TauriPlugin'):
    sources[f'app/tauri/annotation/{name}.java'] = f'package app.tauri.annotation; public @interface {name} {{}}'
for name in ('app/KeyguardManager.java', 'security/keystore/KeyGenParameterSpec.java',
             'security/keystore/KeyProperties.java'):
    sources['android/' + name] = (android / 'tests/zerotier-stubs/android' / name).read_text()

with tempfile.TemporaryDirectory(prefix='herdr-tauri-real-zt-service-') as temporary:
    root = Path(temporary)
    paths = []
    for name, value in sources.items():
        path = root / 'stubs' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        paths.append(path)
    classes = root / 'classes'
    classes.mkdir()
    production = [android / name for name in ('ZeroTierDeviceStoreCore.java',
        'AndroidZeroTierEnvelope.java', 'AndroidZeroTierDeviceStore.java', 'AndroidZeroTierDeviceService.java')]
    subprocess.run(['javac', '-d', str(classes), *map(str, paths + production + [
        android / 'tests/ZeroTierAndroidStoreTest.java', here / 'ZeroTierPluginServiceFixture.java'])], check=True)
    output = root / 'compiled'
    output.mkdir()
    subprocess.run(['java', '-cp', ':'.join(map(str, jars)),
        'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
        '-classpath', ':'.join(map(str, [classes, *jars])), '-d', str(output),
        str(repo / 'validation/tauri/android/DeviceKeysPlugin.kt'),
        str(repo / 'validation/tauri/android/NetworkAuthReview.kt'),
        str(here / 'ZeroTierPluginServiceProbe.kt')], check=True)
    for mode in ('uninstalled', 'installed'):
        subprocess.run(['java', '-cp', ':'.join(map(str, [output, classes, *jars])),
            'org.herdr.pocket.ZeroTierPluginServiceProbeKt', mode, str(root / mode)], check=True)
print('Real Kotlin plugin + Java service/store/core passed; platform/JCE substitutes only. Not AndroidKeyStore/JNI/network proof.')
