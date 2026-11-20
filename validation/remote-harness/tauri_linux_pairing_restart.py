"""Independently check app lifetime, keyring and SSH around a stock restart."""
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import stat

from linux_pairing_keyring import DBUS, DBUS_PATH, KeyringFailure, bus_call
from paired_gui import GuiFailure, bounded_wire, fixture_terminal_id, owned_process, stop_tauri_observation, wait_for
from pairing import fingerprint
from s06_tauri_gui import peer_log_evidence


PRIVATE_ENV = ('HOME', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME',
               'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR')
DENIAL_NOTICE = {
    'locked': '系统密钥环已锁定，请先解锁后重新核查原身份。',
    'unavailable': '系统密钥服务不可用，请配置或启动后重新核查；不会使用明文或替代身份。',
}


@dataclass(frozen=True)
class AppProcess:
    pid: int
    start: int


def process_stat(path):
    try:
        fields = path.read_text().rpartition(') ')[2].split()
        return (int(fields[1]), int(fields[19]), fields[0])
    except (OSError, ValueError, IndexError):
        return None


def owned_stock_app(owner_pid, binary, env, proc=Path('/proc')):
    expected = binary.stat()
    owned = []
    for item in proc.iterdir():
        if not item.name.isdecimal():
            continue
        try:
            actual = (item / 'exe').stat()
        except OSError:
            continue
        if not os.path.samestat(expected, actual):
            continue
        raw = process_stat(item / 'stat')
        if raw is None or raw[2] == 'Z':
            continue
        parent, start, _ = raw
        for _ in range(32):
            if parent == owner_pid:
                try:
                    entries = bounded_wire(item / 'environ', 262144).split(b'\0')
                except OSError:
                    break
                if not all(env.get(name) and f'{name}={env[name]}'.encode() in entries for name in PRIVATE_ENV):
                    raise GuiFailure('restart_app_private_environment_mismatch')
                owned.append(AppProcess(int(item.name), start))
                break
            if parent <= 1:
                break
            ancestor = process_stat(proc / str(parent) / 'stat')
            if ancestor is None:
                break
            parent = ancestor[0]
    if len(owned) > 1:
        raise GuiFailure('restart_stock_app_ambiguous')
    return owned[0] if owned else None


def process_exited(app, proc=Path('/proc')):
    entry = proc / str(app.pid)
    process = process_stat(entry / 'stat')
    if process is None:
        return not entry.exists()
    return process[1] != app.start or process[2] == 'Z'


