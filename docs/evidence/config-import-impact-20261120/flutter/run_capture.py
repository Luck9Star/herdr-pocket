#!/usr/bin/env python3
"""Render baseline and candidate from committed Flutter sources on an isolated test surface."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tarfile


def capture_command(argv, *, cwd=None, env=None):
    return subprocess.check_output(argv, cwd=cwd, env=env)


def run_logged(argv, cwd, env, log, *, check=True):
    log.write(('$ ' + ' '.join(map(str, argv)) + '\n').encode())
    log.flush()
    return subprocess.run(argv, cwd=cwd, env=env, check=check, stdout=log, stderr=subprocess.STDOUT).returncode


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_commit(repo, ref):
    return capture_command(['git', '-C', str(repo), 'rev-parse', '--verify', ref + '^{commit}']).decode().strip()


def run_variant(args, name, commit, env):
    source = args.output / ('source-' + name)
    project = args.output / ('app-' + name)
    result = args.output / name
    source.mkdir()
    result.mkdir()
    env = dict(env, GITHUB_SHA=commit, CAPTURE_SOURCE=commit, CAPTURE_OUT=str(result), CAPTURE_VARIANT=name)
    exported = capture_command(['git', '-C', str(args.repo), 'archive', commit, 'validation'])
    with tarfile.open(fileobj=io.BytesIO(exported)) as archive:
        archive.extractall(source, filter='data')
    with (result / 'flutter-test.log').open('wb') as log:
        run_logged(['python3', 'validation/flutter/tool/ci.py', 'prepare', '--destination', str(project)],
                   source, env, log)
        replay = Path(__file__).with_name('capture_test.dart')
        (project / 'test' / 'config_import_impact_capture_test.dart').write_bytes(replay.read_bytes())
        run_logged(['flutter', 'pub', 'get', '--offline'], project, env, log)
        test_status = run_logged(['flutter', 'test', '--no-pub', '--reporter', 'expanded',
                    'test/config_import_impact_capture_test.dart'], project, env, log, check=False)
    print(name, 'Flutter exit', test_status, flush=True)
    facts = json.loads((result / 'render-facts.json').read_text())
    log_text = (result / 'flutter-test.log').read_text()
    diagnoses = []
    framework_exceptions = log_text.split('EXCEPTION CAUGHT BY ')[1:]
    for block in framework_exceptions:
        overflow = re.search(
            r"^RENDERING LIBRARY.*?A RenderFlex overflowed by ([\d.]+) pixels on the right\..*?"
            r"DropdownButtonFormField<ConfigImportAction>-\[<'(transfer-choice-[01])'>\]",
            block, flags=re.S)
        if overflow is not None:
            px, control = overflow.groups()
            diagnoses.append({'phase':'a-replace' if control.endswith('0') else 'b-replace',
                              'control':control, 'rightOverflowPx':float(px)})
    if test_status == 0:
        assert framework_exceptions == []
    else:
        assert name == 'before' and test_status == 1 and diagnoses
        assert len(framework_exceptions) == len(diagnoses) + 1
        assert framework_exceptions[-1].startswith('FLUTTER TEST FRAMEWORK')
        assert 'Flutter must report zero rendering errors (baseline known negative)' in framework_exceptions[-1]
    facts['flutterExitCode'] = test_status
    facts['layoutDiagnostics'] = diagnoses
    facts['syntheticArchiveSha256'] = digest(result / 'synthetic-archive.hpkt')
    images = list(facts['states'].values()) + [
        event['controlFrame'] for event in facts['interactions'] if 'controlFrame' in event]
    for state in images:
        path = result / state['png']
        with path.open('rb') as stream:
            header = stream.read(24)
        if header[:16] != b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR':
            raise ValueError('Expected original PNG')
        width, height = struct.unpack('>II', header[16:])
        assert (width, height) == (args.width, args.height)
        state['pngSizePx'] = [width, height]
        state['pngSha256'] = digest(path)
    (result / 'render-facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2) + '\n')
    return facts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--before', required=True)
    parser.add_argument('--after', required=True)
    parser.add_argument('--sdk', required=True, type=Path)
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--width', type=int, default=390)
    parser.add_argument('--height', type=int, default=844)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    icon_font = args.sdk / 'bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf'
    env = dict(os.environ, PATH=str(args.sdk.resolve() / 'bin') + os.pathsep + os.environ['PATH'],
               FLUTTER_SUPPRESS_ANALYTICS='true', PYTHONDONTWRITEBYTECODE='1',
               CAPTURE_FONT=str(args.font.resolve()), CAPTURE_ICON_FONT=str(icon_font.resolve()),
               CAPTURE_WIDTH=str(args.width), CAPTURE_HEIGHT=str(args.height))
    version = json.loads(capture_command(['flutter', '--version', '--machine'], env=env))
    assert (version['frameworkVersion'], version['frameworkRevision']) == (
        '3.47.9', 'c197ca5199e9ee5661e865596c9c07294dfab51c')
    colors = {
        name: run_variant(args, name, source_commit(args.repo, ref), env)
        for name, ref in (('before', args.before), ('after', args.after))
    }
    before, after = colors['before'], colors['after']
    assert before['syntheticArchiveSha256'] == after['syntheticArchiveSha256']
    assert before['viewport'] == after['viewport']
    assert after['layoutDiagnostics'] == []
    if (args.width, args.height) in ((390, 844), (320, 740)):
        assert [(entry['phase'], entry['control']) for entry in before['layoutDiagnostics']] == [
            ('a-replace', 'transfer-choice-0'), ('b-replace', 'transfer-choice-1')]
    assert len(after['interactions']) == len(before['interactions']) == 3
    for old, new in zip(before['interactions'], after['interactions'], strict=True):
        assert [old[key] for key in ('picker', 'option', 'choicesAfterTap')] == [
            new[key] for key in ('picker', 'option', 'choicesAfterTap')]
        assert old['optionGeometryAtTap']['hitTestable'] and new['optionGeometryAtTap']['hitTestable']
        assert new['selectedRendering']['allGlyphsVisible']
        assert new['selectedRendering']['arrowFitsInsidePicker']
        assert new['selectedRendering']['arrowGeometry']['hitTestable']
    for name, state in after['states'].items():
        assert state['choices'] == before['states'][name]['choices']
        assert state['bodyViewport'] == before['states'][name]['bodyViewport']
    manifest = {'syntheticArchiveSha256':after['syntheticArchiveSha256'],
                'fontSha256':digest(args.font), 'fontName':args.font.name,
                'materialIconsSha256':digest(icon_font),
                'flutterFramework':version['frameworkRevision'], 'flutterEngine':version['engineRevision'],
                'before':before, 'after':after}
    (args.output / 'comparison.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(args.output / 'comparison.json')


if __name__ == '__main__':
    main()
