#!/usr/bin/env python3
"""Local AppKit/real Flutter codec probe. No visible window or system AX claim."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

CHECKS = {'channelRetired', 'clearDoesNotChangeOtherField', 'clearIsEmpty',
    'clearedFieldCanFocusAgain', 'disabledLateEditCannotRestore', 'emptyFieldCanFocus',
    'emptySyncPreservesFocus', 'identifierPreserved', 'labelPreserved',
    'metadataKeepsCurrentValue', 'nativeEditingReachedFlutterWire', 'nativeValueMatchesEdits',
    'rebuiltFieldStartsEmpty', 'reenableStaysEmpty', 'retireReplied',
    'retiredLateEditCannotRestore', 'nativeSecureRolePublished', 'secureClass',
    'staleSyncCannotRestore', 'nativeSecureSubrolePublished', 'nativeSecureElementPublished', 'syncReplied',
    'inheritedWindowChildPreserved', 'secureWindowChildPresent', 'secureWindowChildUnique',
    'secureWindowParentCorrect', 'windowQueriesPreserveFocus', 'windowQueriesDoNotPublishFocus',
    'focusReachedFlutterWithoutText', 'disabledFieldDoesNotPublishFocus', 'hiddenFieldExcluded',
    'clippedFieldExcluded', 'detachedFieldExcluded', 'reattachedFieldExposed',
    'preexistingSecureChildDeduplicated', 'retiredFieldNotExposed',
    'rebuiltPasswordIsOnlySecureChild', 'closedWindowNoRegisteredSecureChild',
    'closedWindowClearsNativeValue', 'closedWindowRetiresChannel',
    'stagedPassphraseIsNative', 'invalidPairsHaveNoEditorOrChannel'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flutter-sdk', required=True, type=Path)
    args = parser.parse_args()
    framework = args.flutter_sdk / 'bin/cache/artifacts/engine/darwin-x64/FlutterMacOS.xcframework/macos-arm64_x86_64'
    here = Path(__file__).resolve().parent
    if sys.platform != 'darwin' or not (framework / 'FlutterMacOS.framework').is_dir():
        print('{"passed":false,"stage":"macos_framework_required"}'); return 1
    with tempfile.TemporaryDirectory(prefix='hp-appkit-secure-probe-') as temporary:
        root = Path(temporary); binary = root / 'secure-probe'
        result = subprocess.run(['xcrun', 'swiftc', '-module-cache-path', str(root / 'cache'),
            '-F', str(framework), '-framework', 'FlutterMacOS', '-Xlinker', '-rpath', '-Xlinker', str(framework),
            str(here.parent / 'SecureCredentialView.swift'), str(here / 'SecureCredentialViewProbe.swift'),
            '-o', str(binary)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
        if result.returncode:
            print(result.stdout[-8000:])  # Compiler diagnostics contain source only, no runtime secret.
            print('{"passed":false,"stage":"compile"}'); return 1
        result = subprocess.run([str(binary)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        try: report = json.loads(result.stdout)
        except ValueError:
            print('{"passed":false,"stage":"native_probe"}'); return 1
        checks = report.get('checks')
        events = report.get('nativeChangedEvents')
        if (not isinstance(checks, dict) or set(checks) != CHECKS
                or any(type(v) is not bool for v in checks.values())
                or type(events) is not int or not 0 <= events <= 1000):
            print('{"passed":false,"stage":"invalid_evidence"}'); return 1
        safe = {'schemaVersion': 1, 'passed': report.get('passed') is True, 'checks': checks,
                'nativeChangedEvents': events,
                'localAccessibilityValueAvailable': report.get('localAccessibilityValueAvailable') is True,
                'localAccessibilityValueContainsSecret': report.get('localAccessibilityValueContainsSecret') is True,
                'localRoleAvailable': report.get('localRoleAvailable') is True,
                'localSubroleAvailable': report.get('localSubroleAvailable') is True,
                'systemAXVerified': False, 'liveDartEngineVerified': False, 'visibleWindowShown': False}
        print(json.dumps(safe, sort_keys=True))
        return 0 if result.returncode == 0 and safe['passed'] and all(checks.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
