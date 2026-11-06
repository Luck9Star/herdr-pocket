"""Wire shared Android sources into the disposable Tauri-generated Gradle project."""
from pathlib import Path
import shutil

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
'''
gradle.write_text(text)
target=app/'src/main/java/org/herdr/pocket/DeviceKeysPlugin.kt'
target.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(root/'android/DeviceKeysPlugin.kt',target)
shutil.copyfile(root/'android/PairScanPlugin.kt',target.with_name('PairScanPlugin.kt'))
shutil.copyfile(root/'android/ConfigDocumentPlugin.kt',target.with_name('ConfigDocumentPlugin.kt'))
