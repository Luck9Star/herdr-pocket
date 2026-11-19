import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paired_gui import GuiFailure
import tauri_android_config_document as config


PROVIDER = 'com.google.android.documentsui'
FOLDER = 'hp-config-fixture'


def node(resource='', content='', *, package=PROVIDER, **attributes):
    fields = {'resource-id': resource, 'package': package, 'enabled': 'true', **attributes}
    values = ' '.join(f'{name}="{value}"' for name, value in fields.items())
    return f'<node {values}>{content}</node>'


def chooser(*content):
    return '<hierarchy rotation="0">' + ''.join(content) + '</hierarchy>'


class PickerTests(unittest.TestCase):
    def hit(self, xml, **options):
        return config.native_hit(xml, PROVIDER, (1080, 2000), **options)

    def test_file_requires_exact_owned_breadcrumb_and_directory_scope(self):
        row = node('', node('android:id/title', text=config.ARCHIVE), clickable='true',
                   bounds='[20,40][400,140]')
        listing = node(f'{PROVIDER}:id/dir_list', row)
        breadcrumb = node('com.android.documentsui:id/horizontal_breadcrumb',
                          node('', text=FOLDER))
        options = {'ancestor': 'dir_list', 'label': config.ARCHIVE,
                   'resource': 'android:id/title', 'folder': FOLDER}
        self.assertIsNone(self.hit(chooser(listing), **options))
        self.assertIsNone(self.hit(chooser(breadcrumb, row), **options))
        self.assertEqual(self.hit(chooser(breadcrumb, listing), **options), (20, 40, 400, 140))

    def test_duplicate_foreign_and_offscreen_rows_are_rejected(self):
        options = {'ancestor': 'roots_list', 'label': 'Downloads', 'resource': 'android:id/title'}

        def lookup(*rows):
            return self.hit(chooser(node(f'{PROVIDER}:id/roots_list', ''.join(rows))), **options)

        def root(package=PROVIDER, bounds='[10,20][100,60]'):
            return node('', node('android:id/title', package=package, text='Downloads'),
                        package=package, clickable='true', bounds=bounds)

        self.assertEqual(lookup(root()), (10, 20, 100, 60))
        self.assertIsNone(lookup(root(), root()))
        self.assertIsNone(lookup(root('bad.other.package')))
        self.assertIsNone(lookup(root(bounds='[10,20][1100,60]')))

    def test_save_requires_the_default_name_in_the_system_save_form(self):
        button = node('android:id/button1', clickable='true', bounds='[10,20][100,60]')
        breadcrumb = node(f'{PROVIDER}:id/horizontal_breadcrumb', node('', text=FOLDER))
        title = node('android:id/title', **{'class': 'android.widget.EditText', 'text': config.ARCHIVE})
        options = {'ancestor': 'container_save', 'resource': 'android:id/button1',
                   'folder': FOLDER, 'save_name': config.ARCHIVE}
        self.assertIsNone(self.hit(chooser(breadcrumb, title,
                                         node(f'{PROVIDER}:id/container_save', button)), **options))
        self.assertEqual(self.hit(chooser(breadcrumb,
                                         node(f'{PROVIDER}:id/container_save', title + button)),
                                  **options), (10, 20, 100, 60))

    def test_no_tap_if_foreground_changes_after_bounds_are_stable(self):
        with patch.object(config, 'owned_display', return_value=(1080, 2000)):
            picker = config.Picker({})
        picker.package = PROVIDER
        with patch.object(config, 'wait_for', return_value=(10, 20, 100, 60)), \
                patch.object(config, 'foreground', return_value=config.PACKAGE), \
                patch.object(config, 'adb') as adb:
            with self.assertRaisesRegex(GuiFailure, '^documents_ui_unconfirmed$'):
                picker.tap(ancestor='dir_list', label='owned')
            adb.assert_not_called()


