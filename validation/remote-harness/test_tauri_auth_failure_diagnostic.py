import json
from pathlib import Path
import sys
import unittest
from xml.etree.ElementTree import Element

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tauri_auth_failure_diagnostic as diagnostic

OWNED = 'dev.herdrpocket.dualtestauth'
SYSTEM = 'com.android.documentsui'
PERSONAL = 'com.personal.privateapp'
ACTIVITY = OWNED + '/.MainActivity'
WINDOW = '  mCurrentFocus=Window{1a2b u0 ' + ACTIVITY + '}\n'


class Fixture:
    def __init__(self):
        self.commands = []
        self.windows = [WINDOW, WINDOW]
        self.fail = set()
        self.pids = '2148 2150'
        self.nodes = [{'package': OWNED, 'text': 'http://127.0.0.1:43210/private-token'}]

    def adb(self, *parts, **options):
        self.commands.append((parts, options))
        if parts[:3] == ('shell', 'pm', 'list'):
            key, value = 'systemPackages', 'package:' + SYSTEM
        elif parts == ('shell', 'dumpsys', 'window'):
            key = 'windowBeforeTree' if len(self.windows) == 2 else 'windowAfterTree'
            value = self.windows.pop(0)
        elif parts[:2] == ('shell', 'pidof'):
            key, value = 'ownedProcesses', self.pids
        else:
            raise AssertionError('unexpected command')
        if key in self.fail:
            raise RuntimeError('PRIVATE_EXCEPTION /private/user/path https://secret.invalid')
        return value

    def read_nodes(self):
        if 'nativeTree' in self.fail:
            raise RuntimeError('PRIVATE_XML <node text="personal"/>')
        return self.nodes

    def read_activity(self):
        if 'activity' in self.fail:
            raise RuntimeError('PRIVATE_ACTIVITY ' + PERSONAL)
        return ACTIVITY

    def capture(self, owned=None, port=43210):
        return diagnostic.capture(self.adb, self.read_nodes, self.read_activity,
                                  {OWNED} if owned is None else owned, port)


