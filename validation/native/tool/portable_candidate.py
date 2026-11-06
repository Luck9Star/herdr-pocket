#!/usr/bin/env python3
"""Build the exact experimental Heeler patch; never start a network node."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
os.environ['NATIVE_PROBE_OUTPUT']=str(ROOT/'validation/native/candidate-artifacts')
import probe as base

def apply(reference):
    manifest=json.loads((ROOT/'validation/native/patches/portable-manifest.json').read_text())
    patch=ROOT/'validation/native/patches'/manifest['patch']
    if base.sha(patch)!=manifest['patchSha256']:raise RuntimeError('candidate patch hash mismatch')
    for name,digest in manifest.get('sourceTemplates',{}).items():
        if base.sha(ROOT/'validation/native/portable-stream'/name)!=digest:raise RuntimeError('candidate source template hash mismatch: '+name)
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=reference,text=True).strip()!=manifest['referenceCommit']:
        raise RuntimeError('candidate source commit mismatch')
    for name,digest in manifest['originalFiles'].items():
        if base.sha(reference/name)!=digest:raise RuntimeError('candidate original hash mismatch: '+name)
    base.run('candidate-patch-check',['git','apply','--check',patch],cwd=reference,timeout=30)
    base.run('candidate-patch-apply',['git','apply',patch],cwd=reference,timeout=30)
    for name,digest in manifest['patchedFiles'].items():
        if base.sha(reference/name)!=digest:raise RuntimeError('candidate patched hash mismatch: '+name)
    target=reference/'native/easytier/src'
    (target/'pocket_stream').mkdir()
    for name,destination in [('src/lib.rs',target/'pocket_stream.rs'),('src/tests.rs',target/'pocket_stream/tests.rs')]:
        source=ROOT/'validation/native/portable-stream'/name
        if base.sha(source)!=manifest['copiedModules'][name]:raise RuntimeError('candidate module hash mismatch: '+name)
        shutil.copy2(source,destination)
    (base.OUT/'candidate-provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    shutil.copy2(patch,base.OUT/patch.name)
    return manifest

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true':raise SystemExit('candidate native build is CI-only')
    base.OUT.mkdir(parents=True,exist_ok=True)
    base.WORK=Path(os.environ['RUNNER_TEMP'])/('herdr-native-candidate-'+os.environ['GITHUB_RUN_ID'])
    base.WORK.mkdir() # Refuses reuse or overwriting any prior tree.
    base.CURRENT={'provider':'easytier-candidate','commands':[]}
    report={'schemaVersion':1,'sourceSHA':os.environ['GITHUB_SHA'],'platform':platform.system(),
            'arch':platform.machine(),'runnerImage':os.environ.get('ImageVersion'),
            'runUrl':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],
            'status':'failed','check':'not run','link':'not run','load':'not run','loopbackTests':'not run',
            'overlayNodesStarted':False,'overlayDial':'not run','deviceValidation':'not run',
            'scope':'Candidate Heeler source check/link, exact embedded portable stream loopback tests, ABI load only. No start/join, identities, overlay traffic or GUI binding.',
            'details':base.CURRENT}
    try:
        reference=base.WORK/'reference'
        base.checkout(base.CONFIG['reference']['repository'],base.CONFIG['reference']['commit'],reference,'reference')
        lock=base.lock_values(reference);shutil.copy2(reference/'sources.lock',base.OUT/'upstream-sources.lock')
        env=base.easytier(reference,lock,check=False)
        apply(reference)
        source=reference/'native/easytier'
        base.licenses('heeler-easytier',source)
        base.run('candidate-check',['cargo','+1.95.0','check','--locked','--lib'],cwd=source,env=env,timeout=1800)
        report['check']='passed'
        # Only our offline module/FFI tests are selected, never the upstream network tests.
        base.run('candidate-loopback-tests',['cargo','+1.95.0','test','--locked','--lib','pocket','--','--nocapture'],cwd=source,env=env,timeout=2400)
        report['loopbackTests']='passed'
        base.run('candidate-shared-build',['cargo','+1.95.0','build','--locked','--lib'],cwd=source,env=env,timeout=2400)
        report['link']='passed'
        name={'Windows':'heeler_easytier.dll','Darwin':'libheeler_easytier.dylib','Linux':'libheeler_easytier.so'}[platform.system()]
        library=source/'target/debug'/name
        if not library.is_file():raise RuntimeError('shared library missing')
        load='''import ctypes,sys
lib=ctypes.CDLL(sys.argv[1])
for symbol in ['heeler_et_stream_connect','heeler_et_stream_read','heeler_et_stream_write','heeler_et_stream_shutdown_write','heeler_et_stream_close','heeler_et_node_start','heeler_et_node_status','heeler_et_node_stop','heeler_et_node_stream_connect']:
    getattr(lib,symbol)
close=lib.heeler_et_stream_close;close.argtypes=[ctypes.c_uint64,ctypes.c_void_p,ctypes.c_size_t];close.restype=ctypes.c_int
assert close(0,None,0)==-6
status=lib.heeler_et_node_status;status.argtypes=[ctypes.c_uint64,ctypes.POINTER(ctypes.c_uint32),ctypes.c_void_p,ctypes.c_size_t];status.restype=ctypes.c_int
state=ctypes.c_uint32(0)
assert status(0,ctypes.byref(state),None,0)==-6
print('five stream and four managed-node ABI symbols resolved; invalid handles rejected; no node started')
'''
        base.run('candidate-shared-load',[sys.executable,'-c',load,library],timeout=30)
        report['load']='passed';report['library']={'bytes':library.stat().st_size,'sha256':base.sha(library)}
        shutil.copy2(source/'Cargo.lock',base.OUT/'Heeler-Cargo.lock')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    finally:
        (base.OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
        (base.OUT/'SHA256SUMS').write_text(''.join(base.sha(p)+'  '+str(p.relative_to(base.OUT))+'\n' for p in sorted(base.OUT.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
    print(json.dumps(report));return 0 if report['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
