"""Convert the disposable Flutter macOS scaffold's test target to XCUITest."""
from pathlib import Path
import argparse
import base64
import json
import re

HERE = Path(__file__).resolve().parent


def install_test_semantics_hook(app):
    app = Path(app).resolve()
    marker = app / '.herdr-generated-probe.json'
    if not marker.is_file() or json.loads(marker.read_text()).get('kind') != 'herdr-flutter-validation':
        raise ValueError('macos_xcui_scaffold_invalid')
    window = app / 'macos/Runner/MainFlutterWindow.swift'
    text = window.read_text()
    point = '    super.awakeFromNib()\n'
    if text.count(point) != 1 or '--herdr-xcui-embedder-semantics' in text:
        raise ValueError('macos_xcui_window_unexpected')
    hook = '''    if CommandLine.arguments.contains("--herdr-xcui-embedder-semantics") {
      DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
        NotificationCenter.default.post(
          name: NSNotification.Name("NSApplicationDidChangeAccessibilityEnhancedUserInterfaceNotification"),
          object: nil, userInfo: ["AXEnhancedUserInterface": true])
      }
    }
'''
    window.write_text(text.replace(point, point + hook, 1))


def prepare(app, fixture=None):
    app = Path(app).resolve()
    marker = app / '.herdr-generated-probe.json'
    if not marker.is_file() or json.loads(marker.read_text()).get('kind') != 'herdr-flutter-validation':
        raise ValueError('macos_xcui_scaffold_invalid')
    project = app / 'macos/Runner.xcodeproj/project.pbxproj'
    scheme = app / 'macos/Runner.xcodeproj/xcshareddata/xcschemes/Runner.xcscheme'
    source = app / 'macos/RunnerTests/RunnerTests.swift'
    text = project.read_text()
    unit = 'productType = "com.apple.product-type.bundle.unit-test";'
    loader = '\t\t\t\tBUNDLE_LOADER = "$(TEST_HOST)";\n'
    host = '\t\t\t\tTEST_HOST = "$(BUILT_PRODUCTS_DIR)/herdr_flutter_probe.app/$(BUNDLE_EXECUTABLE_FOLDER_PATH)/herdr_flutter_probe";'
    if text.count(unit) != 1 or text.count(loader) != 3 or text.count(host) != 3 or not source.is_file():
        raise ValueError('macos_xcui_project_unexpected')
    scheme_text = scheme.read_text()
    if scheme_text.count('parallelizable = "YES"') != 1:
        raise ValueError('macos_xcui_scheme_unexpected')
    if fixture is not None:
        fixture = Path(fixture).resolve()
        if not fixture.is_file():
            raise ValueError('macos_xcui_fixture_invalid')
        config = json.loads(fixture.read_text())
        if (set(config) != {'port','username','password','fingerprint','keyPort','keyFingerprint','privateKey','passphrase'} or
                type(config['port']) is not int or not 1 <= config['port'] <= 65535 or
                type(config['keyPort']) is not int or not 1 <= config['keyPort'] <= 65535 or config['keyPort'] == config['port'] or
                config['username'] != 'fixture' or not re.fullmatch(r'[0-9a-f]{32}',config['password']) or
                not re.fullmatch(r'[0-9a-f]{32}',config['passphrase']) or
                not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',config['fingerprint']) or
                not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',config['keyFingerprint']) or
                not re.fullmatch(r'-----BEGIN OPENSSH PRIVATE KEY-----\n[A-Za-z0-9+/=\n]+-----END OPENSSH PRIVATE KEY-----\n?',config['privateKey'])):
            raise ValueError('macos_xcui_fixture_invalid')
    text = text.replace(unit, 'productType = "com.apple.product-type.bundle.ui-testing";')
    text = text.replace(loader, '').replace(host, '\t\t\t\tTEST_TARGET_NAME = Runner;')
    test_source = (HERE / 'macos_secure_xcuitest.swift').read_text()
    if fixture is not None:
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        if test_source.count('__HP_FIXTURE_BASE64__') != 1:
            raise ValueError('macos_xcui_test_source_unexpected')
        test_source = test_source.replace('__HP_FIXTURE_BASE64__', encoded)
        dart = app / 'lib/direct_ssh_page.dart'
        dart_text = dart.read_text()
        form_point = "    return entryList(desktop: desktop, key: const ValueKey('direct-form'), children: [\n"
        cleared_point = '      Align(alignment: Alignment.topLeft, child: SizedBox(width: width, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [\n'
        paste_point = "      if (keyAuth) ...[const SizedBox(height: 10), SizedBox(height: mobileButtonHeight, child: OutlinedButton(key: const ValueKey('direct-paste-key'),"
        if (dart_text.count(form_point) != 2 or dart_text.count(cleared_point) != 1 or
                dart_text.count(paste_point) != 1 or any(marker in dart_text for marker in ('HPAX:H', 'HPKEY:K', 'HPCLEAR:K', 'HPCLOSE:L'))):
            raise ValueError('macos_xcui_dart_unexpected')
        diagnostic = '''      if (desktop) Text('HPAX:H${host.text.trim() == "127.0.0.1" ? 1 : 0}P${port.text.trim() == "PASSWORD_PORT" ? 1 : 0}K${port.text.trim() == "KEY_PORT" ? 1 : 0}U${user.text.trim() == "fixture" ? 1 : 0}V${valid ? 1 : 0}B${busy ? 1 : 0}F${foreground ? 1 : 0}E${status.startsWith("探测失败") ? 1 : 0}A${host.text.isEmpty ? 1 : 0}N${user.text.isEmpty ? 1 : 0}T${port.text == "22" ? 1 : 0}D${port.text.isEmpty ? 1 : 0}C${fingerprint != null && checkedTarget == target ? 1 : 0}', style: const TextStyle(fontSize: 1)),
'''.replace('PASSWORD_PORT',str(config['port'])).replace('KEY_PORT',str(config['keyPort']))
        cleared_diagnostic = '''Text('HPCLEAR:K${secret.text.isEmpty ? 1 : 0}P${passphrase.text.isEmpty ? 1 : 0}', style: const TextStyle(fontSize: 1)),
'''
        close_diagnostic = '''Text('HPCLOSE:L${closeLocalConfirmed ? 1 : 0}F${closeCleanupFailed ? 1 : 0}', style: const TextStyle(fontSize: 1)),
'''
        key_encoded = base64.b64encode(config['privateKey'].encode()).decode()
        phrase_encoded = base64.b64encode(config['passphrase'].encode()).decode()
        key_diagnostic = ("      if (desktop && keyAuth) Text('HPKEY:K${secret.text == utf8.decode(base64.decode(\"" + key_encoded +
                       "\")) ? 1 : 0}P${passphrase.text == utf8.decode(base64.decode(\"" + phrase_encoded +
                       "\")) ? 1 : 0}Q${passphrase.text == 'q' ? 1 : 0}E${secret.text.isEmpty ? 1 : 0}L${secret.text.length == utf8.decode(base64.decode(\"" + key_encoded + "\")).length ? 1 : 0}T${secret.text.trimRight() == utf8.decode(base64.decode(\"" + key_encoded + "\")).trimRight() ? 1 : 0}', style: const TextStyle(fontSize: 1)),\n")
        connect_point = '  Future<void> connect() async {'
        parse_point = '      final localSocket = await SSHSocket.connect('
        if dart_text.count(connect_point) != 1 or dart_text.count(parse_point) != 1:
            raise ValueError('macos_xcui_dart_unexpected')
        dart_text = dart_text.replace(connect_point, connect_point + "\n    if (keyAuth) debugPrint('HP_XCUI_STAGE=keyConnectHandlerEntered');", 1)
        dart_text = dart_text.replace(parse_point, "      if (keyAuth) debugPrint('HP_XCUI_STAGE=keyPemParsed');\n" + parse_point, 1)
        dart_text = dart_text.replace(form_point, form_point + diagnostic + '      if (desktop) ' + cleared_diagnostic)
        dart_text = dart_text.replace(cleared_point, cleared_point + '        ' + cleared_diagnostic + '        ' + close_diagnostic, 1)
        dart.write_text(dart_text.replace(paste_point, key_diagnostic + paste_point, 1))
    project.write_text(text)
    scheme.write_text(scheme_text.replace('parallelizable = "YES"', 'parallelizable = "NO"'))
    source.write_text(test_source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--install-hook', action='store_true')
    args = parser.parse_args()
    if args.install_hook:
        install_test_semantics_hook(args.app)
    else:
        prepare(args.app, args.fixture)
