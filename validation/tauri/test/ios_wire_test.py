"""Stubbed bridge checks; these do not replace iOS SDK, device or GUI tests."""
from pathlib import Path
import os
import plistlib
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / 'pairing/native/apple/DeviceKeys.swift'


class IOSWireTests(unittest.TestCase):
    def test_permission_and_pinned_registration_wiring(self):
        info = plistlib.loads((ROOT / 'src-tauri/Info.ios.plist').read_bytes())
        self.assertTrue(info['NSCameraUsageDescription'])
        build = (ROOT / 'src-tauri/build.rs').read_text()
        for item in ('DEP_TAURI_IOS_LIBRARY_PATH', 'DeviceKeys.swift', 'PairScanner.swift',
                     'PocketKeyBridge.swift', 'PocketPlugin.swift', 'ConfigDocument.swift', 'link_apple_library'):
            self.assertIn(item, build)
        rust = (ROOT / 'src-tauri/src/ios_keys.rs').read_text()
        swift = (ROOT / 'ios/PocketPlugin.swift').read_text()
        self.assertIn('init_plugin_herdr_pocket_ios', rust)
        self.assertIn('init_plugin_herdr_pocket_ios', swift)
        for method in ('create', 'publicKey', 'sign', 'delete', 'privateConfigRoot', 'scan'):
            self.assertIn(f'func {method}(', swift)
            self.assertIn(f'"{method}"', rust)
        for method in ('openDocument', 'saveDocument'):
            self.assertIn(f'func {method}(', swift)
            self.assertIn(f'"{method}"', rust)

    def test_key_contract_against_memory_backend(self):
        with tempfile.TemporaryDirectory(prefix='herdr-ios-wire-') as tmp:
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=tmp + '/clang')
            subprocess.run(['swiftc', '-module-cache-path', tmp + '/modules', str(SHARED),
                            str(ROOT / 'ios/PocketKeyBridge.swift'),
                            str(ROOT / 'test/PocketKeyBridgeProbe.swift'), '-o', tmp + '/probe'],
                           env=env, check=True)
            subprocess.run([tmp + '/probe'], env=env, check=True)

    def test_swift_plugin_typechecks_against_minimal_native_stubs(self):
        with tempfile.TemporaryDirectory(prefix='herdr-ios-typecheck-') as tmp:
            tmp = Path(tmp)
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(tmp / 'clang'))
            cache = ['-module-cache-path', str(tmp / 'modules')]
            (tmp / 'UIKit.swift').write_text('''import Foundation
public enum UIModalPresentationStyle { case fullScreen }
open class UIView: NSObject { public var window: NSObject? }
open class UIViewController: NSObject {
  public var presentedViewController: UIViewController?
  public var modalPresentationStyle: UIModalPresentationStyle = .fullScreen
  public var viewIfLoaded: UIView?
  public func present(_ controller: UIViewController, animated: Bool) {}
}
''')
            (tmp / 'Tauri.swift').write_text('''import Foundation
import UIKit
@objc public class Invoke: NSObject {
  public func parseArgs<T: Decodable>(_ type: T.Type) throws -> T { fatalError() }
  public func resolve<T: Encodable>(_ value: T) {}
  public func reject(_ message: String) {}
}
public class PluginManager { public var viewController: UIViewController? }
open class Plugin: NSObject { public let manager = PluginManager() }
''')
            (tmp / 'Scanner.swift').write_text('''import UIKit
final class PairScanner: UIViewController { var onFinish: ((String?, String?) -> Void)? }
''')
            (tmp / 'Documents.swift').write_text('''import Foundation
import UIKit
enum PocketDocumentIO { static let limit = 65586 }
final class PocketDocumentPicker {
  func open(presenter: UIViewController, completion: @escaping (Result<Data?, Error>) -> Void) {}
  func save(_ bytes: Data, presenter: UIViewController, completion: @escaping (Result<Data?, Error>) -> Void) {}
}
''')
            for module in ('UIKit', 'Tauri'):
                subprocess.run(['swiftc', *cache, '-emit-module', '-module-name', module,
                                '-I', str(tmp), str(tmp / (module + '.swift')),
                                '-emit-module-path', str(tmp / (module + '.swiftmodule'))],
                               env=env, check=True)
            subprocess.run(['swiftc', *cache, '-typecheck', '-I', str(tmp), str(SHARED),
                            str(ROOT / 'ios/PocketKeyBridge.swift'), str(ROOT / 'ios/PocketPlugin.swift'),
                            str(tmp / 'Scanner.swift'), str(tmp / 'Documents.swift')], env=env, check=True)


if __name__ == '__main__':
    unittest.main()
