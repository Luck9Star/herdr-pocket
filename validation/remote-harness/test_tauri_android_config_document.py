import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paired_gui import GuiFailure
import tauri_android_config_document as config


PROVIDER = 'com.google.android.documentsui'
FOLDER = 'hp-config-fixture'
ACTIVITY = config.PACKAGE + '/.MainActivity'
CANONICAL_ACTIVITY = config.PACKAGE + '/' + config.PACKAGE + '.MainActivity'
SYSTEM_PICKER = PROVIDER + '/com.android.documentsui.picker.PickActivity'


def node(resource='', content='', *, package=PROVIDER, **attributes):
    fields = {'resource-id': resource, 'package': package, 'enabled': 'true', **attributes}
    values = ' '.join(f'{name}="{value}"' for name, value in fields.items())
    return f'<node {values}>{content}</node>'


def chooser(*content):
    return '<hierarchy rotation="0">' + ''.join(content) + '</hierarchy>'


def catalog_bytes(font):
    return json.dumps({'version': 1, 'hosts': [], 'networkProfiles': [],
                       'preferences': {'terminalFontSize': font}}, separators=(',', ':')).encode()


class FontSaveTests(unittest.TestCase):
    class Browser:
        def __init__(self, *, click='target', receipt='same_success', dispatch_fails=False):
            self.click_target = click
            self.receipt = receipt
            self.dispatch_fails = dispatch_fails
            self.saves = 0
            self.closed = 0
            self.released = 0

        def evaluate(self, expression):
            return True

        def click(self, selector):
            if selector == '#terminal-font-save':
                self.saves += 1
                if self.dispatch_fails:
                    raise GuiFailure('untrusted dispatch detail')

        def read(self, selector, prop):
            return str(config.CONTROL_FONT)

        def call(self, method, params):
            if method == 'Runtime.evaluate':
                return {'result': {'objectId': 'fixture-listener'}}
            if method == 'Runtime.callFunctionOn':
                if 'this.sample()' in params['functionDeclaration']:
                    return {'result': {'value': {
                        'pointerDown': 'target', 'pointerUp': 'target', 'click': self.click_target,
                        'viewportAtPress': 'reduced', 'receipt': self.receipt}}}
                if 'this.close()' in params['functionDeclaration']:
                    self.closed += 1
            if method == 'Runtime.releaseObject':
                self.released += 1
            return {}

    @staticmethod
    def sample(probe, error, **options):
        return probe() or config.require(False, error)

    def test_catalog_transition_does_not_require_the_same_success_text_node_to_change(self):
        before, after = catalog_bytes(config.FONT), catalog_bytes(config.CONTROL_FONT)
        browser, facts = self.Browser(), {}

        with patch.object(config, 'binary_file', side_effect=[before, before, after]) as read:
            self.assertEqual(config.set_font(browser, config.CONTROL_FONT, facts=facts, before=before), after)
        self.assertEqual(read.call_count, 3)
        self.assertEqual((browser.saves, browser.closed, browser.released), (1, 1, 1))
        self.assertEqual((facts['click'], facts['receipt'], facts['catalog']), ('target', 'same_success', 'expected'))

    def test_wrong_or_unproven_outcome_is_not_replayed_or_accepted(self):
        before, after = catalog_bytes(config.FONT), catalog_bytes(config.CONTROL_FONT)
        for click, receipt, raw, code, catalog in (
            ('target', 'same_success', before, 'font_save_storage_unconfirmed', 'previous_bytes'),
            ('target', 'success', catalog_bytes(17), 'catalog_mismatch', 'mismatch'),
            ('target', 'success', after.replace(b':13', b':13.0'), 'catalog_mismatch', 'mismatch'),
            ('target', 'rejected', before, 'font_save_rejected', 'previous_bytes'),
            ('target', 'empty', after, 'font_save_status_unconfirmed', 'expected'),
            ('none', 'same_success', after, 'font_save_click_unconfirmed', 'expected'),
            ('other', 'same_success', before, 'font_save_click_unconfirmed', 'previous_bytes'),
            ('different_value', 'success', after, 'font_save_click_unconfirmed', 'expected'),
            ('untrusted', 'success', after, 'font_save_click_unconfirmed', 'expected'),
            ('multiple', 'success', after, 'font_save_click_unconfirmed', 'expected'),
        ):
            with self.subTest(click=click, receipt=receipt, code=code):
                browser, facts = self.Browser(click=click, receipt=receipt), {}
                with patch.object(config, 'binary_file', side_effect=[before, raw]), \
                        patch.object(config, 'wait_for', side_effect=self.sample):
                    with self.assertRaisesRegex(GuiFailure, '^' + code + '$'):
                        config.set_font(browser, config.CONTROL_FONT, facts=facts, before=before)
                self.assertEqual((facts['click'], facts['receipt'], facts['catalog']), (click, receipt, catalog))
                self.assertEqual((browser.saves, browser.closed, browser.released), (1, 1, 1))

    def test_uncertain_dispatch_is_not_replayed(self):
        browser, facts = self.Browser(click='none', dispatch_fails=True), {}
        before = catalog_bytes(config.FONT)
        with patch.object(config, 'binary_file', return_value=before) as read:
            with self.assertRaisesRegex(GuiFailure, '^font_save_dispatch_unconfirmed$'):
                config.set_font(browser, config.CONTROL_FONT, facts=facts, before=before)
        read.assert_called_once()
        self.assertEqual((facts['dispatch'], facts['click']), ('uncertain', 'none'))
        self.assertEqual((browser.saves, browser.closed, browser.released), (1, 1, 1))

    def test_known_baseline_must_still_match_before_typing_or_clicking(self):
        browser, facts = self.Browser(), {}
        with patch.object(config, 'binary_file', return_value=catalog_bytes(config.CONTROL_FONT)):
            with self.assertRaisesRegex(GuiFailure, '^catalog_changed$'):
                config.set_font(browser, config.CONTROL_FONT, facts=facts, before=catalog_bytes(config.FONT))
        self.assertEqual((facts['dispatch'], facts['catalog']), ('not_attempted', 'different_baseline'))
        self.assertEqual((browser.saves, browser.closed, browser.released), (0, 0, 0))