class FailureDiagnosticTests(unittest.TestCase):
    def test_capture_keeps_only_approved_bounded_facts(self):
        fixture = Fixture()
        result = fixture.capture()
        self.assertEqual(result['activityComponent'], OWNED + '/' + OWNED + '.MainActivity')
        self.assertTrue(result['windowStableAcrossTree'])
        self.assertTrue(result['loopbackHostPortSeen'])
        self.assertEqual(result['ownedProcessAlive'], {OWNED: True})
        self.assertIsNone(result['exitReason'])
        self.assertFalse(result['exitReasonAvailable'])
        encoded = json.dumps(result)
        for secret in ('2148', '2150', 'http://', 'private-token', '<node', 'Extras'):
            self.assertNotIn(secret, encoded)
        self.assertEqual([command[0] for command in fixture.commands], [
            ('shell', 'pm', 'list', 'packages', '-s'), ('shell', 'dumpsys', 'window'),
            ('shell', 'dumpsys', 'window'), ('shell', 'pidof', OWNED)])
        self.assertTrue(all(options.get('check', True) for _, options in fixture.commands))

    def test_personal_and_malformed_components_are_null(self):
        for value in (PERSONAL + '/.Main', ACTIVITY + ' Extras={secret}',
                      ACTIVITY + '\n', 'http://private/activity', 'a' * 257,
                      ['ambiguous'], None):
            with self.subTest(value=value):
                fixture = Fixture()
                fixture.windows = ['mCurrentFocus=Window{abc u0 ' + PERSONAL + '/.Main}'] * 2
                fixture.nodes = [{'package': PERSONAL, 'resource-id': PERSONAL + ':id/secret',
                                  'text': '127.0.0.1:43210'}]
                result = diagnostic.capture(fixture.adb, fixture.read_nodes, lambda: value, {OWNED}, 43210)
                self.assertIsNone(result['activityComponent'])
                self.assertIsNone(result['windowComponentBeforeTree'])
                self.assertIsNone(result['windowComponentAfterTree'])
                self.assertIsNone(result['rootPackage'])
                self.assertFalse(result['loopbackHostPortSeen'])
                self.assertNotIn(PERSONAL, json.dumps(result))

    def test_ambiguous_or_missing_activity_is_not_inferred(self):
        fixture = Fixture()
        result = diagnostic.capture(fixture.adb, fixture.read_nodes, lambda: None, {OWNED}, 43210)
        self.assertIsNone(result['activityComponent'])
        self.assertTrue(result['readsAvailable']['activity'])
        self.assertFalse(result['activityMatchesWindowBefore'])
        self.assertFalse(result['rootMatchesActivity'])
        for raw in (WINDOW + 'mCurrentFocus=null\n', WINDOW + WINDOW.replace(ACTIVITY, SYSTEM + '/.Files'),
                    'mCurrentFocus=Window{bad u0 ' + ACTIVITY + ' Extras={secret}}'):
            self.assertIsNone(diagnostic.window_component(raw))

    def test_raw_xml_is_not_a_native_tree(self):
        fixture = Fixture()
        fixture.nodes = '<hierarchy><node package="' + PERSONAL + '" text="PRIVATE_XML"/></hierarchy>'
        result = fixture.capture()
        self.assertFalse(result['readsAvailable']['nativeTree'])
        self.assertIsNone(result['rootPackage'])
        self.assertNotIn('PRIVATE_XML', json.dumps(result))
        self.assertTrue(result['ownedProcessAlive'][OWNED])

    def test_each_failed_read_preserves_other_facts_and_hides_error(self):
        for failed in ('systemPackages', 'activity', 'windowBeforeTree', 'nativeTree',
                       'windowAfterTree', 'ownedProcesses'):
            with self.subTest(failed=failed):
                fixture = Fixture()
                fixture.fail.add(failed)
                result = fixture.capture()
                available = result['readsAvailable']
                self.assertFalse(available['ownedProcesses'][OWNED] if failed == 'ownedProcesses' else available[failed])
                for other in ('systemPackages', 'activity', 'windowBeforeTree', 'nativeTree', 'windowAfterTree'):
                    if other != failed:
                        self.assertTrue(available[other])
                if failed != 'ownedProcesses':
                    self.assertTrue(result['ownedProcessAlive'][OWNED])
                else:
                    self.assertIsNone(result['ownedProcessAlive'][OWNED])
                self.assertNotIn('PRIVATE', json.dumps(result))
                self.assertNotIn('/private/', json.dumps(result))

    def test_resources_require_verified_system_root_and_are_capped(self):
        fixture = Fixture()
        fixture.nodes = [Element('node', {'package': SYSTEM, 'resource-id': SYSTEM + ':id/item_' + str(i)})
                         for i in range(40)]
        fixture.nodes.extend([{'package': SYSTEM, 'resource-id': PERSONAL + ':id/secret'},
                              {'package': PERSONAL, 'resource-id': SYSTEM + ':id/outside_root'},
                              {'package': SYSTEM, 'resource-id': SYSTEM + ':id/../secret'},
                              {'package': SYSTEM, 'resource-id': SYSTEM + ':id/' + 'x' * 161}])
        result = fixture.capture()
        self.assertEqual(len(result['systemResourceIds']), 32)
        self.assertTrue(result['systemResourceIdsTruncated'])
        self.assertTrue(all(remainder.startswith(SYSTEM + ':id/item_') for remainder in result['systemResourceIds']))
        self.assertNotIn(PERSONAL, json.dumps(result))
        fixture = Fixture()
        fixture.nodes = [{'package': OWNED, 'resource-id': OWNED + ':id/private'}]
        self.assertEqual(fixture.capture()['systemResourceIds'], [])

    def test_unverified_systems_and_malformed_package_lines_are_not_trusted(self):
        self.assertEqual(diagnostic.system_packages('package:' + SYSTEM + '\npackage:' + PERSONAL + ' /private\n'
                                                   'package:https://secret.invalid\npackage:' + 'x' * 129), {SYSTEM})
        fixture = Fixture()
        fixture.fail.add('systemPackages')
        fixture.nodes = [{'package': SYSTEM, 'resource-id': SYSTEM + ':id/title'}]
        result = fixture.capture()
        self.assertIsNone(result['rootPackage'])
        self.assertEqual(result['systemResourceIds'], [])
        self.assertIsNotNone(result['activityComponent'])

    def test_system_root_can_use_another_verified_system_resource_namespace(self):
        fixture = Fixture()
        root = 'com.android.intentresolver'
        fixture.nodes = [{'package': root, 'resource-id': 'android:id/button_once'},
                         {'package': root, 'resource-id': OWNED + ':id/private'},
                         {'package': root, 'resource-id': PERSONAL + ':id/private'},
                         {'package': PERSONAL, 'resource-id': 'android:id/outside_root'}]
        def adb(*parts, **options):
            if parts[:3] == ('shell', 'pm', 'list'):
                return 'package:' + root + '\npackage:android'
            return fixture.adb(*parts, **options)
        result = diagnostic.capture(adb, fixture.read_nodes, fixture.read_activity, {OWNED}, 43210)
        self.assertEqual(result['rootPackage'], root)
        self.assertEqual(result['systemResourceIds'], ['android:id/button_once'])
        self.assertNotIn(PERSONAL, json.dumps(result))

    def test_pid_allowlist_and_owned_packages_are_bounded(self):
        for raw, alive, available in (('123 456\n', True, True), ('', False, True),
                                      ('pid=123 secret', None, False), ('0', None, False),
                                      ('FATAL EXCEPTION: private', None, False), ('1' * 4097, None, False)):
            with self.subTest(raw=raw[:30]):
                fixture = Fixture()
                fixture.pids = raw
                result = fixture.capture()
                self.assertIs(result['ownedProcessAlive'][OWNED], alive)
                self.assertIs(result['readsAvailable']['ownedProcesses'][OWNED], available)
                self.assertIsNone(result['exitReason'])
        fixture = Fixture()
        result = fixture.capture(['dev.owned.app' + str(i) for i in range(12)] + ['bad/secret', None, ['bad']])
        self.assertEqual(len(result['ownedProcessAlive']), 8)
        self.assertTrue(result['ownedProcessPackagesTruncated'])
        self.assertEqual(sum(parts[:2] == ('shell', 'pidof') for parts, _ in fixture.commands), 8)
        self.assertNotIn('bad/secret', json.dumps(result))
        self.assertLess(len(json.dumps(result)), 10000)

    def test_loopback_only_matches_scoped_current_port(self):
        for text, port, expected in [('127.0.0.1:43210', 43210, True),
                                     ('http://127.0.0.1:43210/private', 43210, True),
                                     ('127.0.0.1:432100', 43210, False),
                                     ('1127.0.0.1:43210', 43210, False),
                                     ('127.0.0.1:43210', True, False),
                                     ('127.0.0.1:43210', '43210', False),
                                     ('127.0.0.1:12345', 43210, False)]:
            with self.subTest(text=text, port=port):
                fixture = Fixture()
                fixture.nodes = [{'package': OWNED, 'text': text},
                                 {'package': PERSONAL, 'text': '127.0.0.1:43210'}]
                self.assertIs(fixture.capture(port=port)['loopbackHostPortSeen'], expected)


if __name__ == '__main__':
    unittest.main()
