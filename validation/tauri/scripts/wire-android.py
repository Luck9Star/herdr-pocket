"""Wire shared Android sources into the disposable Tauri-generated Gradle project."""
from pathlib import Path
import shutil
from js_notices import copy_android_assets

root=Path(__file__).resolve().parents[1]
project=root/'src-tauri/gen/android'
app=project/'app'
gradle=app/'build.gradle.kts'
text=gradle.read_text()
if 'herdr-pocket shared device keys' in text:
    raise SystemExit('device key wiring already present')
text += '''
// herdr-pocket shared device keys; generated project only
val sharedDeviceKeys = rootProject.projectDir.resolve("../../../../pairing/native/android").canonicalFile
extensions.extraProperties["herdrDeviceKeysDir"] = sharedDeviceKeys
apply(from = sharedDeviceKeys.resolve("device-keys.gradle"))
val sharedNetworkVault = rootProject.projectDir.resolve("../../../../network-profiles/native/android").canonicalFile
extensions.extraProperties["herdrNetworkSecretsDir"] = sharedNetworkVault
apply(from = sharedNetworkVault.resolve("network-secrets.gradle"))
// Preserve the exact candidate bytes required by the native bundle verifier.
android { packaging { jniLibs.keepDebugSymbols += setOf("**/libheeler_easytier.so", "**/libhp_tailscale.so", "**/libhp_zerotier.so") } }
'''
gradle.write_text(text)
target=app/'src/main/java/org/herdr/pocket/DeviceKeysPlugin.kt'
target.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(root/'android/DeviceKeysPlugin.kt',target)
shutil.copyfile(root/'android/NetworkAuthReview.kt',target.with_name('NetworkAuthReview.kt'))
shutil.copyfile(root/'android/PairScanPlugin.kt',target.with_name('PairScanPlugin.kt'))
shutil.copyfile(root/'android/ConfigDocumentPlugin.kt',target.with_name('ConfigDocumentPlugin.kt'))
shutil.copyfile(root/'android/ClipboardPlugin.kt',target.with_name('ClipboardPlugin.kt'))
shutil.copyfile(root/'android/TerminalKeyboardPlugin.kt',target.with_name('TerminalKeyboardPlugin.kt'))
copy_android_assets(root, app/'src/main/assets')
wrapper_props = project / 'gradle/wrapper/gradle-wrapper.properties'
if wrapper_props.exists():
    props_text = wrapper_props.read_text()
    if 'networkTimeout=10000' in props_text:
        wrapper_props.write_text(props_text.replace('networkTimeout=10000', 'networkTimeout=120000'))
    elif 'networkTimeout=' not in props_text:
        wrapper_props.write_text(props_text + '\nnetworkTimeout=120000\n')
