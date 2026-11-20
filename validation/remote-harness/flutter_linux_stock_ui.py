"""Use AT-SPI and X11 user input against a single stock GTK application window."""
from contextlib import contextmanager
import ctypes as c
from dataclasses import dataclass
import re
import subprocess
import time

from paired_gui import GuiFailure, owned_process, wait_for


@dataclass(frozen=True)
class Window:
    id: int
    x: int
    y: int
    width: int
    height: int

    @property
    def region(self):
        return (self.x, self.y, self.x + self.width, self.y + self.height)


def geometry(raw, window_id):
    pairs = re.findall(r'(?m)^(WINDOW|X|Y|WIDTH|HEIGHT|SCREEN)=(-?[0-9]{1,10})$', raw)
    fields = {name: int(value) for name, value in pairs}
    required = {'WINDOW', 'X', 'Y', 'WIDTH', 'HEIGHT', 'SCREEN'}
    if (len(pairs) != len(required) or fields.keys() != required or fields['WINDOW'] != window_id or
            fields['X'] < 0 or fields['Y'] < 0 or fields['SCREEN'] != 0 or
            not 320 <= fields['WIDTH'] <= 4096 or not 480 <= fields['HEIGHT'] <= 2160):
        raise GuiFailure('stock_flutter_window_geometry_invalid')
    return Window(window_id, fields['X'], fields['Y'], fields['WIDTH'], fields['HEIGHT'])


def unique_match(nodes, label, *, prefixes=False):
    matches = [node for node, name in nodes if (name.split('\n', 1)[0] if prefixes else name) == label]
    if len(matches) > 1:
        raise GuiFailure('stock_flutter_control_not_unique')
    return matches[0] if matches else None


def ancestor_labels(node, expected):
    parent = node.get_parent()
    for _ in range(10):
        if parent is None:
            return False
        if all(label in (parent.get_name() or '').splitlines() for label in expected):
            return True
        parent = parent.get_parent()
    return False


class ClientMessage(c.Structure):
    # Xlib's XClientMessageEvent. The union storage below is sizeof(XEvent).
    _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                ('format', c.c_int), ('data', c.c_long * 5)]


class Event(c.Union):
    _fields_ = [('client', ClientMessage), ('padding', c.c_long * 24)]


def request_window_close(window_id):
    """Send the standard window-manager close message to the verified XID."""
    x = c.CDLL('libX11.so.6')
    x.XOpenDisplay.argtypes, x.XOpenDisplay.restype = [c.c_char_p], c.c_void_p
    x.XInternAtom.argtypes, x.XInternAtom.restype = [c.c_void_p, c.c_char_p, c.c_int], c.c_ulong
    x.XSendEvent.argtypes, x.XSendEvent.restype = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.POINTER(Event)], c.c_int
    x.XSync.argtypes = [c.c_void_p, c.c_int]
    x.XCloseDisplay.argtypes = [c.c_void_p]
    display = x.XOpenDisplay(None)
    if not display:
        raise GuiFailure('stock_flutter_close_display_unavailable')
    try:
        protocols = x.XInternAtom(display, b'WM_PROTOCOLS', 1)
        close = x.XInternAtom(display, b'WM_DELETE_WINDOW', 1)
        if not protocols or not close:
            raise GuiFailure('stock_flutter_close_protocol_unavailable')
        event = Event(client=ClientMessage(type=33, display=display, window=window_id, message_type=protocols, format=32))
        event.client.data[0] = close
        if not x.XSendEvent(display, window_id, 0, 0, c.byref(event)):
            raise GuiFailure('stock_flutter_close_request_rejected')
        x.XSync(display, 0)
    finally:
        x.XCloseDisplay(display)


