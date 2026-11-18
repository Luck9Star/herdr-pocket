#!/usr/bin/env python3
"""CI-only package/evidence checks for the two-shell iOS acceptance batch.

This does not drive SSH, evaluate terminal pixels, or establish device support.
The corresponding simulator runners own those checks and their sanitization.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess


class BatchFailure(RuntimeError):
    pass


TERMINAL_PROOFS = {'ordinary-terminal.png': 'ordinary-terminal-ocr.json',
                   'key-change-terminal.png': 'key-change-terminal-ocr.json'}
REQUIRED_IMAGES = {*TERMINAL_PROOFS, 'key-change-review.png'}


def read_public_file(root, name, limit):
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise BatchFailure('ios_batch_public_file_invalid')
    return path.read_bytes()


def read_public_json(root, name):
    data = read_public_file(root, name, 1_000_000)
    try:
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
    except (UnicodeError, ValueError):
        raise BatchFailure('ios_batch_public_json_invalid') from None
    return data, value


def publish_evidence(root, destination, *, shell, source_sha):
    """Copy only this run's bound public files; leave SSH/OCR to the runners.

    Failed runs may retain an already completed scene. A passed result must
    supply all three original system captures and both accepted OCR reports.
    Even an incomplete passed result retains its sanitized result for diagnosis.
    """
    from PIL import Image
    root, destination = Path(root), Path(destination)
    if root.is_symlink() or not root.is_dir() or destination.exists() or destination.is_symlink():
        raise BatchFailure('ios_batch_public_directory_invalid')
    if shell not in ('flutter', 'tauri') or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise BatchFailure('ios_batch_source_invalid')
    raw, report = read_public_json(root, 'result.json')
    if report.get('sourceSHA') != source_sha or report.get('status') not in ('passed', 'failed'):
        raise BatchFailure('ios_batch_result_source_or_status_invalid')
    destination.mkdir(parents=True)
    (destination / 'result.json').write_bytes(raw)
    passed = report['status'] == 'passed'
    artifacts = report.get('artifacts', {})
    allowed = REQUIRED_IMAGES | ({'preconnect.png'} if shell == 'flutter' else set())
    if (not isinstance(artifacts, dict) or set(artifacts) - allowed or
            any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)
                for value in artifacts.values())):
        raise BatchFailure('ios_batch_artifact_manifest_invalid')
    if passed and not REQUIRED_IMAGES.issubset(artifacts):
        raise BatchFailure('ios_batch_required_images_missing')
    published = {'result.json'}
    for name in sorted(allowed):
        if name not in artifacts:
            continue
        try:
            data = read_public_file(root, name, 8_000_000)
            if hashlib.sha256(data).hexdigest() != artifacts[name]:
                raise BatchFailure('ios_batch_image_hash_mismatch')
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'PNG' or image.width * image.height > 16_000_000:
                    raise BatchFailure('ios_batch_image_invalid')
                image.verify()
            proof_name = TERMINAL_PROOFS.get(name)
            if proof_name:
                proof_raw, proof = read_public_json(root, proof_name)
                if proof.get('imageSha256') != artifacts[name]:
                    raise BatchFailure('ios_batch_ocr_image_hash_mismatch')
                if not all(proof.get(key) is True for key in
                           ('markerVisible', 'tokenVisible', 'proofSequenceVisible')):
                    raise BatchFailure('ios_batch_ocr_not_accepted')
                (destination / proof_name).write_bytes(proof_raw)
                published.add(proof_name)
            (destination / name).write_bytes(data)
            published.add(name)
        except (BatchFailure, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            if passed:
                if isinstance(exc, BatchFailure):
                    raise
                raise BatchFailure('ios_batch_image_invalid') from None
            # An incomplete scene is not exported, even if another scene passed.
            continue
    return published


def select_simulator_app(root, *, command=subprocess.run):
    """Select the actual unsigned arm64 simulator app inside Tauri's archive."""
    root = Path(root).resolve(strict=True)
    candidates = []
    for app in root.glob('**/*.xcarchive/Products/Applications/*.app'):
        if app.is_symlink() or not app.is_dir() or not app.resolve().is_relative_to(root):
            raise BatchFailure('ios_batch_app_path_invalid')
        try:
            info_path = app / 'Info.plist'
            if info_path.is_symlink():
                raise ValueError('symlink')
            info = plistlib.loads(info_path.read_bytes())
        except (OSError, ValueError, plistlib.InvalidFileException):
            raise BatchFailure('ios_batch_app_plist_invalid') from None
        if info.get('CFBundleIdentifier') == 'dev.herdrpocket.tauriprobe':
            candidates.append((app, info))
    if len(candidates) != 1:
        raise BatchFailure('ios_batch_app_not_unique')
    app, info = candidates[0]
    name = info.get('CFBundleExecutable')
    if (info.get('CFBundleSupportedPlatforms') != ['iPhoneSimulator'] or
            info.get('CFBundlePackageType') != 'APPL' or
            not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name)):
        raise BatchFailure('ios_batch_app_not_simulator')
    binary = app / name
    if binary.is_symlink() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise BatchFailure('ios_batch_app_executable_missing')
    try:
        arch = command(['xcrun', 'lipo', '-archs', str(binary)], check=True,
                       capture_output=True, text=True, timeout=30).stdout.strip()
        build = command(['xcrun', 'vtool', '-show-build', str(binary)], check=True,
                        capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        raise BatchFailure('ios_batch_app_binary_inspection_failed') from None
    if arch != 'arm64' or not re.search(r'^\s*platform\s+(?:IOSSIMULATOR|7)\s*$', build, re.M):
        raise BatchFailure('ios_batch_app_binary_not_arm64_simulator')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    select = sub.add_parser('select-app')
    select.add_argument('--root', required=True)
    publish = sub.add_parser('publish')
    publish.add_argument('--root', required=True)
    publish.add_argument('--destination', required=True)
    publish.add_argument('--shell', required=True, choices=('flutter', 'tauri'))
    publish.add_argument('--source-sha', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'select-app':
            print(select_simulator_app(args.root))
        elif args.action == 'publish':
            names = publish_evidence(args.root, args.destination, shell=args.shell, source_sha=args.source_sha)
            print('Verified public files: ' + ', '.join(sorted(names)))
            if read_public_json(Path(args.destination), 'result.json')[1]['status'] != 'passed':
                raise BatchFailure('ios_batch_runner_reported_failure')
    except (BatchFailure, OSError) as exc:
        raise SystemExit(str(exc) if isinstance(exc, BatchFailure) else 'ios_batch_path_unavailable') from None


if __name__ == '__main__':
    main()