class ArchiveTests(unittest.TestCase):
    def test_independent_open_and_wrong_secret_tag_or_payload(self):
        def encrypted(payload):
            header = b'HPKT\x01\x01' + bytes(range(28))
            key = hashlib.pbkdf2_hmac('sha256', b'synthetic long passphrase', header[6:22], 600_000)
            return header + AESGCM(key).encrypt(header[22:34], json.dumps(payload).encode(), header)

        password = 'synthetic long passphrase'
        payload = {'version': 2, 'hosts': [], 'networks': [], 'preferences': {'terminalFontSize': 19}}
        raw = encrypted(payload)
        config.open_archive(raw, password)
        for name, contents, secret in (
            ('wrong_secret', raw, 'another synthetic passphrase'),
            ('tampered_tag', raw[:-1] + bytes([raw[-1] ^ 1]), password),
            ('extra_metadata', encrypted(dict(payload, hosts=[{'fixture': True}])), password),
            ('oversize', raw + bytes(config.MAX_ARCHIVE), password),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(GuiFailure, '^archive_invalid$'):
                config.open_archive(contents, secret)

    def test_catalog_requires_no_hosts_networks_or_extra_fields(self):
        state = {'version': 1, 'hosts': [], 'networkProfiles': [], 'preferences': {'terminalFontSize': 13}}
        raw = json.dumps(state).encode()
        with patch.object(config, 'binary_file', return_value=raw) as read:
            self.assertEqual(config.catalog(13), raw)
            read.assert_called_once_with(['run-as', config.PACKAGE], config.HOME_RECORDS, 131072,
                                         'catalog_read_failed')
        state['hosts'] = [{'fixture': True}]
        with patch.object(config, 'binary_file', return_value=json.dumps(state).encode()):
            with self.assertRaisesRegex(GuiFailure, '^catalog_mismatch$'):
                config.catalog(13)


class EvidenceTests(unittest.TestCase):
    def test_exception_does_not_echo_paths_secrets_or_overwrite_the_report(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'RUNNER_TEMP': root}):
            report = Path(root).resolve() / 'result'
            args = ['driver', '--apk', 'synthetic.apk', '--output', str(report)]
            with patch('sys.argv', args), patch.object(config, 'device_run',
                    side_effect=GuiFailure('synthetic untrusted path and secret')):
                self.assertEqual(config.main(), 1)
                data = json.loads((report / 'manifest.json').read_text())
                self.assertEqual(data['errorCode'], 'driver_failed')
                self.assertEqual(data['status'], 'failed')
                self.assertNotIn('synthetic', str(data))
                with self.assertRaisesRegex(GuiFailure, '^unsafe_runner$'):
                    config.main()

    def test_without_owned_runner_refuses_before_adb(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(config, 'adb') as adb:
            with self.assertRaisesRegex(GuiFailure, '^unsafe_runner$'):
                config.device_run(Path('synthetic.apk'), {})
            adb.assert_not_called()

    def test_partial_install_keeps_first_failure_and_cleans_owned_folder(self):
        with tempfile.TemporaryDirectory() as root:
            avd = Path(root) / 'avd'
            avd.mkdir()
            apk = Path(root) / 'fixture.apk'
            apk.touch()
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/codex/local',
                   'ANDROID_SERIAL': config.SERIAL, 'ANDROID_AVD_HOME': str(avd),
                   'RUNNER_TEMP': root}
            folders = []
            installed = False

            def adb(*args, **kwargs):
                nonlocal installed
                fixed = {('devices',): f'List of devices attached\n{config.SERIAL}\tdevice',
                         ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                         ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                         ('shell', 'am', 'get-current-user'): '0',
                         ('shell', 'wm', 'size'): 'Physical size: 1080x2000'}
                if args in fixed:
                    return fixed[args]
                if args[:4] == ('shell', 'pm', 'list', 'packages'):
                    return 'package:' + config.PACKAGE if installed else ''
                if args[:2] == ('shell', 'mkdir'):
                    folders.append(args[2])
                    return ''
                if args[0] == 'install':
                    installed = True
                    raise GuiFailure('install_unconfirmed')
                if args[0] == 'uninstall':
                    raise GuiFailure('app_package_unconfirmed')
                if args[:2] == ('shell', 'rm'):
                    self.assertEqual(args[3:], tuple(folders[0] + '/' + name
                                                    for name in (config.ARCHIVE, config.CORRUPT)))
                    return ''
                if args[:2] == ('shell', 'rmdir'):
                    self.assertEqual(folders.pop(), args[2])
                    return ''
                if args[:3] == ('shell', 'am', 'force-stop') or args[:4] == ('shell', 'test', '!', '-e'):
                    return ''
                self.fail('unexpected ADB command')

            report = {'cleanup': {}}
            with patch.dict(os.environ, env, clear=True), patch.object(config, 'adb', side_effect=adb):
                with self.assertRaisesRegex(GuiFailure, '^install_unconfirmed$'):
                    config.device_run(apk, report)
            self.assertEqual(report['cleanup'], {'hierarchyFile': True, 'application': False,
                                                 'downloadFolder': True})
            self.assertEqual(folders, [])


if __name__ == '__main__':
    unittest.main()
