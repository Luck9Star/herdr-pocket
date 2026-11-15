#!/usr/bin/env python3
"""Install or verify the independently checked Android x86_64 QA libraries."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

LIBRARIES = ('libheeler_easytier.so', 'libhp_tailscale.so', 'libherdr_flutter_network_runtime.so')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sources(bundle):
    root = Path(bundle)
    result = {}
    for name in LIBRARIES:
        source = root / name
        if source.is_symlink() or not source.is_file():
            raise ValueError('native_library_missing')
        result[name] = source.read_bytes()
    return result


def install(bundle, project):
    libraries = sources(bundle)
    root = Path(project) / 'android/app/src/main/jniLibs'
    if root.is_symlink() or (root.exists() and any(root.iterdir())):
        raise ValueError('unexpected_existing_native_libraries')
    destination = root / 'x86_64'
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in libraries.items():
        (destination / name).write_bytes(data)
    return {name: digest(data) for name, data in libraries.items()}


def verify(bundle, apk):
    libraries = sources(bundle)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('apk_duplicate_entries')
        for name, expected in libraries.items():
            path = 'lib/x86_64/' + name
            if path not in names or digest(archive.read(path)) != digest(expected):
                raise ValueError('apk_native_library_mismatch')
        abis = {item.split('/')[1] for item in names if item.startswith('lib/') and item.count('/') >= 2}
        if abis != {'x86_64'}:
            raise ValueError('apk_abi_mismatch')
    return {'abi': 'x86_64', 'apkSha256': digest(Path(apk).read_bytes()),
            'libraries': {name: digest(data) for name, data in libraries.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'verify'))
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    if args.action == 'install' and args.project:
        result = install(args.bundle, args.project)
    elif args.action == 'verify' and args.apk:
        result = verify(args.bundle, args.apk)
    else:
        parser.error('missing action argument')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
