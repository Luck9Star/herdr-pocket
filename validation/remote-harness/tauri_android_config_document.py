"""Tauri API35 configuration transfer through the foreground system document picker."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from android_gui import PACKAGE, SERIAL, adb
from paired_gui import GuiFailure, wait_for
from tauri_android_direct_ssh import _connect_ready

PICKERS = {'com.android.documentsui', 'com.google.android.documentsui'}
ARCHIVE = 'herdr-pocket.hpkt'
CORRUPT = 'herdr-pocket-corrupt.hpkt'
DOWNLOADS = '/storage/emulated/0/Download'
FONT = 19
CONTROL_FONT = 13
MAX_ARCHIVE = 65586
PANEL = '#config-transfer'
SUCCESS = ('导入完成：主机新增 0，主机旧身份停用保留 0，移除旧主机资料 0。'
           '网络配置请核对当前状态；字号偏好已按选择应用。新目标需重新配对。')
REJECTED = '无法验证或解密文件，或文件不受支持；没有导入任何资料。'
HOME_RECORDS = 'no_backup/host-records-v1/hosts.json'
ERRORS = {'unsafe_runner', 'unowned_device', 'invalid_display', 'install_unconfirmed',
          'app_foreground_unconfirmed', 'app_package_unconfirmed', 'debug_forward_invalid',
          'webview_socket_missing', 'webview_not_ready', 'documents_ui_unconfirmed',
          'picker_hierarchy_invalid', 'picker_target_unconfirmed', 'picker_directory_unconfirmed',
          'picker_return_unconfirmed', 'archive_read_failed',
          'archive_invalid', 'tamper_guard_failed', 'catalog_read_failed', 'catalog_mismatch',
          'catalog_changed', 'configuration_ui_unconfirmed', 'shared_storage_mount_unconfirmed',
          'download_parent_unconfirmed', 'download_folder_create_failed'}


def require(condition, error):
    if not condition:
        raise GuiFailure(error)


def public_error(error):
    return str(error) if isinstance(error, GuiFailure) and str(error) in ERRORS else 'driver_failed'


def open_archive(raw, password):
    require(50 < len(raw) <= MAX_ARCHIVE and raw.startswith(b'HPKT\x01\x01'), 'archive_invalid')
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), raw[6:22], 600_000, dklen=32)
    try:
        value = json.loads(AESGCM(key).decrypt(raw[22:34], raw[34:], raw[:34]))
    except (InvalidTag, ValueError, UnicodeError):
        raise GuiFailure('archive_invalid') from None
    require(value == {'version': 2, 'hosts': [], 'networks': [],
                      'preferences': {'terminalFontSize': FONT}}, 'archive_invalid')


def binary_file(prefix, path, limit, error):
    # The only binary reads are of bounded, owned fixture files. ADB stdout is not logged.
    try:
        result = subprocess.run(['adb', '-s', SERIAL, 'exec-out', *prefix, 'head', '-c',
                                 str(limit + 1), path], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GuiFailure(error) from None
    require(result.returncode == 0 and 0 < len(result.stdout) <= limit, error)
    return result.stdout


def catalog(font):
    raw = binary_file(['run-as', PACKAGE], HOME_RECORDS, 131072, 'catalog_read_failed')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise GuiFailure('catalog_read_failed') from None
    require(value == {'version': 1, 'hosts': [], 'networkProfiles': [],
                      'preferences': {'terminalFontSize': font}}, 'catalog_mismatch')
    return raw


def foreground():
    value = adb('shell', 'dumpsys', 'window', 'windows')
    matches = re.findall(r'^\s*mCurrentFocus=Window\{[^\n{}]*\su0\s+([a-zA-Z0-9_.]+)/', value, re.M)
    return matches[0] if len(matches) == 1 else None


def owned_display():
    widths = re.findall(r'^(?:Physical|Override) size: ([0-9]+)x([0-9]+)$',
                        adb('shell', 'wm', 'size'), re.M)
    require(1 <= len(widths) <= 2, 'invalid_display')
    size = tuple(map(int, widths[-1]))
    require(all(1 <= edge <= 8192 for edge in size), 'invalid_display')
    return size


def picker_tree(xml):
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        raise GuiFailure('picker_hierarchy_invalid') from None
    require(root.tag == 'hierarchy' and root.get('rotation') == '0', 'picker_hierarchy_invalid')
    return root


def android_id(node, package, name):
    # The Google API35 image can package AOSP DocumentsUI under Google's app ID.
    return node.get('package') == package and node.get('resource-id') in {
        f'{package}:id/{name}', f'com.android.documentsui:id/{name}'}


def in_picker_scope(root, package, scope, **attributes):
    return [node for surface in root.iter('node') if android_id(surface, package, scope)
            for node in surface.iter('node') if node.get('package') == package
            and all(node.get(key) == value for key, value in attributes.items())]


def native_hit(xml, package, size, *, ancestor, label=None, resource=None, description=None,
               folder=None, save_name=None):
    """Find exactly one visible, enabled target in the current DocumentsUI surface."""
    root = picker_tree(xml)
    if folder and len(in_picker_scope(root, package, 'horizontal_breadcrumb', text=folder)) != 1:
        return None
    if save_name and len(in_picker_scope(root, package, 'container_save', **{
        'class': 'android.widget.EditText', 'resource-id': 'android:id/title', 'text': save_name
    })) != 1:
        return None

    def match(node, lineage):
        return (node.get('package') == package and
                (label is None or node.get('text') == label) and
                (resource is None or node.get('resource-id') == resource) and
                (description is None or node.get('content-desc') == description) and
                any(android_id(item, package, ancestor) for item in lineage))

    def candidates(node, lineage=()):
        path = (*lineage, node)
        if match(node, path):
            for item in reversed(path):
                if item.get('package') != package or android_id(item, package, ancestor):
                    break
                if item.get('clickable') == 'true' and item.get('enabled') == 'true':
                    yield item
                    break
        for child in node:
            yield from candidates(child, path)

    targets = list(candidates(root))
    if len(targets) != 1:
        return None
    bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', targets[0].get('bounds', ''))
    if bounds:
        left, top, right, bottom = map(int, bounds.groups())
        if 0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]:
            return left, top, right, bottom
    return None


class Picker:
    def __init__(self, report):
        self.size = owned_display()
        self.package = None
        self.report = report
        self.scratch = '/data/local/tmp/hp-doc-ui-' + secrets.token_hex(12) + '.xml'
        self.scratch_cleanup_failed = False

    def enter(self):
        self.report['pickerStep'] = 'foreground'
        self.package = wait_for(lambda: (package if (package := foreground()) in PICKERS else None),
                                'documents_ui_unconfirmed')
        self.report['pickerOpens'] += 1

    def hierarchy(self):
        if foreground() != self.package:
            return None
        try:
            adb('shell', 'uiautomator', 'dump', self.scratch, check=False, timeout=10)
            result = adb('exec-out', 'cat', self.scratch, check=False)
            return result if foreground() == self.package else None
        finally:
            try:
                adb('shell', 'rm', '-f', self.scratch)
                adb('shell', 'test', '!', '-e', self.scratch)
            except GuiFailure:
                self.scratch_cleanup_failed = True

    def tap(self, **expected):
        def sample():
            xml = self.hierarchy()
            return xml and native_hit(xml, self.package, self.size, **expected)

        def stable():
            before = sample()
            return before if before and sample() == before else None

        left, top, right, bottom = wait_for(stable, 'picker_target_unconfirmed', timeout=30)
        require(foreground() == self.package, 'documents_ui_unconfirmed')
        adb('shell', 'input', 'tap', (left + right) // 2, (top + bottom) // 2)

    def directory(self, folder):
        self.report['pickerStep'] = 'show_roots'
        xml = wait_for(self.hierarchy, 'picker_directory_unconfirmed')
        if not in_picker_scope(picker_tree(xml), self.package, 'roots_list'):
            self.tap(ancestor='toolbar', description='Show roots')
        self.report['pickerStep'] = 'downloads_root'
        self.tap(ancestor='roots_list', label='Downloads', resource='android:id/title')
        self.report['pickerStep'] = 'owned_download_folder'
        self.tap(ancestor='dir_list', label=folder, resource='android:id/title')

    def save(self, folder):
        self.report['pickerStep'] = 'save_action'
        self.tap(ancestor='container_save', resource='android:id/button1', folder=folder,
                 save_name=ARCHIVE)

    def open(self, folder, filename):
        self.report['pickerStep'] = 'open_file_row'
        self.tap(ancestor='dir_list', label=filename, resource='android:id/title', folder=folder)

    def cancel(self):
        self.report['pickerStep'] = 'cancel'
        require(foreground() == self.package, 'documents_ui_unconfirmed')
        adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')

    def wait_return(self):
        wait_for(lambda: foreground() == PACKAGE, 'picker_return_unconfirmed')
        self.report['pickerStep'] = 'app_foreground'


def checked(browser, expression):
    wait_for(lambda: browser.evaluate(expression) is True, 'configuration_ui_unconfirmed')


def status(browser, selector, expected):
    checked(browser, '(() => { const n = document.querySelector(' + json.dumps(selector)
            + '); return !!n?.getClientRects().length && n.textContent.trim() === '
            + json.dumps(expected) + '; })()')


def set_font(browser, font):
    # This is a number input (select() is unavailable), so enter through a focused
    # control using CDP key events and text input, without assigning DOM values.
    selector = '#terminal-font-size'
    browser.click(selector)
    checked(browser, "document.activeElement === document.querySelector('#terminal-font-size')")
    for phase in ('keyDown', 'keyUp'):
        browser.call('Input.dispatchKeyEvent', {'type': phase, 'key': 'a', 'code': 'KeyA',
                                               'modifiers': 2, 'windowsVirtualKeyCode': 65})
    browser.call('Input.insertText', {'text': str(font)})
    require(browser.read(selector, 'value') == str(font), 'configuration_ui_unconfirmed')
    browser.click('#terminal-font-save')
    status(browser, '#terminal-font-status', '字号已保存；不改变远端终端尺寸。')
    return catalog(font)


def exercise(browser, picker, folder, report):
    def button(label, scope=PANEL):
        browser.click_named(scope, label, 'configuration_ui_unconfirmed')

    def open_panel():
        browser.click('#config-transfer-open')
        checked(browser, "!!document.querySelector('#config-transfer > fieldset input[type=password]')")

    def finished(message):
        picker.wait_return()
        status(browser, PANEL + ' > [role=status]', message)
        checked(browser, """Array.from(document.querySelectorAll('#config-transfer input[type=password]'))
                .length === 3 && Array.from(document.querySelectorAll('#config-transfer input[type=password]'))
                .every(n => n.value === '')""")

    def select(filename):
        button('选择加密文件')
        picker.enter()
        picker.directory(folder)
        picker.open(folder, filename)
        finished('文件已选择，请输入口令预览。')

    def preview(password):
        browser.fill(PANEL + ' > fieldset:nth-of-type(2) input[type=password]', password)
        button('解密并预览')

    folder_path = f'{DOWNLOADS}/{folder}'
    report['stage'] = 'set_export_preference'
    password = secrets.token_hex(16)
    checked(browser, "document.querySelector('#host-empty')?.hidden === false")
    browser.click('#nav-settings')
    original = set_font(browser, FONT)
    open_panel()

    report['stage'] = 'cancel_picker'
    button('选择加密文件')
    picker.enter()
    picker.cancel()
    finished('未选择文件。')
    require(catalog(FONT) == original and not adb('shell', 'ls', '-A', folder_path), 'catalog_changed')
    report['pickerCancelledUnchanged'] = True

    report['stage'] = 'save_picker'
    selector = PANEL + ' > fieldset:first-of-type input[type=checkbox]'
    browser.click(selector)
    checked(browser, 'document.querySelector(' + json.dumps(selector) + ')?.checked === true')
    for index in (1, 2):
        browser.fill(PANEL + f' > fieldset:first-of-type label:nth-of-type({index}) input[type=password]',
                     password)
    button('加密并保存')
    picker.enter()
    picker.directory(folder)
    picker.save(folder)
    finished('已保存加密文件；目标设备仍需独立授权。')
    require(adb('shell', 'ls', '-A', folder_path) == ARCHIVE, 'archive_read_failed')
    report['stage'] = 'independent_archive_check'
    raw = binary_file([], folder_path + '/' + ARCHIVE, MAX_ARCHIVE, 'archive_read_failed')
    open_archive(raw, password)
    report['archive'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'version': 2}
    damaged = raw[:-1] + bytes((raw[-1] ^ 1,))
    try:
        open_archive(damaged, password)
    except GuiFailure:
        pass
    else:
        raise GuiFailure('tamper_guard_failed')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / CORRUPT
        path.write_bytes(damaged)
        adb('push', path, folder_path + '/' + CORRUPT)

    report['stage'] = 'set_control_preference'
    button('关闭')
    baseline = set_font(browser, CONTROL_FONT)
    open_panel()
    for stage, filename, secret in (('wrong_passphrase', ARCHIVE, 'invalid-' + password),
                                    ('tampered_file', CORRUPT, password)):
        report['stage'] = stage
        select(filename)
        preview(secret)
        finished(REJECTED)
        checked(browser, "!document.querySelector('#config-transfer .config-preview')")
        require(catalog(CONTROL_FONT) == baseline, 'catalog_changed')
        report[stage] = True

    report['stage'] = 'preview_original'
    select(ARCHIVE)
    preview(password)
    status(browser, PANEL + ' .config-preview h3', '逐条审查并选择')
    choice = PANEL + ' .config-preview input[type=checkbox]'
    checked(browser, """(() => {const ns=document.querySelectorAll('#config-transfer .config-preview input');
        return ns.length === 1 && ns[0].type === 'checkbox' && !ns[0].checked &&
        ns[0].parentElement.textContent.trim() === '应用导入字号 19（默认不应用）';})()""")
    require(catalog(CONTROL_FONT) == baseline, 'catalog_changed')
    report['previewUnchanged'] = True

    report['stage'] = 'confirm_once'
    browser.click(choice)
    checked(browser, 'document.querySelector(' + json.dumps(choice) + ')?.checked === true')
    report['confirmationAttempts'] = 1
    report['confirmationClicks'] = None  # The sole dispatch can have an unknown outcome.
    button('确认应用所选操作', PANEL + ' .config-preview')
    report['confirmationClicks'] = 1
    finished(SUCCESS)
    checked(browser, "!document.querySelector('#config-transfer .config-preview')")
    require(catalog(FONT) == original and browser.read('#terminal-font-size', 'value') == str(FONT),
            'catalog_changed')
    report['restoredPreference'] = FONT


def wait_download_storage(report):
    # Android can report boot completion before MediaProvider provisions the shared folders.
    def mounted():
        volumes = adb('shell', 'sm', 'list-volumes', 'emulated', check=False, timeout=5)
        primary = [fields for row in volumes.splitlines()
                   if (fields := row.split())[:1] == ['emulated;0']]
        return len(primary) == 1 and len(primary[0]) == 3 and primary[0][1] == 'mounted'

    report['stage'] = 'shared_storage_mount'
    wait_for(mounted, 'shared_storage_mount_unconfirmed', timeout=45)
    report['stage'] = 'download_parent'
    command = (f'if [ -d {DOWNLOADS} ] && [ ! -L {DOWNLOADS} ] && '
               f'[ -w {DOWNLOADS} ] && [ -x {DOWNLOADS} ]; then printf download_ready; fi')
    wait_for(lambda: adb('shell', command, check=False, timeout=5) == 'download_ready',
             'download_parent_unconfirmed', timeout=45)


def device_run(apk, report):
    avd = Path(os.environ.get('ANDROID_AVD_HOME', '/nonexistent')).resolve()
    root = Path(os.environ.get('RUNNER_TEMP', '/nonexistent')).resolve()
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REF', '').startswith('refs/heads/codex/') and
            os.environ.get('ANDROID_SERIAL') == SERIAL and avd != root and
            avd.is_relative_to(root) and avd.is_dir() and apk.is_file(), 'unsafe_runner')
    devices = [line.split()[:2] for line in adb('devices').splitlines()[1:] if line.strip()]

    def installed():
        return 'package:' + PACKAGE in adb('shell', 'pm', 'list', 'packages', PACKAGE).splitlines()

    require(devices == [[SERIAL, 'device']] and adb('shell', 'getprop', 'ro.kernel.qemu') == '1'
            and adb('shell', 'getprop', 'ro.build.version.sdk') == '35'
            and adb('shell', 'am', 'get-current-user') == '0' and not installed(), 'unowned_device')
    report['androidApi'] = 35
    picker = Picker(report)
    folder = 'hp-config-' + secrets.token_hex(12)
    directory = f'{DOWNLOADS}/{folder}'
    browser = None
    forward_socket = None
    install_attempted = False
    owned_directory = False

    def clean(name, action):
        try:
            action()
            report['cleanup'][name] = True
        except Exception:
            report['cleanup'][name] = False

    def remove_app():
        if installed():
            adb('shell', 'am', 'force-stop', PACKAGE)
            adb('uninstall', PACKAGE, timeout=60)
        require(not installed() and not adb('shell', 'pidof', PACKAGE, check=False),
                'app_package_unconfirmed')

    def forward_endpoints(target):
        return [parts[1] for row in adb('forward', '--list').splitlines() if
                len(parts := row.split()) == 3 and parts[0] == SERIAL and parts[2] == target
                and re.fullmatch(r'tcp:[1-9][0-9]{0,4}', parts[1])]

    def remove_forward():
        # An allocation that timed out can still have created its forwarding entry.
        for endpoint in forward_endpoints(forward_socket):
            adb('forward', '--remove', endpoint)
        require(not forward_endpoints(forward_socket), 'debug_forward_invalid')

    def close_browser():
        browser.close()
        require(browser.ws.connected is False, 'debug_forward_invalid')

    def remove_directory():
        adb('shell', 'rm', '-f', directory + '/' + ARCHIVE, directory + '/' + CORRUPT)
        adb('shell', 'rmdir', directory)
        adb('shell', 'test', '!', '-e', directory)

    try:
        report['stage'] = 'prepare_device'
        with apk.open('rb') as stream:
            report['apkSha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        wait_download_storage(report)
        report['stage'] = 'download_folder_create'
        try:
            adb('shell', 'mkdir', directory)
        except GuiFailure:
            # Do not retry or touch this path when exclusive creation was unconfirmed.
            raise GuiFailure('download_folder_create_failed') from None
        owned_directory = True
        report['stage'] = 'install_app'
        install_attempted = True
        require(adb('install', str(apk), timeout=90).splitlines()[-1:] == ['Success'] and installed(),
                'install_unconfirmed')
        adb('shell', 'monkey', '-p', PACKAGE, '-c', 'android.intent.category.LAUNCHER', '1')
        wait_for(lambda: foreground() == PACKAGE, 'app_foreground_unconfirmed', timeout=60)
        pid = wait_for(lambda: adb('shell', 'pidof', PACKAGE, check=False), 'webview_socket_missing')
        require(re.fullmatch(r'[1-9][0-9]*', pid), 'webview_socket_missing')
        socket = 'webview_devtools_remote_' + pid
        wait_for(lambda: any(line.endswith(' @' + socket) for line in
                 adb('shell', 'cat', '/proc/net/unix', check=False).splitlines()),
                 'webview_socket_missing', timeout=60)
        target = 'localabstract:' + socket
        require(not forward_endpoints(target), 'debug_forward_invalid')
        forward_socket = target
        port = adb('forward', 'tcp:0', target)
        require(port.isdigit() and 0 < int(port) <= 65535, 'debug_forward_invalid')
        require(forward_endpoints(target) == ['tcp:' + port], 'debug_forward_invalid')
        browser = wait_for(lambda: _connect_ready(int(port)), 'webview_not_ready', timeout=60)
        exercise(browser, picker, folder, report)
    finally:
        report['cleanup']['hierarchyFile'] = not picker.scratch_cleanup_failed
        if browser is not None:
            clean('debugConnection', close_browser)
        if forward_socket is not None:
            clean('debugForward', remove_forward)
        if install_attempted:
            clean('application', remove_app)
        if owned_directory:
            clean('downloadFolder', remove_directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(os.environ.get('RUNNER_TEMP', '/nonexistent')).resolve()
    output = args.output.absolute()
    require(output == output.resolve() and output != root and output.is_relative_to(root)
            and not os.path.lexists(output), 'unsafe_runner')
    output.mkdir(mode=0o700)
    source = os.environ.get('GITHUB_SHA', '')
    report = {'schemaVersion': 1, 'scenario': 'preferences-only-system-documents-ui',
              'sourceSHA': source if re.fullmatch(r'[0-9a-f]{40}', source) else None,
              'status': 'failed', 'stage': 'preflight', 'confirmationAttempts': 0, 'confirmationClicks': 0,
              'pickerOpens': 0, 'cleanup': {}}
    try:
        device_run(args.apk, report)
        if len(report['cleanup']) == 5 and all(report['cleanup'].values()):
            report.update(status='passed', stage='complete')
        else:
            report['errorCode'] = 'cleanup_unconfirmed'
    except Exception as error:
        report['errorCode'] = public_error(error)
    finally:
        (output / 'manifest.json').write_text(json.dumps(report, sort_keys=True) + '\n', encoding='ascii')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (GuiFailure, OSError):
        raise SystemExit('config_document_output_unavailable') from None
