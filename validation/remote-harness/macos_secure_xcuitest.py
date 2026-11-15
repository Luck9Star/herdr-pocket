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
    project.write_text(text)
    scheme.write_text(scheme_text.replace('parallelizable = "YES"', 'parallelizable = "NO"'))
    test_source = (HERE / 'macos_secure_xcuitest.swift').read_text()
    if fixture is not None:
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        if test_source.count('__HP_FIXTURE_BASE64__') != 1:
            raise ValueError('macos_xcui_test_source_unexpected')
        test_source = test_source.replace('__HP_FIXTURE_BASE64__', encoded)
        dart = app / 'lib/direct_ssh_page.dart'
        dart_text = dart.read_text()
        point = "          OutlinedButton(key: const ValueKey('direct-probe')"
        if dart_text.count(point) != 1 or 'HPAX:H' in dart_text:
            raise ValueError('macos_xcui_dart_unexpected')
        diagnostic = '''          Text('HPAX:H${host.text.trim() == "127.0.0.1" ? 1 : 0}P${port.text.trim() == "PASSWORD_PORT" ? 1 : 0}K${port.text.trim() == "KEY_PORT" ? 1 : 0}U${user.text.trim() == "fixture" ? 1 : 0}V${valid ? 1 : 0}B${busy ? 1 : 0}F${foreground ? 1 : 0}E${status.startsWith("探测失败") ? 1 : 0}A${host.text.isEmpty ? 1 : 0}N${user.text.isEmpty ? 1 : 0}T${port.text == "22" ? 1 : 0}D${port.text.isEmpty ? 1 : 0}C${fingerprint != null && checkedTarget == target ? 1 : 0}', style: const TextStyle(fontSize: 1)),
'''.replace('PASSWORD_PORT',str(config['port'])).replace('KEY_PORT',str(config['keyPort']))
        address_point = "          Semantics(container: true, explicitChildNodes: true, label: '地址'"
        if dart_text.count(address_point) != 1:
            raise ValueError('macos_xcui_dart_unexpected')
        dart.write_text(dart_text.replace(point, diagnostic + point, 1).replace(address_point, diagnostic + address_point, 1))
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
