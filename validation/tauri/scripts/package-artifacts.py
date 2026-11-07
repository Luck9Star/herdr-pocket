"""Create bounded, auditable test artifacts, including failures; never package credentials."""
from pathlib import Path
import hashlib, json, os, platform, shutil, subprocess, sys, zipfile
root = Path(__file__).resolve().parents[1]
repo = root.parents[1]
sys.path.insert(0, str(repo / 'validation/shared'))
from android_notices import verify as verify_packaged_notices
sys.path.insert(0, str(repo / 'validation/network-profiles'))
from android_sources import production_java_hashes
sys.path.insert(0, str(root / 'scripts'))
from js_notices import collect as collect_js_notices, verify_zip as verify_js_notices
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
def android_apks():
    if 'ANDROID_APK_PATH' not in os.environ:
        return list(root.glob('src-tauri/gen/android/app/build/outputs/apk/**/*.apk'))
    value = os.environ['ANDROID_APK_PATH']
    if not value:
        return []
    candidate = Path(value)
    runner_temp = Path(os.environ.get('RUNNER_TEMP', '')).resolve()
    if (not os.environ.get('RUNNER_TEMP') or candidate.is_symlink() or not candidate.is_file() or
            not candidate.resolve().is_relative_to(runner_temp)):
        raise SystemExit('ANDROID_APK_PATH must name a runner-owned APK')
    return [candidate.resolve()]
fixture_checksums = (repo/'validation/shared/SHA256SUMS').read_text().splitlines()
fixture_provenance = {}
for field, filename in {
    'configTransferFixtureSHA256': 'config-transfer-v1.json',
    'configTransferV2FixtureSHA256': 'config-transfer-v2.json',
    'networkProfileFixtureSHA256': 'network-profiles-v1.json',
}.items():
    digest = sha(repo/'validation/shared'/filename)
    if digest + '  ' + filename not in fixture_checksums:
        raise SystemExit('Shared fixture checksum mismatch: ' + filename)
    fixture_provenance[field] = digest
source_sha = os.environ.get('GITHUB_SHA', '')
if len(source_sha) not in (40, 64) or any(ch not in '0123456789abcdef' for ch in source_sha.lower()):
    raise SystemExit('GITHUB_SHA must identify the exact source commit before packaging')
manifest = {
    'schemaVersion':1, 'sourceSHA':source_sha,
    'route':'tauri', 'platform':os.getenv('PROBE_PLATFORM','unknown'),
    'buildOutcome':os.getenv('BUILD_OUTCOME','unknown'), 'deviceResult':'unverified',
    'signing':'ephemeral-debug-key' if os.getenv('PROBE_PLATFORM')=='android' else 'unsigned-test-only',
    'runner':{'os':platform.platform(),'architecture':platform.machine(),'imageVersion':os.getenv('ImageVersion'),'imageOS':os.getenv('ImageOS')},
    'toolchains':{'node':version(['node','--version']),'rustc':version(['rustc','--version']),'cargo':version(['cargo','--version'])},
    'versions':{'tauriCore':'2.12.5','tauriBuild':'2.7.4','tauriAPI':'2.12.4','tauriCLI':'2.12.4','xterm':'6.0.0','russh':'0.65.0','herdrProtocolTarget':'0.9.5'},
    'scope':'Experimental pairing v2, opaque device signer, explicit SSH target review and bounded continuous read-only observation. Package construction does not exercise the device key store.',
    'remoteContractSHA256':sha(repo/'validation/shared/remote-contract.json'),
    'transportSourceSHA256':sha(repo/'validation/transport-rust/src/lib.rs'),
    'pairingContractSHA256':sha(repo/'validation/pairing/protocol-v2.schema.json'),
    'pairingDependenciesSHA256':sha(repo/'validation/pairing/sources.json'),
    'remoteBehavior':{'mode':'explicit-pane-continuous-readonly','remoteInput':'stock server read-only; explicit guarded capability required','ptyResize':False,'credentialStorage':{'android':'API35 wrapped Ed25519', 'linux':'volatile test signer', 'macos':'volatile test signer'}.get(os.getenv('PROBE_PLATFORM'),'device pairing unavailable'),'browserTransport':'unavailable','deviceResult':'unverified'},
    'fixtureSHA256':sha(repo/'validation/shared/fixture.json'),
    **fixture_provenance,
    'fontSHA256':sha(repo/'validation/shared/fonts/JetBrainsMonoNerdFontMono-Regular.ttf'),
    'designTokensSHA256':sha(repo/'validation/shared/design-tokens-v2.json'),
    'visualBaseline':'herdr-pocket-v2-tech-indigo; shared 16 ANSI colors; fixed 80x24 fixture',
    'artifacts':[]}
