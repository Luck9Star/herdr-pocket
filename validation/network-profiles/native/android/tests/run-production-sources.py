#!/usr/bin/env python3
"""Exercise the actual Gradle source sync, then compile its exact Java closure.

Requires an existing local Gradle distribution; never downloads tools or uses an
Android SDK. The Gradle fixture models only the source-set/task interfaces.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SOURCES = (
    'AndroidEasyTierConfig.java', 'AndroidNetworkEnvelope.java',
    'AndroidNetworkSecretStore.java', 'AndroidTailscaleConfig.java',
    'AndroidTailscaleEnvelope.java', 'AndroidTailscaleStateStore.java',
    'AndroidZeroTierDeviceService.java', 'AndroidZeroTierDeviceStore.java',
    'AndroidZeroTierEnvelope.java', 'AndroidZeroTierNative.java',
    'EasyTierConfigBuilder.java', 'NetworkSecretStoreCore.java',
    'TailscaleStateStoreCore.java', 'ZeroTierDeviceStoreCore.java',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gradle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    gradle = args.gradle.resolve(strict=True)
    here = Path(__file__).resolve().parent
    source = here.parent
    manifest = 'android-production-sources.txt'
    for name in (*SOURCES, manifest, 'network-secrets.gradle'):
        path = source / name
        assert not path.is_symlink() and path.is_file(), f'non-regular production input: {name}'
    assert (source / manifest).read_text().splitlines() == list(SOURCES)
    report = {'schemaVersion': 1, 'scope': 'offline Gradle Sync + desktop JVM/Android stubs',
              'productionSources': list(SOURCES), 'jniCandidateIncluded': True,
              'sourceSHA256': {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                               for name in (*SOURCES, manifest, 'network-secrets.gradle')}, 'checks': []}
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='herdr-java-production-', dir='/private/tmp') as temp:
        root = Path(temp)
        shared = root / 'input'
        shared.mkdir()
        for name in (*SOURCES, manifest, 'network-secrets.gradle'):
            shutil.copyfile(source / name, shared / name)
        # A future top-level draft must not silently enter the Android bundle.
        (shared / 'OtherDraft.java').write_text('NOT VALID JAVA; MUST NOT COMPILE')
        (shared / 'tests').mkdir()
        (shared / 'tests' / 'Accidental.java').write_text('NOT VALID JAVA')
        project = root / 'project'
        project.mkdir()
        shutil.copyfile(here / 'production-sources.gradle', project / 'build.gradle')
        (project / 'settings.gradle').write_text("rootProject.name='herdr-metadata-source-boundary'\n")
        home = root / 'home'
        home.mkdir()
        env = {'HOME': str(home), 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'TMPDIR': str(root), 'LANG': 'en_US.UTF-8'}
        if os.environ.get('JAVA_HOME'):
            env['JAVA_HOME'] = os.environ['JAVA_HOME']
        command = [str(gradle), '--offline', '--no-daemon', '--console=plain',
                   '-g', str(root / 'gradle-home'), '-p', str(project),
                   '-PsharedSourceDir=' + str(shared)]
        count = 0

        def run(command, *, succeeds=True):
            nonlocal count
            count += 1
            result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=180)
            (args.output / f'{count:02d}.log').write_text(result.stdout)
            if (result.returncode == 0) != succeeds:
                raise AssertionError(f'command {count} unexpected exit {result.returncode}: {result.stdout[-2000:]}')
            return result.stdout

        tasks = ['preBuild', 'compileUniversalDebugKotlin', 'compileUniversalDebugJavaWithJavac']
        generated = project / 'build/generated/herdr-network-sources'

        def verify_sync():
            actual = {str(path.relative_to(generated)) for path in generated.rglob('*') if path.is_file()}
            assert actual == set(SOURCES), actual
            for name in SOURCES:
                assert (generated / name).read_bytes() == (source / name).read_bytes()

        run(command + tasks)
        verify_sync()
        report['checks'].append('all 14 checked files copied exactly; invalid top-level draft and nested tests excluded')
        (generated / 'stale/android').mkdir(parents=True)
        (generated / 'stale/android/Old.java').write_text('NOT VALID JAVA')
        rerun = run(command + tasks)
        verify_sync()
        assert '> Task :syncHerdrNetworkSources\n' in rerun
        report['checks'].append('unchanged-input rerun executes Sync and removes stale nested sources')
        # Every production input is validated before compiling, not merely copied if present.
        for name in SOURCES:
            data = (shared / name).read_bytes()
            (shared / name).unlink()
            failure = run(command + ['help'], succeeds=False)
            assert 'missing a required production source' in failure
            (shared / name).write_bytes(data)
        report['checks'].append('each of 14 missing inputs rejected during Gradle configuration')
        original_manifest = (shared / manifest).read_bytes()
        for invalid in ('', '\n', '../Outside.java\n', 'tests/Nested.java\n',
                        'NotJava.txt\n', 'One.java\nOne.java\n', ' One.java\n'):
            (shared / manifest).write_text(invalid)
            failure = run(command + ['help'], succeeds=False)
            assert 'invalid Android production source manifest' in failure
        (shared / manifest).unlink()
        failure = run(command + ['help'], succeeds=False)
        assert 'missing its production source manifest' in failure
        (shared / manifest).write_bytes(original_manifest)
        report['checks'].append('manifest missing/empty/blank/path/non-Java/duplicate/whitespace input rejected')
        # Valid content outside the shared directory still cannot be a source.
        # Invoke Sync itself: rejection must occur before copying external bytes.
        for name, message in (
            (manifest, 'source manifest must not be a symbolic link'),
            (SOURCES[0], 'sources must not be symbolic links'),
        ):
            original = (shared / name).read_bytes()
            external = root / ('outside-' + name)
            external.write_bytes(original)
            (shared / name).unlink()
            (shared / name).symlink_to(external)
            failure = run(command + ['syncHerdrNetworkSources'], succeeds=False)
            assert message in failure
            assert '> Task :syncHerdrNetworkSources' not in failure
            verify_sync()
            (shared / name).unlink()
            (shared / name).write_bytes(original)
        report['checks'].append('valid manifest/source symlinks outside shared directory rejected before Sync; generated bytes unchanged')
        stub = here / 'zerotier-stubs'
        stubs = sorted(str(path) for path in stub.rglob('*.java'))
        android_stubs = source.parents[2] / 'android-network-source/tests/java/android'
        stubs += [str(android_stubs / name) for name in
                  ('os/Process.java', 'system/Os.java', 'system/OsConstants.java', 'system/StructStat.java')]
        classes = root / 'classes'
        run(['javac', '-d', str(classes), *stubs,
             *(str(generated / name) for name in SOURCES), str(here / 'ProductionSliceTest.java')])
        proof = run(['java', '-cp', str(classes), 'org.herdr.network.ProductionSliceTest'])
        assert 'PASS production slice' in proof
        report['checks'].append('exact synced closure compiles including the unbound JNI bridge; unbound service status and all five writes fail closed')
        report['commandCount'] = count
    report['passed'] = True
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
