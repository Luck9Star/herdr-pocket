"""Collect and verify the exact MIT notices for the pinned Tauri JS packages."""
from pathlib import Path
import hashlib
import json
import zipfile

PACKAGES = {
    '@xterm/xterm': ('6.0.0', 'xterm-LICENSE'),
    '@xterm/addon-unicode-graphemes': ('0.4.0', 'xterm-addon-unicode-graphemes-LICENSE'),
}
MAX_NOTICE_BYTES = 65536


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def collect(root):
    """Read package locks and installed package license bytes; fail closed on drift."""
    root = Path(root)
    package_json = json.loads((root / 'package.json').read_text())
    lock_path = root / 'package-lock.json'
    lock = json.loads(lock_path.read_text())
    records = {}
    for package, (version, filename) in PACKAGES.items():
        if package_json.get('dependencies', {}).get(package) != version:
            raise ValueError('package.json version mismatch: ' + package)
        locked = lock.get('packages', {}).get('node_modules/' + package)
        if not isinstance(locked, dict) or locked.get('version') != version or locked.get('license') != 'MIT':
            raise ValueError('package-lock entry/version/license mismatch: ' + package)
        resolved, integrity = locked.get('resolved'), locked.get('integrity')
        if not isinstance(resolved, str) or not resolved.startswith('https://') or not isinstance(integrity, str) or not integrity.startswith('sha512-'):
            raise ValueError('package-lock source integrity missing: ' + package)
        package_dir = root / 'node_modules' / package
        metadata = json.loads((package_dir / 'package.json').read_text())
        if metadata.get('name') != package or metadata.get('version') != version or metadata.get('license') != 'MIT':
            raise ValueError('installed package metadata mismatch: ' + package)
        source = package_dir / 'LICENSE'
        data = source.read_bytes()
        if not data or len(data) > MAX_NOTICE_BYTES:
            raise ValueError('missing or oversized package license: ' + package)
        records[filename] = {
            'package': package,
            'version': version,
            'license': 'MIT',
            'resolved': resolved,
            'integrity': integrity,
            'packageLockSha256': _sha(lock_path.read_bytes()),
            'sourceLicenseSha256': _sha(data),
            'bytes': len(data),
            'data': data,
        }
    return records


def copy_android_assets(root, assets_dir):
    records = collect(root)
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    for filename, record in records.items():
        (assets_dir / filename).write_bytes(record['data'])
    return records


def verify_zip(archive_path, records, prefix):
    """Require each exact notice path once and compare archive bytes to locked package source."""
    verified = {}
    with zipfile.ZipFile(archive_path) as archive:
        for filename, record in records.items():
            name = prefix + filename
            entries = [entry for entry in archive.infolist() if entry.filename == name]
            if len(entries) != 1 or entries[0].file_size > MAX_NOTICE_BYTES:
                raise ValueError('missing, duplicate or oversized JS notice: ' + name)
            data = archive.read(entries[0])
            if data != record['data'] or _sha(data) != record['sourceLicenseSha256']:
                raise ValueError('JS notice differs from pinned package source: ' + name)
            verified[name] = _sha(data)
    return verified
