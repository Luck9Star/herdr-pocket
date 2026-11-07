#!/usr/bin/env python3
"""Isolated real Kotlin channel + Java service/store/core; synthetic Android/key provider."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--kotlin-dir',required=True,type=Path)
args=parser.parse_args()
tests=Path(__file__).resolve().parent
native=tests.parent
repo=native.parents[3]
shared=repo/'validation/network-profiles/native/android'
records=json.loads((repo/'validation/flutter/tool/kotlin-probe-tools.json').read_text())
jars=[]
for record in records:
    path=args.kotlin_dir/record['file']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:
        raise SystemExit('Tool checksum mismatch: '+record['file'])
    jars.append(path.resolve())
# Reuse only the Android/Flutter channel test stubs; never its service double.
tree=ast.parse((tests/'run_zerotier_device_probe.py').read_text())
sources=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and
    any(isinstance(target,ast.Name) and target.id=='sources' for target in node.targets))
del sources['org/herdr/network/AndroidZeroTierDeviceService.java']
sources['android/content/Context.java']='''package android.content; import android.app.KeyguardManager; import java.io.File;
public class Context { private final File root; private final KeyguardManager lock; public Context(File root){this(root,new KeyguardManager());}
public Context(File root,KeyguardManager lock){this.root=root;this.lock=lock;} public Context getApplicationContext(){return this;}
public <T> T getSystemService(Class<T> cls){return cls.cast(lock);} public File getNoBackupFilesDir(){return root;} }'''
with tempfile.TemporaryDirectory(prefix='zt-channel-service-') as tmp:
    root=Path(tmp); paths=[]
    for name,content in sources.items():
        path=root/'stubs'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content);paths.append(path)
    stubs=shared/'tests/zerotier-stubs'
    paths += [stubs/name for name in ('android/app/KeyguardManager.java','android/os/Build.java',
        'android/security/keystore/KeyProperties.java','android/security/keystore/KeyGenParameterSpec.java')]
    paths += [shared/name for name in ('ZeroTierDeviceStoreCore.java','AndroidZeroTierEnvelope.java',
        'AndroidZeroTierDeviceStore.java','AndroidZeroTierDeviceService.java','tests/ZeroTierAndroidStoreTest.java')]
    paths.append(tests/'ZeroTierServiceBridgeFixture.java')
    classes=root/'classes';classes.mkdir();subprocess.run(['javac','-d',str(classes),*map(str,paths)],check=True)
    cp=':'.join(map(str,[classes,*jars]));out=root/'out';out.mkdir()
    subprocess.run(['java','-cp',':'.join(map(str,jars)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
        '-no-stdlib','-no-reflect','-classpath',cp,'-d',str(out),str(native/'HostCatalogFile.kt'),
        str(native/'ZeroTierDeviceChannel.kt'),str(tests/'ZeroTierDeviceServiceBridgeProbe.kt')],check=True)
    for mode in ('normal','pending','pending-deletion'):
        subprocess.run(['java','-cp',':'.join(map(str,[out,classes,*jars])),
            'dev.herdr.herdr_flutter_probe.ZeroTierDeviceServiceBridgeProbeKt',mode],check=True)
