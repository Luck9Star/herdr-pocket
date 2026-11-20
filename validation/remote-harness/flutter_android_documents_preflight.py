#!/usr/bin/env python3
"""Read-only production APK semantics preflight on the exclusively owned API35 AVD."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
LABELS = ('设置', '终端字号', '加密导出／导入公开主机资料', '加密迁移公开配置',
          '打开加密文件', '加密并另存所选公开资料', '我已核对范围与冲突。迁移不带入信任、身份或授权，替换会停止相关连接。')
# Flutter Widget semantics combines the two visible settings labels on the empty home.
# Android's actual mapping is still checked at runtime, never inferred from this fixture.
LABEL_VARIANTS = {'设置': {'设置', '设置\n设置'}}
SCRATCH = '/data/local/tmp/herdr-documents-preflight.xml'


class Failure(Exception):
    pass


def command(*args, timeout=30):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise Failure('command_unavailable') from None
    if p.returncode or len(p.stdout) > 160_000_000 or len(p.stderr) > 1_000_000:
        raise Failure('command_failed')
    return p.stdout


def adb(*args, timeout=30):
    return command('adb', '-s', SERIAL, *args, timeout=timeout)


def inventory(raw):
    if len(raw) > 1_000_000:
        raise Failure('hierarchy_oversize')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise Failure('hierarchy_invalid') from None
    nodes = list(root.iter('node'))
    parents = {child: parent for parent in root.iter() for child in parent}
    result = {}
    for label in LABELS:
        labels = LABEL_VARIANTS.get(label, {label})
        matches = [n for n in nodes if n.get('package') == PACKAGE and
                   (n.get('text') in labels or n.get('content-desc') in labels)]
        candidates = []
        for node in matches:
            current = node
            while current is not None and current.get('package') == PACKAGE:
                if current.get('clickable') == 'true' and current.get('enabled') == 'true':
                    candidates.append(current)
                    break
                current = parents.get(current)
        unique = list(dict.fromkeys(candidates))
        result[label] = {'matches': len(matches), 'clickableAncestors': len(unique)}
        if len(matches) == len(unique) == 1:
            bounds = unique[0].get('bounds', '')
            m = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
            if m:
                l, t, r, b = map(int, m.groups())
                if 0 <= l < r <= 4096 and 0 <= t < b <= 4096:
                    result[label]['bounds'] = [l, t, r, b]
    return result


def foreground():
    value = adb('shell', 'dumpsys', 'window', 'displays').decode('utf-8', 'replace')
    return bool(re.search(r'mCurrentFocus\s*=\s*Window\{[^\n}]*\bu0\s+' + re.escape(PACKAGE) + r'/', value))


def hierarchy():
    if not foreground():
        raise Failure('foreground_unconfirmed')
    adb('shell', 'test', '!', '-e', SCRATCH)
    adb('shell', 'test', '!', '-L', SCRATCH)
    adb('shell', 'uiautomator', 'dump', SCRATCH, timeout=20)
    try:
        raw = adb('exec-out', 'cat', SCRATCH)
    finally:
        adb('shell', 'rm', '-f', SCRATCH)
        adb('shell', 'test', '!', '-e', SCRATCH)
        adb('shell', 'test', '!', '-L', SCRATCH)
    if not foreground():
        raise Failure('foreground_changed')
    return inventory(raw)


def tap_unique(state, label):
    node = state[label]
    if node['matches'] != 1 or node['clickableAncestors'] != 1 or 'bounds' not in node:
        raise Failure('target_unconfirmed')
    # Require a second matching observation before a single, non-replayed tap.
    if hierarchy()[label] != node:
        raise Failure('target_unstable')
    l, t, r, b = node['bounds']
    adb('shell', 'input', 'tap', str((l + r) // 2), str((t + b) // 2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apk', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    env = os.environ
    temp = Path(env.get('RUNNER_TEMP', '/nonexistent')).resolve()
    apk = Path(args.apk).resolve()
    output = Path(args.output).resolve()
    if (env.get('GITHUB_ACTIONS') != 'true' or not env.get('GITHUB_REF', '').startswith('refs/heads/codex/')
            or not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))
            or not apk.is_relative_to(temp) or not output.is_relative_to(temp) or output == temp):
        raise Failure('unsafe_runner')
    if not apk.is_file() or apk.is_symlink():
        raise Failure('apk_unconfirmed')
    app = temp / 'documents-app'
    try:
        marker = json.loads((app / '.herdr-generated-probe.json').read_text())
        candidate = json.loads((app / 'candidate-manifest.json').read_text())
    except (OSError, ValueError):
        raise Failure('source_unconfirmed') from None
    if (marker.get('kind') != 'herdr-flutter-validation' or marker.get('sourceCommit') != env['GITHUB_SHA']
            or candidate.get('sourceCommit') != env['GITHUB_SHA']
            or apk != app / 'build/app/outputs/flutter-apk/app-debug.apk'):
        raise Failure('source_unconfirmed')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'schemaVersion': 1, 'sourceSHA': env['GITHUB_SHA'], 'stage': 'preflight',
              'status': 'failed', 'checkpoints': {}, 'cleanup': 'not_attempted'}
    installed = False
    try:
        devices = command('adb', 'devices').decode().splitlines()[1:]
        if [line.split() for line in devices if line.strip()] != [[SERIAL, 'device']]:
            raise Failure('device_unconfirmed')
        if (adb('shell', 'getprop', 'ro.kernel.qemu').strip() != b'1' or
                adb('shell', 'getprop', 'ro.build.version.sdk').strip() != b'35' or
                adb('shell', 'am', 'get-current-user').strip() != b'0'):
            raise Failure('device_unconfirmed')
        if adb('shell', 'pm', 'list', 'packages', PACKAGE).strip():
            raise Failure('package_already_present')
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
        report['apkSha256'] = digest
        installed = True  # cleanup also runs if installation outcome is unknown
        adb('install', str(apk), timeout=120)
        paths = adb('shell', 'pm', 'path', PACKAGE).decode().splitlines()
        if len(paths) != 1 or not re.fullmatch(r'package:/data/app/[A-Za-z0-9_./=+~ -]+/base\.apk', paths[0]):
            raise Failure('installed_path_unconfirmed')
        installed_digest = hashlib.sha256(adb('exec-out', 'cat', paths[0][8:], timeout=60)).hexdigest()
        if installed_digest != digest:
            raise Failure('installed_hash_mismatch')
        report['installedHashMatched'] = True
        adb('shell', 'am', 'start', '-n', PACKAGE + '/.MainActivity')
        for _ in range(30):
            if foreground():
                break
            time.sleep(1)
        else:
            raise Failure('foreground_unconfirmed')
        for stage, label in [('home', '设置'), ('settings', '加密导出／导入公开主机资料')]:
            report['stage'] = stage
            for _ in range(15):
                state = hierarchy()
                report['checkpoints'][stage] = state
                if state[label]['matches']:
                    break
                time.sleep(1)
            tap_unique(state, label)
            time.sleep(2)
        report['stage'] = 'transfer'
        report['checkpoints']['transfer'] = hierarchy()
        if report['checkpoints']['transfer']['加密迁移公开配置']['matches'] != 1:
            raise Failure('transfer_unconfirmed')
        report['status'] = 'passed'
    except Failure as error:
        report['error'] = str(error)
    except Exception:
        report['error'] = 'unexpected_failure'
    finally:
        if installed:
            try:
                adb('uninstall', PACKAGE, timeout=60)
                if adb('shell', 'pm', 'list', 'packages', PACKAGE).strip():
                    raise Failure('cleanup_failed')
                report['cleanup'] = 'package_absent'
            except Failure:
                report['cleanup'] = 'unconfirmed'
                report['status'] = 'failed'
        (output / 'flutter-documents-preflight.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
