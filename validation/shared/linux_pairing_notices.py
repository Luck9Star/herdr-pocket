"""Verify the three vendored secret-service notices in a Linux application package."""
from hashlib import sha256
from pathlib import Path
import subprocess
import tarfile
from tempfile import TemporaryFile

SOURCE = Path(__file__).resolve().parents[1] / 'linux-secure-identity/vendor/secret-service'
NOTICE_FILES = ('LICENSE-APACHE', 'LICENSE-MIT', 'UPSTREAM')
FLUTTER_NOTICE_DIR = 'bundle/data/third-party/secret-service-5.1.0'
TAURI_DEB_NOTICE_DIR = 'usr/share/doc/herdr-pocket-tauri-probe/secret-service-5.1.0'


def verify_tar(bundle, directory):
    expected = {f'{directory}/{name}': (SOURCE / name).read_bytes() for name in NOTICE_FILES}
    verified = {}
    for member in bundle:
        name = member.name.removeprefix('./')
        if name not in expected:
            continue
        value = expected[name]
        if name in verified or not member.isfile() or member.size != len(value):
            raise ValueError('Linux pairing notice mismatch: ' + name)
        with bundle.extractfile(member) as stored:
            if stored.read() != value:
                raise ValueError('Linux pairing notice mismatch: ' + name)
        verified[name] = sha256(value).hexdigest()
    if verified.keys() != expected.keys():
        raise ValueError('Linux pairing notices missing: ' + ', '.join(sorted(expected.keys() - verified.keys())))
    return verified


def verify_deb(archive):
    # Avoid installing the package, extracting members, or buffering the
    # entire uncompressed Debian payload in memory.
    with TemporaryFile() as payload:
        subprocess.run(['dpkg-deb', '--fsys-tarfile', archive], stdout=payload, check=True, timeout=60)
        payload.seek(0)
        with tarfile.open(fileobj=payload, mode='r:') as bundle:
            return verify_tar(bundle, TAURI_DEB_NOTICE_DIR)
