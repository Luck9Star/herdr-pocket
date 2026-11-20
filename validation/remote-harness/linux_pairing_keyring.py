"""Start one private, non-activating D-Bus and verify public identities on it."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time


SERVICE = 'org.freedesktop.secrets'
NAMESPACE = {'flutter': 'herdr-pocket.flutter', 'tauri': 'herdr-pocket.tauri'}
MARKER = 'HERDR_LINUX_PAIRING_SESSION'
BUS_CONFIG = '''<busconfig><type>session</type><listen>unix:path={socket}</listen>
<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/>
<allow own="*"/></policy></busconfig>'''


class KeyringFailure(Exception):
    """Fixed conditions only. D-Bus paths and key values stay private."""


def bus_call(destination, path, method, *args):
    result = subprocess.run(['/usr/bin/gdbus', 'call', '--session', '--dest', destination,
                             '--object-path', path, '--method', method, *args],
                            capture_output=True, text=True, timeout=8, check=True)
    return result.stdout.strip()


def private_home():
    raw = os.environ.get(MARKER, '')
    root = Path(raw)
    if (not raw or not root.is_absolute() or root.parent != Path('/tmp') or
            not root.name.startswith('herdr-pairing-keyring.') or root.is_symlink() or
            not root.is_dir() or root.stat().st_uid != os.getuid() or
            root.stat().st_mode & 0o077 or os.environ.get('HOME') != str(root / 'home') or
            os.environ.get('DBUS_SESSION_BUS_ADDRESS', '').split(',', 1)[0] != f'unix:path={root / "bus"}' or
            not (root / 'bus').is_socket()):
        raise KeyringFailure('private_keyring_session_required')
    return root


@contextmanager
def start_daemon(daemon):
    root = private_home()
    owner = bus_call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                     'org.freedesktop.DBus.NameHasOwner', SERVICE)
    if owner != '(false,)':
        raise KeyringFailure('private_keyring_already_owned')
    with (root / 'daemon.log').open('xb') as log:
        with subprocess.Popen([str(daemon), '--foreground', '--unlock', '--components=secrets'],
                              stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT) as process:
            try:
                process.stdin.write(secrets.token_hex(24).encode() + b'\n')
                process.stdin.close()
                alias = re.compile(r"\(objectpath '(/org/freedesktop/secrets/collection/[A-Za-z0-9_]+)',\)")
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        item = alias.fullmatch(bus_call(SERVICE, '/org/freedesktop/secrets',
                                                       'org.freedesktop.Secret.Service.ReadAlias', 'default'))
                        if item and bus_call(SERVICE, item[1], 'org.freedesktop.DBus.Properties.Get',
                                             'org.freedesktop.Secret.Collection', 'Locked') == '(<false>,)':
                            break
                    except subprocess.CalledProcessError:
                        pass
                    time.sleep(0.15)
                else:
                    raise KeyringFailure('private_keyring_unlock_unconfirmed')
                yield
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


class KeyringEvidence:
    def __init__(self, route, probe):
        private_home()
        self.namespace = NAMESPACE[route]
        if not probe.is_absolute() or not probe.is_file() or probe.is_symlink():
            raise KeyringFailure('private_keyring_public_probe_required')
        self.probe = probe
        self.verified = set()
        for namespace in NAMESPACE.values():
            if self.items(namespace):
                raise KeyringFailure('private_keyring_not_empty')

    @staticmethod
    def items(namespace):
        reply = bus_call(SERVICE, '/org/freedesktop/secrets', 'org.freedesktop.Secret.Service.SearchItems',
                         "{'application': '" + namespace + "', 'purpose': 'ssh-pairing-v1'}")
        # Reject malformed/locked results before reading item metadata. Object
        # paths are used only inside this fixture and never enter its artifacts.
        path = r"(?:objectpath )?'(/org/freedesktop/secrets/collection/[A-Za-z0-9_/]+)'"
        result = re.fullmatch(r"\((@ao )?\[([^]]*)\], @ao \[\]\)", reply)
        if not result:
            raise KeyringFailure('private_keyring_items_unverified')
        content = result[2]
        if not content:
            return []
        items = re.findall(path, content)
        if not re.fullmatch(path + '(?:, ' + path + ')*', content) or len(set(items)) != len(items):
            raise KeyringFailure('private_keyring_items_unverified')
        return items

    def handles(self, items):
        handles = set()
        for item in items:
            attributes = bus_call(SERVICE, item, 'org.freedesktop.DBus.Properties.Get',
                                  'org.freedesktop.Secret.Item', 'Attributes')
            found = re.findall(r"'handle': '([a-f0-9]{32})'", attributes)
            if len(found) != 1 or found[0] in handles:
                raise KeyringFailure('private_keyring_reference_mismatch')
            handles.add(found[0])
        return handles

    def verify_public(self, handle, public_key):
        result = subprocess.run([str(self.probe), self.namespace, handle], capture_output=True, text=True, timeout=15)
        if result.returncode or result.stdout != public_key + '\n':
            raise KeyringFailure('private_keyring_public_key_mismatch')

    def verify(self, public_key):
        items = self.items(self.namespace)
        if len(items) != len(self.verified) + 1:
            raise KeyringFailure('private_keyring_item_count_wrong')
        handles = self.handles(items)
        if not self.verified <= handles or len(handles - self.verified) != 1:
            raise KeyringFailure('private_keyring_reference_mismatch')
        handle = (handles - self.verified).pop()
        self.verify_public(handle, public_key)
        self.verified.add(handle)

    def verify_existing(self, public_key):
        if len(self.verified) != 1 or self.handles(self.items(self.namespace)) != self.verified:
            raise KeyringFailure('private_keyring_original_reference_changed')
        self.verify_public(next(iter(self.verified)), public_key)


def run_private(command, daemon):
    # The caller bus is not passed into dbus-run-session. This configuration
    # has no service directories and cannot activate the user's keyring.
    with tempfile.TemporaryDirectory(prefix='herdr-pairing-keyring.', dir='/tmp') as name:
        root = Path(name)
        env = {key: value for key, value in os.environ.items() if not key.startswith(('DBUS_', 'GNOME_KEYRING_'))}
        for key, dirname in {'HOME':'home', 'XDG_CONFIG_HOME':'config', 'XDG_DATA_HOME':'data',
                             'XDG_STATE_HOME':'state', 'XDG_CACHE_HOME':'cache', 'XDG_RUNTIME_DIR':'runtime'}.items():
            directory = root / dirname
            directory.mkdir(mode=0o700)
            env[key] = str(directory)
        config = root / 'bus.conf'
        config.write_text(BUS_CONFIG.format(socket=root / 'bus'), encoding='utf-8')
        env.update({MARKER: str(root), 'GSETTINGS_BACKEND': 'memory'})
        return subprocess.run(['/usr/bin/dbus-run-session', f'--config-file={config}', '--', sys.executable,
                               str(Path(__file__).resolve()), '--child', '--daemon', str(daemon), '--', *command],
                              env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--daemon', type=Path, default=Path('/usr/bin/gnome-keyring-daemon'))
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or not Path(command[0]).is_absolute() or not args.daemon.is_absolute():
        parser.error('provide an absolute command and daemon path')
    try:
        if args.child:
            with start_daemon(args.daemon):
                return subprocess.run(command).returncode
        return run_private(command, args.daemon)
    except KeyringFailure as error:
        print(str(error), file=sys.stderr)
    except (OSError, ValueError, subprocess.SubprocessError):
        print('private_keyring_session_failed', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
