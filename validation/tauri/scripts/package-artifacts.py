"""Create bounded, auditable test artifacts, including failures; never package credentials."""
from pathlib import Path
import hashlib, json, os, platform, shutil, subprocess, zipfile
root = Path(__file__).resolve().parents[1]
repo = root.parents[1]
out = root / 'artifacts'
out.mkdir(exist_ok=True)
def version(command):
    try: return subprocess.check_output(command, cwd=root, text=True, stderr=subprocess.STDOUT, timeout=30).strip()
    except Exception as exc: return type(exc).__name__
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def zip_tree(source, dest):
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(source.rglob('*')):
            if f.is_file(): z.write(f, f.relative_to(source.parent))
manifest = {
    'schemaVersion':1, 'sourceSHA':version(['git','rev-parse','HEAD']),
    'route':'tauri', 'platform':os.getenv('PROBE_PLATFORM','unknown'),
    'buildOutcome':os.getenv('BUILD_OUTCOME','unknown'), 'deviceResult':'unverified',
    'signing':'ephemeral-debug-key' if os.getenv('PROBE_PLATFORM')=='android' else 'unsigned-test-only',
    'runner':{'os':platform.platform(),'architecture':platform.machine(),'imageVersion':os.getenv('ImageVersion'),'imageOS':os.getenv('ImageOS')},
    'toolchains':{'node':version(['node','--version']),'rustc':version(['rustc','--version']),'cargo':version(['cargo','--version'])},
    'versions':{'tauriCore':'2.12.5','tauriBuild':'2.7.4','tauriAPI':'2.12.4','tauriCLI':'2.12.4','xterm':'6.0.0','russh':'0.65.0','herdrProtocolTarget':'0.9.5'},
    'scope':'Separate offline renderer/IPC fixture and experimental reviewed SSH one-shot read-only adapter; no remote input, overlay integration or protected credential storage. Build does not verify devices or a real remote connection.',
    'remoteContractSHA256':sha(repo/'validation/shared/remote-contract.json'),
    'transportSourceSHA256':sha(repo/'validation/transport-rust/src/lib.rs'),
    'remoteBehavior':{'mode':'one-shot-readonly','remoteInput':False,'ptyResize':False,'credentialStorage':'experimental-memory-only','browserTransport':'unavailable','deviceResult':'unverified'},
    'fixtureSHA256':sha(repo/'validation/shared/fixture.json'),
    'fontSHA256':sha(repo/'validation/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'),
    'designTokensSHA256':sha(repo/'validation/shared/design-tokens-v2.json'),
    'visualBaseline':'herdr-pocket-v2-tech-indigo; shared 16 ANSI colors; fixed 80x24 fixture',
    'artifacts':[]}
if platform.system()=='Darwin': manifest['toolchains']['xcode']=version(['xcodebuild','-version'])
if os.getenv('PROBE_PLATFORM')=='android':
    manifest['toolchains']['java']=version(['java','-version']); manifest['toolchains']['ndk']='28.2.13676358'; manifest['toolchains']['androidPlatform']='android-35'
for f in [root/'package-lock.json',root/'src-tauri/Cargo.lock',root/'core/Cargo.lock',repo/'validation/transport-rust/Cargo.lock']:
    if f.exists(): shutil.copy2(f,out/f'{f.parent.name}-{f.name}')
shutil.copytree(repo/'validation/shared',out/'shared',dirs_exist_ok=True,ignore=shutil.ignore_patterns('.gitattributes'))
if (root/'dist').exists(): zip_tree(root/'dist',out/'browser-preview.zip')
for pattern in ['src-tauri/target/release/bundle/deb/*.deb','src-tauri/target/release/bundle/nsis/*.exe','src-tauri/gen/android/app/build/outputs/apk/**/*.apk']:
    for f in root.glob(pattern): shutil.copy2(f,out/f.name)
for base in [root/'src-tauri/target/release/bundle/macos',root/'src-tauri/gen/apple/build']:
    if base.exists():
        for app in base.rglob('*.app'):
            # ditto preserves the app bundle's executable bits and links on Apple hosts.
            dest=out/(app.name+'.zip')
            if platform.system()=='Darwin': subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(dest)],check=True)
            else: zip_tree(app,dest)
native_packages=[f for f in out.iterdir() if f.is_file() and (f.suffix in ['.apk','.deb','.exe'] or f.name.endswith('.app.zip'))]
manifest['nativeArtifactStatus']='present-unverified' if native_packages else 'missing'
for f in sorted(out.iterdir()):
    if f.is_file() and f.name not in ['build-manifest.json','SHA256SUMS']:
        manifest['artifacts'].append({'file':f.name,'bytes':f.stat().st_size,'sha256':sha(f)})
(out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(out/'SHA256SUMS').write_text(''.join(sha(f)+'  '+str(f.relative_to(out))+'\n' for f in sorted(out.rglob('*')) if f.is_file() and f.name!='SHA256SUMS'))
print(json.dumps({'platform':manifest['platform'],'buildOutcome':manifest['buildOutcome'],'files':[x['file'] for x in manifest['artifacts']]}))

if manifest['buildOutcome']=='success' and not native_packages:
    raise SystemExit('Build reported success but no native test package was collected; inspect generated output paths.')
