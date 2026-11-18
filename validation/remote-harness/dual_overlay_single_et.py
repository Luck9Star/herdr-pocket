#!/usr/bin/env python3
"""Run the existing EasyTier-only control in the dual job's sealed namespace.

This is an independent, read-only control: the original probe and four cases
are unchanged. Its namespace check is replaced only in this process by the
strict lo + unconnected TEST-NET /32 dummy and local-route allowlist.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import dual_overlay_loopback as dual
import easytier_loopback as et


def run(bundle, output):
    root = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    expected = root / ('hp-easytier-bundle-' + os.environ['GITHUB_RUN_ID']) / 'single-et'
    if bundle.is_symlink() or bundle.resolve(strict=True) != expected.resolve(strict=True):
        raise et.Failure('single_bundle_path_invalid')
    dual.check_current_namespace()
    report = et.initial_report()
    report['scope'] = ('Linux isolated namespace; EasyTier only, real product OverlayDialer and '
                       'SSH/herdr read-only; one unconnected TEST-NET dummy')
    report['isolatedNamespace'] = True
    report['testOnlyDummy'] = True
    report['noExternalRoutes'] = True
    try:
        # Its ordinary entry point keeps its lo-only default. This wrapper
        # explicitly rechecks the stricter dummy/address/route allowlist.
        et.run(bundle, output, report,
               namespace_check=lambda _links: dual.check_current_namespace(), loopback_only=False)
    except Exception as error:
        report['status'] = 'failed'
        report['errorCode'] = (str(error) if isinstance(error, et.Failure)
                               else 'controlled_timeout' if isinstance(error, et.subprocess.TimeoutExpired)
                               else 'invalid_controlled_json' if isinstance(error, json.JSONDecodeError)
                               else 'unexpected_runner_error')
    finally:
        report['loopbackOnlyNamespace'] = False
        et.write_json(output / 'manifest.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        report = run(args.bundle, args.output)
    except Exception as error:
        report = {'status': 'failed', 'stage': 'precondition',
                  'errorCode': str(error) if isinstance(error, et.Failure) else 'unexpected_runner_error'}
        et.write_json(args.output / 'manifest.json', report)
    print(json.dumps({'status': report['status'], 'stage': report.get('stage'),
                      'errorCode': report.get('errorCode')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
