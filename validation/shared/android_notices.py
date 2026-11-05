"""Verify license files shipped in the two Android candidate APKs."""
from pathlib import Path
import hashlib
import zipfile

NATIVE = Path(__file__).resolve().parents[1] / 'pairing/native'
FILES = ('android/notices/BOUNCY-CASTLE-LICENSE.md',
         'camera/android/notices/QR-NOTICE.txt', 'camera/android/notices/ZXING-APACHE-2.0.txt')


def verify(apk):
    verified = {}
    with zipfile.ZipFile(apk) as package:
        for relative in FILES:
            source = NATIVE / relative
            name = 'assets/' + source.name
            entries = [entry for entry in package.infolist() if entry.filename == name]
            if len(entries) != 1 or entries[0].file_size > 65536:
                raise SystemExit('Missing, duplicate or oversized Android asset: ' + name)
            actual = hashlib.sha256(package.read(entries[0])).hexdigest()
            if actual != hashlib.sha256(source.read_bytes()).hexdigest():
                raise SystemExit('Android asset differs from reviewed source: ' + name)
            verified[name] = actual
    return verified