def owner_lock_state(path, same_file=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise GuiFailure('restart_owner_lock_invalid')
        file_id = (info.st_dev, info.st_ino)
        if same_file is not None and file_id != same_file:
            raise GuiFailure('restart_owner_lock_replaced')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return file_id, False
            raise
        fcntl.flock(stream, fcntl.LOCK_UN)
        return file_id, True


def require_peers(approval, count, *, all_closed):
    path = approval.root / 'sshd.log'
    text = bounded_wire(path, 2_097_152)
    peers = peer_log_evidence(approval)
    if text != bounded_wire(path, 2_097_152):
        return False  # sshd appended while we were sampling the two views.
    if any(row[2] for row in peers):
        raise GuiFailure('restart_peer_reset')
    text = text.decode(errors='replace')
    total = len(re.findall(r'^Accepted [^\n]+ from ', text, flags=re.MULTILINE))
    if total != len(peers) or len(peers) > count or len({peer[0] for peer in peers}) != len(peers):
        raise GuiFailure('restart_unexpected_authentication')
    if len(peers) != count:
        return False
    return all(peer[1] for peer in peers) if all_closed else (peers[0][1] and not peers[-1][1])


def one_saved_host(driver):
    script = """const home=document.querySelector('#host-home');
        if (!home?.getClientRects().length) return [];
        return [...home.querySelectorAll('#host-list .saved-host-card')]
            .filter(card=>card.getClientRects().length).map(card=>card.dataset.hostId);"""
    ids = driver.call('POST', driver.session + '/execute/sync', {'script':script, 'args':[]})
    if ids == []:
        return None
    if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or not re.fullmatch(r'[a-f0-9]{32}', ids[0]):
        raise GuiFailure('restart_saved_host_not_unique')
    return ids[0]


def rendered_frames(driver):
    selector = '#remote-captured'
    full = driver.attribute(selector, 'data-full-frames')
    delta = driver.attribute(selector, 'data-delta-frames')
    if all(isinstance(count, str) and re.fullmatch(r'[0-9]{1,7}', count) and 0 < int(count) <= 1_000_000
           for count in (full, delta)):
        return {'full': int(full), 'delta': int(delta)}
    return None


@contextmanager
def no_keyring_writes(approval, root, env, *, service_available=True):
    # --profile prints only D-Bus headers. Never retain an argument or secret.
    watched = {
        DBUS: ('GetId',),
        'org.freedesktop.Secret.Service': ('SearchItems', 'CreateCollection', 'SetAlias', 'Lock', 'Unlock'),
        'org.freedesktop.Secret.Collection': ('CreateItem', 'Delete'),
        'org.freedesktop.Secret.Item': ('Delete', 'SetSecret'),
    }
    args = ['/usr/bin/stdbuf', '-oL', '/usr/bin/dbus-monitor', '--session', '--profile']
    args.extend(f"type='method_call',interface='{interface}',member='{method}'"
                for interface, methods in watched.items() for method in methods)
    args.append("type='method_call',interface='org.freedesktop.DBus.Properties',member='Set',"
                "path_namespace='/org/freedesktop/secrets'")
    log = root / 'restart-keyring-profile.log'
    with owned_process(args, cwd=root, env=env, log=log) as monitor:
        marker = b'SearchItems' if service_available else b'GetId'

        def markers():
            if monitor.poll() is not None:
                raise GuiFailure('restart_keyring_monitor_exited')
            profile = bounded_wire(log, 131072)
            if re.search(rb'(?m)^mc\t[^\n]*\t(?:CreateCollection|SetAlias|Lock|Unlock|CreateItem|Delete|SetSecret|Set)\s*$', profile):
                raise GuiFailure('restart_keyring_write_observed')
            return len(re.findall(rb'(?m)^mc\t[^\n]*\t' + marker + rb'\s*$', profile))

        def live_marker():
            before = markers()
            if service_available:
                approval.keyring.items(approval.keyring.namespace)
            else:
                reply = bus_call(DBUS, DBUS_PATH, DBUS + '.GetId')
                if not re.fullmatch(r"\('[a-f0-9]{32}',\)", reply):
                    raise GuiFailure('restart_private_bus_identity_unproven')
            return markers() > before

        wait_for(live_marker, 'restart_keyring_monitor_unproven', timeout=8)
        yield
        wait_for(live_marker, 'restart_keyring_monitor_lost', timeout=8)


class RestartReceipt:
    def __init__(self, app, root, env, config, approval):
        data = root / 'data'
        if env.get('XDG_DATA_HOME') != str(data) or data.is_symlink():
            raise GuiFailure('restart_catalog_not_private')
        self.app, self.root, self.env, self.config, self.approval = app, root, env, config, approval
        self.lock = data / 'dev.herdrpocket.tauriprobe' / 'host-records-v1' / 'owner.lock'
        self.denial_catalog = None
        self.first = self.lock_id = self.host_id = self.authorized = self.approval_id = self.terminal = None

    def first_started(self, owner_pid):
        self.first = wait_for(lambda: owned_stock_app(owner_pid, self.app, self.env), 'restart_first_app_unproven')

    def before_first_exit(self, driver, owner_pid):
        if not self.first or owned_stock_app(owner_pid, self.app, self.env) != self.first:
            raise GuiFailure('restart_first_app_changed')
        self.lock_id, unlocked = owner_lock_state(self.lock)
        if unlocked:
            raise GuiFailure('restart_first_app_not_lock_owner')
        wait_for(lambda: require_peers(self.approval, 1, all_closed=True), 'restart_first_peer_not_closed')
        self.host_id = wait_for(lambda: one_saved_host(driver), 'restart_original_home_missing')
        self.terminal = fixture_terminal_id(self.config)
        self.authorized = bounded_wire(self.root / 'authorized_keys', 4096)
        self.approval_id = self.approval.request_id
        if not self.authorized or not self.approval_id:
            raise GuiFailure('restart_original_authorization_missing')
        self.verify_original_key()

    def verify_original_key(self):
        if (self.approval_id != self.approval.request_id or
                self.authorized != bounded_wire(self.root / 'authorized_keys', 4096)):
            raise GuiFailure('restart_authorization_changed')
        try:
            fields = self.authorized.splitlines()[0].decode('ascii').split()
            self.approval.keyring.verify_existing(' '.join(fields[:2]))
        except KeyringFailure as error:
            raise GuiFailure(str(error)) from None

    def after_first_exit(self):
        def released():
            return process_exited(self.first) and owner_lock_state(self.lock, self.lock_id)[1]
        wait_for(released, 'restart_first_app_or_owner_lock_not_released', timeout=15)

    def open_original(self, driver, owner_pid):
        next_app = wait_for(lambda: owned_stock_app(owner_pid, self.app, self.env), 'restart_second_app_unproven')
        if next_app == self.first or not process_exited(self.first):
            raise GuiFailure('restart_app_process_reused')
        if wait_for(lambda: one_saved_host(driver), 'restart_restored_home_missing') != self.host_id:
            raise GuiFailure('restart_saved_host_changed')
        if owner_lock_state(self.lock, self.lock_id)[1]:
            raise GuiFailure('restart_second_app_not_lock_owner')

        card = f'#host-list .saved-host-card[data-host-id="{self.host_id}"]'
        driver.click(card + ' .saved-host-actions > button.primary')
        review = '#host-restore-review'
        driver.wait_control(review)
        description = driver.read('#host-restore-description')
        if ('主机：' + fingerprint(self.config['expectedHostKey']) not in description or
                '设备：' + self.approval.fingerprint not in description or
                driver.read(review, 'checked') is not False or driver.read('#host-restore', 'disabled') is not True or
                driver.read('#remote-connect', 'disabled') is not True or driver.read('#pair-request', 'value') != ''):
            raise GuiFailure('restart_original_identity_review_missing')
        for field, key in [('host', 'host'), ('port', 'port'), ('user', 'username'), ('session', 'session'),
                           ('herdr', 'herdrPath'), ('socket', 'socketPath'), ('pin', 'expectedHostKey')]:
            if driver.read('#remote-' + field, 'value') != str(self.config[key]):
                raise GuiFailure('restart_saved_target_changed')
        driver.click(review)
        driver.click('#host-restore')
        return next_app

    def second(self, driver, owner_pid):
        self.open_original(driver, owner_pid)
        wait_for(lambda: f'原设备公钥匹配 · {self.approval.fingerprint}' in driver.read('#pair-status'),
                 'restart_original_key_review_failed')
        if (driver.read('#remote-review', 'checked') is not False or
                driver.read('#remote-connect', 'disabled') is not True or
                not require_peers(self.approval, 1, all_closed=True)):
            raise GuiFailure('restart_ssh_before_explicit_review')
        driver.click('#remote-review')
        driver.click('#remote-connect')
        wait_for(lambda: require_peers(self.approval, 2, all_closed=False), 'restart_second_same_key_authentication_missing')
        pane = '#remote-panes button'
        if (not wait_for(lambda: driver.read(pane), 'restart_pane_missing').startswith(self.config['paneId'] + ' · ') or
                fixture_terminal_id(self.config) != self.terminal):
            raise GuiFailure('restart_observe_target_changed')
        driver.click(pane)
        frames = wait_for(lambda: rendered_frames(driver), 'restart_observe_frames_missing')
        stop_tauri_observation(driver)
        wait_for(lambda: require_peers(self.approval, 2, all_closed=True), 'restart_second_peer_not_closed')
        self.verify_original_key()
        return {'independentAppProcesses': True, 'firstOwnerLockReleased': True,
                'samePrivateSession': True, 'sameSavedHostAndTarget': True,
                'sameDeviceKeyReauthenticated': True, 'exactPeerAuthentications': 2,
                'bothPeersClosed': True, 'secondObservedFrames': frames,
                'originalKeyAndAuthorizationUnchanged': True, 'noKeyringWrites': True}

    def saved_catalog(self):
        path = self.lock.with_name('hosts.json')
        pending = self.lock.with_name('linux-pairing-pending.json')
        if path.is_symlink() or not path.is_file() or pending.exists() or pending.is_symlink():
            raise GuiFailure('denial_original_catalog_unproven')
        raw = bounded_wire(path, 131072)
        catalog = json.loads(raw)
        hosts = catalog.get('hosts') if isinstance(catalog, dict) else None
        if not isinstance(hosts, list) or len(hosts) != 1 or not isinstance(hosts[0], dict):
            raise GuiFailure('denial_original_catalog_unproven')
        original = hosts[0]
        reference = original.get('pairing')
        if (original.get('id') != self.host_id or original.get('enabled') is not True or
                not isinstance(reference, dict) or reference.get('handle') not in self.approval.keyring.verified):
            raise GuiFailure('denial_original_catalog_unproven')
        return raw

    def before_denial(self):
        self.denial_catalog = self.saved_catalog()

    def second_denied(self, driver, owner_pid, mode):
        app = self.open_original(driver, owner_pid)
        notice = '#host-restore-status'
        wait_for(lambda: driver.read(notice) == DENIAL_NOTICE[mode], 'denial_original_identity_notice_missing')
        driver.wait_control(notice)
        if (driver.read(notice) != DENIAL_NOTICE[mode] or
                driver.read('#host-restore-review', 'checked') is not True or
                driver.read('#remote-review', 'checked') is not False or
                driver.read('#remote-connect', 'disabled') is not True or
                driver.read('#pair-create', 'disabled') is not True or
                driver.read('#pair-request', 'value') != '' or
                self.saved_catalog() != self.denial_catalog):
            raise GuiFailure('denial_original_identity_controls_changed')
        return app

    def wait_second_exit(self, second):
        wait_for(lambda: process_exited(second) and owner_lock_state(self.lock, self.lock_id)[1],
                 'denial_second_app_or_owner_lock_not_released')

    def after_denial(self, mode):
        if self.saved_catalog() != self.denial_catalog or fixture_terminal_id(self.config) != self.terminal:
            raise GuiFailure('denial_original_catalog_or_target_changed')
        self.verify_original_key()
        wait_for(lambda: require_peers(self.approval, 1, all_closed=True), 'denial_original_peer_close_unproven')
        self.approval.verify_ssh(b'')
        return {'mode': mode, 'independentAppProcesses': True, 'noticeVisible': True, 'connectDisabled': True,
                'originalHostAndIdentityRetained': True, 'authorizationUnchanged': True,
                'exactPeerAuthentications': 1, 'firstPeerClosed': True, 'noKeyringWrites': True,
                'receivedInputBytes': 0}
