#!/usr/bin/env python3
"""Mac-only offline JNI identity -> real device service/store, no node/network.

Requires a clean accepted native source export and a fully verified candidate
work prepared by its normal tool. Never downloads or changes either input.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-root', type=Path, required=True,
                        help='validation/native from the accepted clean source export')
    parser.add_argument('--work', type=Path, required=True,
                        help='normal prepare/apply/verify-candidate work, never a device directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
        parser.error('output must be a fresh file in an existing directory')
    if any(args.output.resolve().is_relative_to(path.resolve()) for path in (args.work, args.native_root)):
        parser.error('output must stay outside both immutable source inputs')
    report = {'passed':False, 'macOS':platform.system() == 'Darwin', 'sourceVerified':False,
              'nativeBuildPassed':False, 'javaBuildPassed':False, 'jvmExited':False,
              'temporaryTreeRemoved':False, 'androidAbi':False, 'fakeAndroidKeyStore':True,
              'nodeStarted':False, 'streamsCompiled':False, 'sourceHashes':{}}
    temporary = None
    try:
        if not report['macOS']:
            raise ValueError('Mac only')
        native = args.native_root.resolve(strict=True)
        # Use the full accepted preparation/verification path, including manager
        # inputs, even though this test links only identity translation units.
        for name in ('zerotier-runtime-source.json', 'zerotier-candidate.json', 'tool/zerotier_candidate.py'):
            if sha(native / name) != sha(REPO / 'validation/native' / name):
                raise ValueError('accepted source anchor changed')
        manifest = json.loads((native / 'zerotier-candidate.json').read_text())
        if [Path(row['path']).name for row in manifest['patches']] != [
                '0005-native-safety.patch', '0006-strict-offline-identity.patch', '0007-defined-ecc-shifts.patch']:
            raise ValueError('unexpected candidate patch set')
        spec = importlib.util.spec_from_file_location('accepted_zt_candidate', native / 'tool/zerotier_candidate.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        verified = helper.verify_candidate(args.work.resolve(strict=True))
        report['sourceVerified'] = True
        report['verifiedSourceFiles'] = verified['verifiedFiles']
        tree = args.work.resolve() / 'libzt'
        android = REPO / 'validation/network-profiles/native/android'
        crypto = [tree / 'ext/ZeroTierOne/node' / (name + '.cpp')
                  for name in ('Identity', 'ECC', 'Salsa20', 'SHA512', 'Utils')]
        native_sources = [*crypto, tree / 'src/hp_zt_identity.cpp', HERE / 'identity_bridge.cpp']
        java_sources = [android / name for name in ('ZeroTierDeviceStoreCore.java',
            'AndroidZeroTierEnvelope.java', 'AndroidZeroTierDeviceStore.java', 'AndroidZeroTierDeviceService.java',
            'tests/ZeroTierAndroidStoreTest.java')]
        java_sources += sorted((android / 'tests/zerotier-stubs').rglob('*.java'))
        java_sources += [HERE / 'IdentityBridge.java', HERE / 'DeviceIdentityServiceProbe.java']
        for path in [*native_sources, tree / 'src/hp_zt.h', *java_sources,
                     native / 'zerotier-candidate.json', native / 'zerotier-runtime-source.json',
                     native / 'tool/zerotier_candidate.py', HERE / 'run.py']:
            if path.is_relative_to(REPO):
                label = path.relative_to(REPO).as_posix()
            elif path.is_relative_to(tree):
                label = 'verified-candidate/' + path.relative_to(tree).as_posix()
            else:
                label = 'accepted-native/' + path.relative_to(native).as_posix()
            report['sourceHashes'][label] = sha(path)
        java = Path(shutil.which('java')).resolve()
        launch_env = {'PATH':'/usr/bin:/bin', 'LANG':'C', 'LC_ALL':'C'}
        if os.environ.get('JAVA_HOME'):
            launch_env['JAVA_HOME'] = os.environ['JAVA_HOME']
        properties = subprocess.run([str(java), '-XshowSettings:properties', '-version'], env=launch_env,
                                    capture_output=True, text=True, check=True, timeout=15)
        java_home = Path(re.search(r'^\s*java.home = (.+)$', properties.stderr, re.M).group(1))
        # The macOS /usr/bin/java launcher may depend on ambient JAVA_HOME.
        # Invoke the resolved JDK directly after stripping the ambient process environment.
        java = java_home / 'bin/java'
        includes = [tree / 'src', tree / 'ext/ZeroTierOne', tree / 'ext/ZeroTierOne/node',
                    java_home / 'include', java_home / 'include/darwin']
        for header in ('jni.h', 'darwin/jni_md.h'):
            report['sourceHashes']['JDK/include/' + header] = sha(java_home / 'include' / header)
        with tempfile.TemporaryDirectory(prefix='herdr-real-zt-identity-') as directory:
            temporary = Path(directory)
            env = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin', 'HOME':directory, 'TMPDIR':directory,
                   'LANG':'C', 'LC_ALL':'C'}
            library = temporary / 'identity-jni.dylib'
            exports = ['hp_zt_abi_version', 'hp_zt_identity_create', 'hp_zt_identity_validate',
                       'Java_org_herdr_network_IdentityBridge_create', 'Java_org_herdr_network_IdentityBridge_validateBytes']
            command = [shutil.which('clang++'), '-std=c++11', '-O2', '-dynamiclib', '-fvisibility=hidden',
                       '-DZT_SDK=1', *[item for path in includes for item in ('-I', str(path))],
                       *map(str, native_sources), *['-Wl,-exported_symbol,_' + name for name in exports],
                       '-o', str(library)]
            subprocess.run(command, env=env, capture_output=True, check=True, timeout=180)
            symbols = subprocess.run(['/usr/bin/nm', '-gU', str(library)], env=env,
                                     capture_output=True, text=True, check=True, timeout=15).stdout
            found = {line.split()[-1].removeprefix('_') for line in symbols.splitlines() if line.split()}
            if found != set(exports):
                raise ValueError('unexpected native exports')
            report['nativeBuildPassed'] = True
            report['compiledNativeFiles'] = len(native_sources)
            report['identityOnlyExports'] = True
            classes = temporary / 'classes'
            classes.mkdir()
            subprocess.run([str(java_home / 'bin/javac'), '-d', str(classes), *map(str, java_sources)],
                           env=env, capture_output=True, check=True, timeout=90)
            report['javaBuildPassed'] = True
            result = subprocess.run([str(java), '-Xcheck:jni', '--enable-native-access=ALL-UNNAMED',
                '-Djava.awt.headless=true', '-Dhp.identity.library=' + str(library), '-cp', str(classes),
                'org.herdr.network.DeviceIdentityServiceProbe', str(temporary / 'device')],
                env=env, capture_output=True, text=True, timeout=180)
            report['jvmExited'] = True
            report['jvmExitCode'] = result.returncode
            if result.returncode:
                report['jvmAssertionFailed'] = 'AssertionError' in result.stderr
                report['jvmNativeLinkError'] = 'UnsatisfiedLinkError' in result.stderr
                report['jvmNativeGenerationError'] = 'identity_fixture_failed' in result.stderr
                line = re.search(r'DeviceIdentityServiceProbe.main\(DeviceIdentityServiceProbe.java:(\d+)\)', result.stderr)
                if line:
                    report['failedJavaLine'] = int(line.group(1))
                raise ValueError('bounded JVM failure')
            value = json.loads(result.stdout)
            expected = {'passed', 'checks', 'nativeCreates', 'nativeValidations', 'encryptedAtRest',
                'freshReaderMatched', 'tamperRejected', 'wrongInstanceRejected', 'explicitlyRemoved',
                'buffersCleared', 'keyStoreEmpty', 'temporaryRootRemoved'}
            if (set(value) != expected or any(type(item) not in (bool, int) for item in value.values())
                    or not value['passed'] or value['nativeCreates'] != 1 or value['nativeValidations'] < 3
                    or any(value[key] is not True for key in expected - {'checks','nativeCreates','nativeValidations'})):
                raise ValueError('invalid bounded result')
            report['identityService'] = value
            report['passed'] = True
    except Exception:
        # Runtime diagnostics may contain key operands. Never persist or print
        # stderr, exception strings, identity bytes, handles or node addresses.
        report['passed'] = False
    finally:
        report['temporaryTreeRemoved'] = temporary is None or not temporary.exists()
        report['passed'] = report['passed'] and report['temporaryTreeRemoved']
        with args.output.open('x') as output:
            output.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