if platform.system()=='Darwin': manifest['toolchains']['xcode']=version(['xcodebuild','-version'])
if os.getenv('PROBE_PLATFORM')=='android':
    manifest['toolchains']['java']=version(['java','-version']); manifest['toolchains']['ndk']='28.2.13676358'; manifest['toolchains']['androidPlatform']='android-35'
    manifest['toolchains']['androidTargetAbi']=os.getenv('ANDROID_TARGET_ABI','not recorded')
for f in [root/'package-lock.json',root/'src-tauri/Cargo.lock',root/'core/Cargo.lock',repo/'validation/transport-rust/Cargo.lock']:
    if f.exists(): shutil.copy2(f,out/f'{f.parent.name}-{f.name}')
shutil.copytree(repo/'validation/shared',out/'shared',dirs_exist_ok=True,ignore=shutil.ignore_patterns('.gitattributes'))
js_notices = collect_js_notices(root)
js_notice_manifest = {}
for filename, record in js_notices.items():
    (out/filename).write_bytes(record['data'])
    js_notice_manifest[filename] = {key:value for key,value in record.items() if key != 'data'}
(out/'js-notices.json').write_text(json.dumps(js_notice_manifest,indent=2)+'\n')
if (root/'dist').exists(): zip_tree(root/'dist',out/'browser-preview.zip')
if (out/'browser-preview.zip').exists():
    verify_js_notices(out/'browser-preview.zip',js_notices,'dist/js-notices/')
for pattern in ['src-tauri/target/release/bundle/deb/*.deb','src-tauri/target/release/bundle/nsis/*.exe']:
    for f in root.glob(pattern): shutil.copy2(f,out/f.name)
for f in android_apks(): shutil.copy2(f,out/f.name)
for base in [root/'src-tauri/target/release/bundle/macos',root/'src-tauri/gen/apple/build']:
    if base.exists():
        for app in base.rglob('*.app'):
            # ditto preserves the app bundle's executable bits and links on Apple hosts.
            dest=out/(app.name+'.zip')
            if platform.system()=='Darwin': subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(dest)],check=True)
            else: zip_tree(app,dest)
native_packages=[f for f in out.iterdir() if f.is_file() and (f.suffix in ['.apk','.deb','.exe'] or f.name.endswith('.app.zip'))]
manifest['nativeArtifactStatus']='present-unverified' if native_packages else 'missing'
if manifest['platform']=='android' and manifest['buildOutcome']=='success':
    native=repo/'validation/pairing/native/android'
    manifest['androidSignerSources']={f.name:sha(f) for f in sorted(native.glob('*.java'))}
    network_vault=repo/'validation/network-profiles/native/android'
    manifest['androidNetworkVaultSources']=production_java_hashes(network_vault)
    manifest['androidNetworkVaultSourceListSHA256']=sha(network_vault/'android-production-sources.txt')
    manifest['androidNetworkVaultGradleSHA256']=sha(network_vault/'network-secrets.gradle')
    manifest['androidNetworkBridgeSHA256']=sha(root/'android/DeviceKeysPlugin.kt')
    network_source=repo/'validation/android-network-source'
    manifest['androidNetworkSourceSHA256']={str(f.relative_to(network_source)):sha(f) for f in [network_source/'Cargo.toml',network_source/'Cargo.lock',network_source/'src/lib.rs']}
    manifest['androidNetworkEngine']='feature-gated; runtime and device unverified'
    manifest['androidNetworkVaultDeviceResult']='unverified'
    manifest['androidPackagedNotices']={apk.name:verify_packaged_notices(apk) for apk in native_packages if apk.suffix=='.apk'}
    manifest['tauriJavaScriptNotices']={apk.name:verify_js_notices(apk,js_notices,'assets/') for apk in native_packages if apk.suffix=='.apk'}
    manifest['tauriJavaScriptNoticeSources']=js_notice_manifest
    manifest['androidApkSha256']={apk.name:sha(apk) for apk in native_packages if apk.suffix=='.apk'}
    manifest['androidSignerNoticeSHA256']=sha(native/'notices/BOUNCY-CASTLE-LICENSE.md')

for f in sorted(out.iterdir()):
    if f.is_file() and f.name not in ['build-manifest.json','SHA256SUMS']:
        manifest['artifacts'].append({'file':f.name,'bytes':f.stat().st_size,'sha256':sha(f)})
(out/'build-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(out/'SHA256SUMS').write_text(''.join(sha(f)+'  '+str(f.relative_to(out))+'\n' for f in sorted(out.rglob('*')) if f.is_file() and f.name!='SHA256SUMS'))
print(json.dumps({'platform':manifest['platform'],'buildOutcome':manifest['buildOutcome'],'files':[x['file'] for x in manifest['artifacts']]}))

if manifest['buildOutcome']=='success' and not native_packages:
    raise SystemExit('Build reported success but no native test package was collected; inspect generated output paths.')