@contextmanager
def accessibility(root, env):
    from linux_pairing_keyring import bus_call, private_home
    private_home()
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi, GLib
    command = ['/usr/libexec/at-spi-bus-launcher', '--launch-immediately', '--a11y=1', '--screen-reader=1']
    with owned_process(command, cwd=root, env=env, log=root / 'stock-atspi.log') as loader:
        def ready():
            if loader.poll() is not None:
                raise GuiFailure('stock_flutter_atspi_exited')
            try:
                address = bus_call('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus.GetAddress')
            except subprocess.CalledProcessError:
                return False
            return isinstance(address, str) and address.startswith("('unix:")
        wait_for(ready, 'stock_flutter_atspi_unavailable', timeout=12)
        Atspi.init()
        Atspi.set_timeout(1200, 3000)
        try:
            yield Atspi, GLib
        finally:
            Atspi.exit()


class StockWindow:
    def __init__(self, process, atspi, glib):
        self.process, self.atspi, self.glib = process, atspi, glib
        self.id = wait_for(self.current_window, 'stock_flutter_window_unproven', timeout=20)
        self.xdo('windowfocus', '--sync', self.id)
        self.check_focus()

    def xdo(self, *args, check=True):
        try:
            return subprocess.run(['xdotool', *map(str, args)], capture_output=True, text=True, check=check, timeout=6).stdout
        except subprocess.SubprocessError:
            raise GuiFailure('stock_flutter_x11_operation_failed') from None

    def current_window(self):
        if self.process.poll() is not None:
            raise GuiFailure('stock_flutter_process_exited')
        ids = self.xdo('search', '--onlyvisible', '--all', '--pid', self.process.pid,
                       '--name', '^herdr_flutter_probe$', check=False).splitlines()
        if len(ids) > 1 or (ids and not re.fullmatch(r'[1-9][0-9]{0,9}', ids[0])):
            raise GuiFailure('stock_flutter_window_not_unique')
        return int(ids[0]) if ids else None

    def check_focus(self):
        if self.current_window() != self.id or self.xdo('getwindowfocus').strip() != str(self.id):
            raise GuiFailure('stock_flutter_window_not_focused')

    def window(self):
        self.check_focus()
        return geometry(self.xdo('getwindowgeometry', '--shell', self.id), self.id)

    def nodes(self):
        desktop = self.atspi.get_desktop(0)
        apps = [desktop.get_child_at_index(i) for i in range(desktop.get_child_count())]
        owned = [app for app in apps if app and app.get_process_id() == self.process.pid]
        if len(owned) > 1:
            raise GuiFailure('stock_flutter_ax_application_not_unique')
        if not owned:
            return []
        branch = [owned[0]]
        visible = []
        count = 0
        while branch:
            node = branch.pop()
            if node is None:
                continue
            count += 1
            if count > 1800:
                raise GuiFailure('stock_flutter_ax_tree_unbounded')
            branches = node.get_child_count()
            branch.extend(node.get_child_at_index(i) for i in range(branches - 1, -1, -1))
            state = node.get_state_set()
            if state.contains(self.atspi.StateType.SHOWING) and state.contains(self.atspi.StateType.VISIBLE):
                visible.append((node, node.get_name() or ''))
        return visible

    def visible(self):
        try:
            return self.nodes()
        except self.glib.Error:
            return []  # A GTK layout may retire nodes during passive enumeration.

    def scroll(self, direction):
        box = self.window()
        self.xdo('mousemove', box.x + box.width // 2, box.y + box.height // 2,
                 'click', '--repeat', 4, 5 if direction == 'down' else 4)
        time.sleep(0.18)

    def find(self, stage, name, *, scroll=None, prefixes=False):
        locate = lambda: unique_match(self.visible(), name, prefixes=prefixes)
        if not scroll:
            return wait_for(locate, stage, timeout=14)
        for _ in range(18):
            node = locate()
            if node is not None:
                return node
            self.scroll(scroll)
        raise GuiFailure(stage)

    def tap(self, stage, label, *, scroll=None, prefixes=False, owner=()):
        self.find(stage, label, scroll=scroll, prefixes=prefixes)

        def action():
            node = unique_match(self.visible(), label, prefixes=prefixes)
            if node is None:
                return None
            try:
                actions = [node.get_action_name(i) for i in range(node.get_n_actions())] if 'Action' in node.get_interfaces() else []
                state = node.get_state_set()
                if (actions.count('Tap') != 1 or (state.contains(self.atspi.StateType.SENSITIVE) and
                                                   not state.contains(self.atspi.StateType.ENABLED))):
                    return None
                return node, actions.index('Tap')
            except self.glib.Error:
                return None

        node, index = wait_for(action, stage + '_tap_unavailable', timeout=12)
        self.check_focus()
        if owner and not ancestor_labels(node, owner):
            raise GuiFailure(stage + '_owner_not_proven')
        if not node.do_action(index):
            raise GuiFailure(stage + '_tap_rejected')

    def disabled_button(self, stage, label, *, scroll=None):
        self.find(stage, label, scroll=scroll)
        self.check_focus()
        node = unique_match(self.visible(), label)
        if node is None:
            raise GuiFailure(stage)
        try:
            state = node.get_state_set()
            actions = [node.get_action_name(i) for i in range(node.get_n_actions())] if 'Action' in node.get_interfaces() else []
            # Flutter GTK reports SENSITIVE for a button with an enabled state,
            # including when it explicitly withholds ENABLED and the Tap action.
            disabled = (node.get_role() == self.atspi.Role.PUSH_BUTTON and
                        state.contains(self.atspi.StateType.SENSITIVE) and
                        not state.contains(self.atspi.StateType.ENABLED) and
                        'Tap' not in actions)
        except self.glib.Error:
            disabled = False
        if not disabled:
            raise GuiFailure(stage + '_not_disabled')

    def paste(self, stage, label, data, *, scroll=None):
        # Own the OS clipboard with bounded synthetic public data, then send
        # ordinary keyboard shortcuts only to the already focused stock window.
        if not 0 < len(data) <= 2048:
            raise GuiFailure(stage + '_invalid_public_clipboard')
        self.tap(stage, label, scroll=scroll)
        self.check_focus()
        wait_for(lambda: self.focused_field(label), stage + '_input_focus_unverified', timeout=6)
        with subprocess.Popen(['xclip', '-selection', 'clipboard', '-in', '-quiet'],
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as owner:
            try:
                owner.stdin.write(data)
                owner.stdin.close()
                wait_for(lambda: self.clipboard() == data, stage + '_clipboard_not_owned', timeout=4)
                self.check_focus()
                if self.focused_field(label) is None:
                    raise GuiFailure(stage + '_input_focus_unverified')
                self.xdo('key', '--clearmodifiers', 'ctrl+a', 'ctrl+v')
                wait_for(lambda: self.focused_text(label, data), stage + '_paste_unconfirmed', timeout=8)
            finally:
                if owner.poll() is None:
                    owner.terminate()

    def focused_field(self, label):
        node = unique_match(self.visible(), label)
        if node is not None:
            try:
                state = node.get_state_set()
                if (state.contains(self.atspi.StateType.FOCUSED) and state.contains(self.atspi.StateType.EDITABLE) and
                        'Text' in node.get_interfaces()):
                    return node
            except self.glib.Error:
                return None
        return None

    def focused_text(self, label, data):
        node = self.focused_field(label)
        try:
            return node is not None and self.atspi.Text.get_text(node, 0, -1).encode() == data
        except self.glib.Error:
            return False

    def clipboard(self):
        completed = subprocess.run(['xclip', '-out', '-selection', 'clipboard'], capture_output=True, timeout=5)
        return completed.stdout if completed.returncode == 0 and len(completed.stdout) <= 2048 else b''

    def close(self):
        self.check_focus()
        request_window_close(self.id)
        try:
            if self.process.wait(timeout=15) != 0:
                raise GuiFailure('stock_flutter_process_exit_failed')
        except subprocess.TimeoutExpired:
            raise GuiFailure('stock_flutter_process_exit_unconfirmed') from None