class ForegroundTests(unittest.TestCase):
    def test_api35_displays_subcommand_contains_focus_windows_subcommand_omits(self):
        outputs = {
            'windows': ('WINDOW MANAGER WINDOWS (dumpsys window windows)\n'
                        f'  Window #0 Window{{7ba u0 {ACTIVITY}}}:\n    mDisplayId=0\n'),
            'displays': ('WINDOW MANAGER DISPLAY CONTENTS (dumpsys window displays)\n'
                         f'  Display: mDisplayId=0\n    mCurrentFocus=Window{{7ba u0 {ACTIVITY}}}\n'),
        }
        with patch.object(config, 'adb', side_effect=lambda *args, **opts: outputs[args[-1]]):
            self.assertEqual(config.foreground(), CANONICAL_ACTIVITY)

    def test_focus_rejects_other_users_displays_and_conflicting_windows(self):
        for raw, reason in (
            (f'Display: mDisplayId=0\n mCurrentFocus=Window{{7ba u10 {ACTIVITY}}}', 'other_user'),
            (f'Display: mDisplayId=1\n mCurrentFocus=Window{{7ba u0 {ACTIVITY}}}', 'display_unproven'),
            (f'Display: mDisplayId=0\n mCurrentFocus=Window{{7ba u0 {ACTIVITY}}}\n'
             ' mCurrentFocus=null', 'focus_ambiguous'),
            ('Display: mDisplayId=0\n mCurrentFocus=null', 'no_focused_window'),
            ('Display: mDisplayId=0\n mCurrentFocus=Window{7ba u0 NotificationShade}', 'system_window'),
        ):
            with self.subTest(reason=reason), patch.object(config, 'adb', return_value=raw):
                self.assertEqual(config.focus_sample(), (None, reason))

    def test_launcher_resolves_only_one_component_of_owned_package_on_user_zero(self):
        with patch.object(config, 'adb', return_value='priority=0 match=0x108000\n' + ACTIVITY) as adb:
            self.assertEqual(config.resolve_launcher(), CANONICAL_ACTIVITY)
            self.assertEqual(adb.call_args.args, (
                'shell', 'cmd', 'package', 'resolve-activity', '--brief', '--user', '0',
                '-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER',
                '-p', config.PACKAGE))
        for raw in ('app.private.example/.Hidden', ACTIVITY + '\n' + config.PACKAGE + '/.Other'):
            with patch.object(config, 'adb', return_value=raw):
                with self.assertRaisesRegex(GuiFailure, '^app_launcher_unconfirmed$'):
                    config.resolve_launcher()

    def test_failure_diagnostics_use_enum_for_hidden_window_activity_and_process(self):
        def adb(*args, **kwargs):
            if args[-1] == 'displays':
                return 'Display: mDisplayId=0\n mCurrentFocus=Window{7ba u0 app.private.example/.Hidden}'
            if args[-1] == 'activities':
                return 'topResumedActivity=ActivityRecord{f8e u0 ' + ACTIVITY + ' t86}'
            if args[0] == 'shell' and f'pidof {config.PACKAGE}' in args[1]:
                return 'absent'
            self.fail('unexpected ADB read')

        with patch.object(config, 'adb', side_effect=adb):
            self.assertEqual(config.launch_failure_facts(CANONICAL_ACTIVITY, '983'), {
                'window': 'other_activity', 'resumedActivity': 'launcher', 'process': 'disappeared'})
            self.assertEqual(config.launch_failure_facts(CANONICAL_ACTIVITY, None)['process'], 'not_observed')
        with patch.object(config, 'adb', side_effect=GuiFailure('raw untrusted detail')):
            self.assertEqual(config.launch_failure_facts(CANONICAL_ACTIVITY, '983'), {
                'window': 'unavailable', 'resumedActivity': 'unavailable', 'process': 'unavailable'})


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
        picker.window = SYSTEM_PICKER
        with patch.object(config, 'wait_for', return_value=(10, 20, 100, 60)), \
                patch.object(config, 'foreground', return_value=config.PACKAGE), \
                patch.object(config, 'adb') as adb:
            with self.assertRaisesRegex(GuiFailure, '^documents_ui_unconfirmed$'):
                picker.tap(ancestor='dir_list', label='owned')
            adb.assert_not_called()

    def test_picker_samples_only_fresh_successfully_removed_scratch(self):
        for failure in (None, 'existing', 'dump', 'read', 'empty', 'remove', 'remaining'):
            with self.subTest(failure=failure), patch.object(config, 'owned_display', return_value=(1080, 2000)):
                picker = config.Picker({})
                picker.package = PROVIDER
                picker.window = SYSTEM_PICKER
                calls = []
                xml = chooser(node(f'{PROVIDER}:id/dir_list',
                                   node('', node('android:id/title', text='owned'),
                                        clickable='true', bounds='[20,40][400,140]')))

                def adb(*args, **kwargs):
                    if args[0] == 'shell' and args[1].startswith('test ! -e '):
                        state = 'remaining' if calls else 'existing'
                        calls.append('absent')
                        self.assertIn(f'! -L {picker.scratch}', args[1])
                    elif args[:4] == ('shell', 'test', '!', '-e'):
                        state = 'remaining'
                        calls.append('absent')
                    elif args[:3] == ('shell', 'uiautomator', 'dump'):
                        state = 'dump'
                        calls.append(state)
                    elif args[:2] == ('exec-out', 'cat'):
                        state = 'read'
                        calls.append(state)
                    elif args[:3] == ('shell', 'rm', '-f'):
                        state = 'remove'
                        calls.append(state)
                    elif args[:3] == ('shell', 'input', 'tap'):
                        calls.append('tap')
                        self.assertEqual(args[3:], (210, 90))
                        return ''
                    else:
                        self.fail('unexpected ADB command')
                    self.assertIn(picker.scratch, ' '.join(args))
                    if failure == state and kwargs.get('check', True):
                        raise GuiFailure('untrusted diagnostic')
                    if state == 'read':
                        return '' if failure == 'empty' else xml
                    return ''

                def one_sample(probe, code, *, timeout=25):
                    return probe() or config.require(False, code)

                with patch.object(config, 'adb', side_effect=adb), \
                        patch.object(config, 'foreground', return_value=SYSTEM_PICKER), \
                        patch.object(config, 'wait_for', side_effect=one_sample):
                    if failure is None:
                        picker.tap(ancestor='dir_list', label='owned', resource='android:id/title')
                        self.assertEqual(calls, ['absent', 'dump', 'read', 'remove', 'absent'] * 2 + ['tap'])
                    else:
                        cleanup = failure in ('existing', 'remove', 'remaining')
                        code = 'picker_hierarchy_cleanup_unconfirmed' if cleanup else 'picker_hierarchy_unavailable'
                        with self.assertRaisesRegex(GuiFailure, '^' + code + '$'):
                            picker.tap(ancestor='dir_list', label='owned', resource='android:id/title')
                        self.assertNotIn('tap', calls)
                        self.assertLessEqual(calls.count('dump'), 1)
                        self.assertEqual(picker.scratch_cleanup_failed, cleanup)
                        if failure == 'existing':
                            self.assertEqual(calls, ['absent'])

    def test_picker_requires_actual_picker_activity_and_exact_launcher_on_return(self):
        with patch.object(config, 'owned_display', return_value=(1080, 2000)):
            picker = config.Picker({'pickerOpens': 0})
        picker.launcher = CANONICAL_ACTIVITY

        def one_sample(probe, code):
            return probe() or config.require(False, code)

        with patch.object(config, 'wait_for', side_effect=one_sample):
            with patch.object(config, 'foreground', return_value=PROVIDER + '/.files.FilesActivity'):
                with self.assertRaisesRegex(GuiFailure, '^documents_ui_unconfirmed$'):
                    picker.enter()
            self.assertEqual(picker.report['pickerOpens'], 0)
            with patch.object(config, 'foreground', return_value=SYSTEM_PICKER):
                picker.enter()
            self.assertEqual(picker.report['pickerOpens'], 1)
            with patch.object(config, 'foreground', return_value=config.PACKAGE + '/.OtherActivity'):
                with self.assertRaisesRegex(GuiFailure, '^picker_return_unconfirmed$'):
                    picker.wait_return()
            with patch.object(config, 'foreground', return_value=CANONICAL_ACTIVITY):
                picker.wait_return()
            self.assertEqual(picker.report['pickerStep'], 'app_foreground')


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

    def check_device_setup(self, *, mount_ready=True, download_ready=True, mkdir_fails=False):
        with tempfile.TemporaryDirectory() as root:
            avd = Path(root) / 'avd'
            avd.mkdir()
            apk = Path(root) / 'fixture.apk'
            apk.touch()
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/codex/local',
                   'ANDROID_SERIAL': config.SERIAL, 'ANDROID_AVD_HOME': str(avd),
                   'RUNNER_TEMP': root}
            report = {'cleanup': {}}
            events, folders = [], []
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
                if args == ('shell', 'sm', 'list-volumes', 'emulated'):
                    events.append('volume')
                    state = 'mounted' if mount_ready and events.count('volume') > 1 else 'checking'
                    return f'emulated;10 mounted null\nemulated;0 {state} null'
                if args[0] == 'shell' and len(args) == 2 and '/storage/emulated/0/Download' in args[1]:
                    events.append('parent')
                    self.assertIn('! -L', args[1])
                    if download_ready and events.count('parent') > 1:
                        events.append('parent-ready')
                        return 'download_ready'
                    return ''
                if args[:2] == ('shell', 'mkdir'):
                    events.append('mkdir')
                    if 'parent-ready' not in events or mkdir_fails:
                        raise GuiFailure('untrusted_android_detail')
                    self.assertRegex(args[2], r'^/storage/emulated/0/Download/hp-config-[0-9a-f]{24}$')
                    folders.append(args[2])
                    return ''
                if args[0] == 'install':
                    events.append('install')
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
                    events.append('folder-removed')
                    return ''
                if args[:3] == ('shell', 'am', 'force-stop') or args[:4] == ('shell', 'test', '!', '-e'):
                    return ''
                self.fail('unexpected ADB command')

            def bounded_wait(probe, error, *, timeout=25):
                for _ in range(3):
                    value = probe()
                    if value:
                        return value
                raise GuiFailure(error)

            with patch.dict(os.environ, env, clear=True), patch.object(config, 'adb', side_effect=adb), \
                    patch.object(config, 'wait_for', side_effect=bounded_wait):
                with self.assertRaises(GuiFailure) as error:
                    config.device_run(apk, report)
            self.assertEqual(folders, [])
            return report, events, str(error.exception)

    def test_waits_for_mount_then_download_parent_before_allocating_and_cleans_owned_folder(self):
        report, events, code = self.check_device_setup()
        self.assertEqual(code, 'install_unconfirmed')
        self.assertEqual(events, ['volume', 'volume', 'parent', 'parent', 'parent-ready', 'mkdir',
                                  'install', 'folder-removed'])
        self.assertEqual(report['cleanup'], {'hierarchyFile': True, 'application': False,
                                             'downloadFolder': True})

    def test_mount_or_download_parent_unready_never_allocates_and_never_installs(self):
        for scenario, option in (('shared_storage_mount', 'mount_ready'),
                                 ('download_parent', 'download_ready')):
            with self.subTest(scenario=scenario):
                report, events, code = self.check_device_setup(**{option: False})
                self.assertEqual((report['stage'], code), (scenario, scenario + '_unconfirmed'))
                self.assertNotIn('mkdir', events)
                self.assertNotIn('install', events)
                self.assertEqual(report['cleanup'], {'hierarchyFile': True})

    def test_failed_mkdir_is_classified_without_retry_or_cleanup_of_unowned_path(self):
        report, events, code = self.check_device_setup(mkdir_fails=True)
        self.assertEqual((report['stage'], code), ('download_folder_create', 'download_folder_create_failed'))
        self.assertEqual(config.public_error(GuiFailure(code)), code)
        self.assertEqual(events.count('mkdir'), 1)
        self.assertNotIn('install', events)
        self.assertNotIn('folder-removed', events)
        self.assertEqual(report['cleanup'], {'hierarchyFile': True})

    def test_startup_requires_real_process_and_exact_foreground_before_exercise(self):
        for scenario in ('launcher', 'system_window', 'process_exited', 'cleanup_pid_error'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                avd = Path(root) / 'avd'
                avd.mkdir()
                apk = Path(root) / 'fixture.apk'
                apk.touch()
                env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REF': 'refs/heads/codex/local',
                       'ANDROID_SERIAL': config.SERIAL, 'ANDROID_AVD_HOME': str(avd),
                       'RUNNER_TEMP': root}
                report = {'cleanup': {}}
                installed = forwarded = False
                events = []
                socket = 'localabstract:webview_devtools_remote_42'
                browser = SimpleNamespace(ws=SimpleNamespace(connected=True))
                browser.close = lambda: setattr(browser.ws, 'connected', False)

                def adb(*args, **kwargs):
                    nonlocal installed, forwarded
                    fixed = {
                        ('devices',): f'List of devices attached\n{config.SERIAL}\tdevice',
                        ('shell', 'getprop', 'ro.kernel.qemu'): '1',
                        ('shell', 'getprop', 'ro.build.version.sdk'): '35',
                        ('shell', 'am', 'get-current-user'): '0',
                        ('shell', 'dumpsys', 'activity', 'activities'):
                            'mResumedActivity: ActivityRecord{f8e u0 ' + ACTIVITY + ' t52}',
                    }
                    if args in fixed:
                        return fixed[args]
                    if args[:4] == ('shell', 'pm', 'list', 'packages'):
                        return 'package:' + config.PACKAGE if installed else ''
                    if args[0] == 'install':
                        installed = True
                        return 'Success'
                    if args[0] == 'uninstall':
                        installed = False
                        return 'Success'
                    if args[:4] == ('shell', 'cmd', 'package', 'resolve-activity'):
                        events.append('resolve')
                        return ACTIVITY
                    if args[:2] == ('shell', 'monkey'):
                        events.append('launch')
                        self.assertEqual(args[2:], ('-p', config.PACKAGE, '-c',
                                                   'android.intent.category.LAUNCHER', '1'))
                        return 'Events injected: 1'
                    if args == ('shell', 'pidof', config.PACKAGE):
                        if installed:
                            events.append('pid')
                            return '42'
                        if scenario == 'cleanup_pid_error' and kwargs.get('check', True):
                            raise GuiFailure('untrusted diagnostic')
                        return ''
                    if args == ('shell', 'cat', '/proc/net/unix'):
                        return '' if scenario == 'process_exited' else '0000 @webview_devtools_remote_42'
                    if args == ('forward', 'tcp:0', socket):
                        forwarded = True
                        return '5056'
                    if args == ('forward', '--list'):
                        return f'{config.SERIAL} tcp:5056 {socket}' if forwarded else ''
                    if args == ('forward', '--remove', 'tcp:5056'):
                        forwarded = False
                        return ''
                    if args == ('shell', 'dumpsys', 'window', 'displays'):
                        events.append('focus')
                        title = 'NotificationShade' if scenario == 'system_window' else ACTIVITY
                        return f'Display: mDisplayId=0\n mCurrentFocus=Window{{ab1 u0 {title}}}'
                    if len(args) == 2 and args[0] == 'shell' and f'pidof {config.PACKAGE}' in args[1]:
                        if not installed and scenario == 'cleanup_pid_error':
                            self.assertTrue(kwargs.get('check', True))
                            raise GuiFailure('untrusted diagnostic')
                        return 'absent' if not installed or scenario == 'process_exited' else 'present'
                    if args[:2] == ('shell', 'am') or args[1] in ('mkdir', 'rm', 'rmdir', 'test'):
                        return ''
                    self.fail('unexpected command')

                def one_sample(probe, code, *, timeout=25):
                    return probe() or config.require(False, code)

                with patch.dict(os.environ, env, clear=True), patch.object(config, 'adb', side_effect=adb), \
                        patch.object(config, 'wait_download_storage'), \
                        patch.object(config, 'owned_display', return_value=(1080, 2000)), \
                        patch.object(config, '_connect_ready', return_value=browser), \
                        patch.object(config, 'wait_for', side_effect=one_sample), \
                        patch.object(config, 'exercise') as exercise:
                    if scenario in ('launcher', 'cleanup_pid_error'):
                        config.device_run(apk, report)
                        exercise.assert_called_once()
                    else:
                        code = 'webview_socket_missing' if scenario == 'process_exited' else 'app_foreground_unconfirmed'
                        with self.assertRaisesRegex(GuiFailure, '^' + code + '$'):
                            config.device_run(apk, report)
                        exercise.assert_not_called()
                self.assertEqual(events[:4], ['resolve', 'launch', 'pid', 'focus'])
                self.assertEqual(report['cleanup']['application'], scenario != 'cleanup_pid_error')
                self.assertTrue(all(value for name, value in report['cleanup'].items() if name != 'application'))
                self.assertFalse(installed)
                self.assertFalse(forwarded)
                self.assertEqual(report['launch']['window'], 'system_window' if scenario == 'system_window'
                                 else 'launcher')
                if scenario == 'process_exited':
                    self.assertEqual(report['launch']['process'], 'disappeared')


if __name__ == '__main__':
    unittest.main()
