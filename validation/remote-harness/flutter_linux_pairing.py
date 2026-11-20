"""Launch the existing reviewed pairing widget cases in a native GTK runner."""
import hashlib
import os
from pathlib import Path


def native_command(args, root, env, *, split=False):
    # Reuse the ordinary SSH driver's pinned Flutter, source parity and lock
    # verification. The staged integration entry imports the original case;
    # production sources and test contents are copied unchanged by ci.py.
    from flutter_linux_direct_ssh import prepare
    from paired_gui import GuiFailure
    case = 's06_real_ssh_test.dart' if split else 'pairing_gui_ssh_test.dart'
    checkout = Path(__file__).resolve().parents[1] / 'flutter/test' / case
    staged = args.flutter_app / 'test' / case
    contents = checkout.read_bytes()
    if staged.is_symlink() or staged.read_bytes() != contents:
        raise GuiFailure('flutter_linux_pairing_test_source_changed')
    source = prepare(args.flutter_app, os.environ['GITHUB_SHA'], env, root / 'flutter-pairing-pub.log')
    args.flutter_native_source = {key: value for key, value in source.items()
                                  if key not in ('testSha256', 'uiStepsSha256')}
    args.flutter_native_source['pairingTestSha256'] = hashlib.sha256(contents).hexdigest()
    entry = args.flutter_app / 'integration_test/linux_native_pairing_test.dart'
    entry.write_text(
        "import 'package:integration_test/integration_test.dart';\n"
        f"import '../test/{case}' as reviewed;\n\n"
        'void main() {\n'
        '  IntegrationTestWidgetsFlutterBinding.ensureInitialized();\n'
        '  reviewed.main();\n'
        '}\n', encoding='utf-8')
    exchange = root / ('s06-exchange' if split else 'gui-exchange')
    return ['flutter', 'test', '--no-pub', '--reporter', 'expanded', '-d', 'linux',
            '--dart-define=HERDR_LINUX_NATIVE_PAIRING=true', f'--dart-define=HERDR_LINUX_PAIRING_EXCHANGE={exchange}',
            'integration_test/linux_native_pairing_test.dart']
