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
'''
gradle.write_text(text)
target=app/'src/main/java/org/herdr/pocket/DeviceKeysPlugin.kt'
target.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(root/'android/DeviceKeysPlugin.kt',target)
