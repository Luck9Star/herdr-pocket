"""Prepare isolated terminal_view IME instrumentation; never mutate pub cache."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.request


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reference_pubspec(original):
    """The only pubspec transformation performed by ci.prepare."""
    before = '  terminal_view: 0.5.0\n'
    if original.count(before) != 1:
        raise ValueError('Unexpected terminal_view pubspec dependency')
    return original.replace(before, '  terminal_view:\n    path: candidate/reference_terminal_view\n', 1)


def metadata(source):
    source = Path(source)
    result = json.loads((source / 'patches/ime-observation-manifest.json').read_text(encoding='utf-8'))
    combining = json.loads((source / 'patches/manifest.json').read_text(encoding='utf-8'))
    if (result['version'] != '0.5.0' or result['archiveUrl'] != 'https://pub.dev/api/archives/terminal_view-0.5.0.tar.gz' or
            result['archiveSha256'] != combining['archiveSha256'] or
            result['patch'] != 'terminal_view-0.5.0-ime-observation.patch' or
            set(result['files']) != {'lib/src/terminal_view.dart', 'lib/src/ui/custom_text_edit.dart'} or
            set(result['files']) & set(combining['files'])):
        raise ValueError('Unexpected IME source metadata')
    if digest((source / 'patches' / result['patch']).read_bytes()) != result['patchSha256']:
        raise ValueError('IME patch checksum mismatch')
    return result, combining


def apply_shim(target, source):
    target, source = Path(target), Path(source)
    ime, combining = metadata(source)
    for name, hashes in ime['files'].items():
        if digest((target / name).read_bytes()) != hashes['beforeSha256']:
            raise ValueError('Unexpected upstream IME source: ' + name)
    for check in (True, False):
        subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf', 'apply',
                        *(['--check'] if check else []), str(source / 'patches' / ime['patch'])], cwd=target, check=True)
    for name, hashes in ime['files'].items():
        if digest((target / name).read_bytes()) != hashes['afterSha256']:
            raise ValueError('Unexpected patched IME source: ' + name)
    for name, expected in combining['upstreamLicenseFiles'].items():
        if name not in ('LICENSE', 'NOTICE') or digest((target / name).read_bytes()) != expected:
            raise ValueError('Unexpected upstream license file')
    return ime


def prepare_reference(destination, source):
    destination, source = Path(destination), Path(source)
    parent = destination / 'candidate'
    target = parent / 'reference_terminal_view'
    manifest = destination / 'reference-terminal-manifest.json'
    if parent.is_symlink() or target.exists() or target.is_symlink() or manifest.exists() or manifest.is_symlink():
        raise ValueError('Refusing existing reference terminal dependency')
    ime, combining = metadata(source)
    with urllib.request.urlopen(ime['archiveUrl'], timeout=60) as response:
        archive = response.read(64 * 1024 * 1024 + 1)
    if len(archive) > 64 * 1024 * 1024 or digest(archive) != ime['archiveSha256']:
        raise ValueError('Official archive checksum/size mismatch')
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.reference-', dir=parent) as tmp:
        staging = Path(tmp) / 'package'
        staging.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as bundle:
            members = bundle.getmembers()
            if any(not (m.isfile() or m.isdir()) for m in members) or sum(m.size for m in members) > 64 * 1024 * 1024:
                raise ValueError('Unexpected archive contents')
            names = [m.name for m in members]
            if len(names) != len(set(names)):
                raise ValueError('Duplicate archive member')
            bundle.extractall(staging, filter='data')
        # Prove the reference retains the original renderer/core, independently
        # of the two widget files modified by the observation shim.
        for name, hashes in combining['files'].items():
            if digest((staging / name).read_bytes()) != hashes['beforeSha256']:
                raise ValueError('Unexpected reference renderer/core: ' + name)
        apply_shim(staging, source)
        staging.rename(target)
    record = {'variant': 'reference-renderer-with-ime-observation', 'imeObservation': ime,
              'upstreamLicenseFiles': combining['upstreamLicenseFiles'],
              'rendererCore': 'original pinned archive; IME shim applies to widget files only'}
    manifest.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record
