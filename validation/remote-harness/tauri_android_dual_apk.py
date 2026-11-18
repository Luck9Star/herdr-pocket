#!/usr/bin/env python3
"""Verify x86_64 QA APK contains the independently verified native bytes."""
import argparse
import hashlib
from pathlib import Path
import tempfile
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native/tool'))
import android_bundle
import android_tailscale

APP = 'libherdr_pocket_tauri_probe_lib.so'
PROVIDERS = ('libheeler_easytier.so', 'libhp_tailscale.so')


def verify(apk, qa, readelf):
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        libs = [name for name in names if name.startswith('lib/') and name.endswith('.so')]
        if not libs or any(not name.startswith('lib/x86_64/') for name in libs) or len(libs)!=len(set(libs)):
            raise ValueError('dual_apk_abi_invalid')
        for name in (*PROVIDERS, APP):
            if libs.count('lib/x86_64/'+name) != 1:
                raise ValueError('dual_apk_library_missing')
        for name in PROVIDERS:
            if hashlib.sha256(archive.read('lib/x86_64/'+name)).digest()!=hashlib.sha256((qa/name).read_bytes()).digest():
                raise ValueError('dual_apk_provider_hash_mismatch')
        with tempfile.TemporaryDirectory(prefix='dual-apk-elf-') as directory:
            for name in (*PROVIDERS, APP):
                output=Path(directory)/name
                output.write_bytes(archive.read('lib/x86_64/'+name))
                if name==APP:
                    android_bundle.elf(output,readelf,required=[android_bundle.BIND_NATIVE,android_tailscale.JNI_BIND],
                        needed=list(PROVIDERS),abi='x86_64')
                elif name==android_tailscale.LIBRARY:
                    android_bundle.elf(output,readelf,required=android_tailscale.SYMBOLS,abi='x86_64')
                else:
                    android_bundle.elf(output,readelf,required=android_bundle.SYMBOLS,abi='x86_64')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--qa',type=Path,required=True);parser.add_argument('--readelf',required=True)
    args=parser.parse_args();verify(args.apk,args.qa,args.readelf)
