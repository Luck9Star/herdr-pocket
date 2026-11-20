"""Run paired SSH twice through unmodified Linux GTK launcher and normal UI."""
import hashlib
import io
import json
import re
import subprocess

from PIL import ImageGrab

from flutter_linux_stock_ui import StockWindow, accessibility
from linux_pairing_keyring import KeyringFailure
from paired_gui import GuiFailure, bounded_wire, fixture_terminal_id, owned_process, wait_for
from tauri_linux_pairing_restart import no_keyring_writes, require_peers


TARGET_FIELDS = ('host', 'port', 'username', 'session', 'socketPath', 'herdrPath', 'expectedHostKey')
APP = 'herdr_flutter_probe'


def connection_profile(config):
    return json.dumps({'version': 1, 'type': 'herdr-connection-profile', 'provider': 'direct',
                       **{name: config[name] for name in TARGET_FIELDS}}, separators=(',', ':')).encode()


def catalog_reference(path, config, request):
    try:
        catalog = json.loads(bounded_wire(path, 262144))
        profiles = catalog['profiles']
        if catalog['schemaVersion'] != 4 or catalog['pendingCreation'] is not None or len(profiles) != 1:
            raise ValueError()
        record = profiles[0]
        pairing = record['pairing']
        if (not all(record['target'][name] == config[name] for name in TARGET_FIELDS) or
                record['target']['paneId'] != '' or record['enabled'] is not True or record['retired'] is not False or
                pairing['request'] != request or not re.fullmatch(r'[a-f0-9]{32}', pairing['handle']) or
                not re.fullmatch(r'[a-f0-9]{32}', record['id'])):
            raise ValueError()
        return record['id'], pairing['handle'], record['label']
    except (TypeError, KeyError, ValueError, OSError):
        raise GuiFailure('stock_flutter_catalog_binding_unverified') from None


def observed_tick(text):
    markers = re.findall(r'(?i)isolated\s+ssh\s+fixture\.\s+remote\s+input\s+must\s+remain\s+empty\.', text)
    matches = re.findall(r'(?i)synthetic\s+observe\s+tick\s+([0-9]{6})\b', text)
    return int(matches[0]) if len(markers) == len(matches) == 1 else None


def png_observation(ui):
    window = ui.window()
    pixels = ImageGrab.grab(bbox=window.region)
    if ui.window() != window or pixels.size != (window.width, window.height):
        raise GuiFailure('stock_flutter_observation_window_changed')
    png = io.BytesIO()
    pixels.save(png, format='PNG')
    # The original capture is left unchanged; OCR uses a temporary 2× image.
    enlarged = io.BytesIO()
    pixels.resize((pixels.width * 2, pixels.height * 2)).save(enlarged, format='PNG')
    result = subprocess.run(['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', '11'],
                            input=enlarged.getvalue(), capture_output=True, timeout=12, check=True)
    return observed_tick(result.stdout.decode(errors='replace')), png.getvalue()


def observe(ui, approval, terminals, count):
    ui.tap('stock_flutter_pair_connect_missing', '主动审查连接并读取看板', scroll='down')
    ui.tap('stock_flutter_review_missing', '我已通过可信渠道核验主机公钥、账号与目标资料', scroll='down', prefixes=True)
    ui.tap('stock_flutter_connect_missing', '核验并读取会话看板', scroll='down')
    wait_for(lambda: approval.fingerprint_authenticated() if count == 1 else require_peers(approval, count, all_closed=False),
             'stock_flutter_same_key_authentication_missing', timeout=15)
    wait_for(lambda: any(terminals in name.splitlines() for _, name in ui.visible()),
             'stock_flutter_pane_binding_missing', timeout=25)
    ui.tap('stock_flutter_observe_missing', '选择此 pane 观察', scroll='down')
    # Bring the rendered terminal into view using real scroll-wheel events.
    tick = None
    for _ in range(11):
        first, png = png_observation(ui)
        if first is not None:
            tick = first
            break
        ui.scroll('up')
    if tick is None:
        raise GuiFailure('stock_flutter_observation_pixels_missing')

    def later():
        second, candidate = png_observation(ui)
        return candidate if second is not None and second > tick else None
    new_png = wait_for(later, 'stock_flutter_observation_pixels_unchanged', timeout=22)
    return png, new_png


def stop(ui, approval, count):
    ui.tap('stock_flutter_stop_missing', '停止并断开', scroll='down')
    wait_for(lambda: require_peers(approval, count, all_closed=True),
             'stock_flutter_peer_close_unconfirmed', timeout=15)


def tap_pairing(ui):
    ui.tap('stock_flutter_home_add_missing', '添加主机')
    ui.tap('stock_flutter_home_pairing_missing', 'herdr 配对 / 手动连接', prefixes=True)


def enroll(ui, config, approval):
    tap_pairing(ui)
    ui.paste('stock_flutter_public_profile_input_missing', '粘贴公开连接资料 JSON', connection_profile(config))
    ui.tap('stock_flutter_public_profile_preview_missing', '明确填入未审查表单', scroll='down')
    ui.tap('stock_flutter_pair_review_missing', '我已通过可信渠道核验账号、主机公钥与命名会话资料', scroll='down')
    ui.tap('stock_flutter_create_missing', '在此设备创建独立身份并生成公开请求', scroll='down')
    previous = ui.clipboard()
    ui.tap('stock_flutter_copy_public_request_missing', '复制当前公开请求', scroll='down')
    raw = wait_for(lambda: (value if (value := ui.clipboard()) and value != previous else None),
                   'stock_flutter_public_request_missing', timeout=8)
    response = approval.approve(raw)
    ui.paste('stock_flutter_public_response_input_missing', '公开授权／撤销响应 JSON', response, scroll='down')
    ui.tap('stock_flutter_response_review_missing', '我已独立核验响应来源、账号与两端指纹', scroll='down')
    ui.tap('stock_flutter_response_accept_missing', '审查并接受绑定响应', scroll='down')
    return json.loads(raw)


def run_stock(args, root, env, config, approval):
    binary = args.flutter_stock_app.resolve(strict=True)
    if binary.name != APP or not binary.is_file() or not approval.keyring or args.input_fixture:
        raise GuiFailure('stock_flutter_requires_private_read_only_bundle')
    catalog = root / 'data/herdr-pocket.flutter/catalog.json'
    targets = config['paneId'] + ' · ' + fixture_terminal_id(config)
    with accessibility(root, env) as (atspi, glib):
        with owned_process([str(binary)], cwd=root, env=env, log=root / 'stock-first.log') as first:
            ui = StockWindow(first, atspi, glib)
            request = enroll(ui, config, approval)
            before = catalog_reference(catalog, config, request)
            initial = observe(ui, approval, targets, 1)
            authorized = bounded_wire(root / 'authorized_keys', 4096)
            stop(ui, approval, 1)
            with no_keyring_writes(approval, root, env):
                ui.close()
                if catalog_reference(catalog, config, request) != before:
                    raise GuiFailure('stock_flutter_catalog_changed_on_exit')
                with owned_process([str(binary)], cwd=root, env=env, log=root / 'stock-second.log') as second:
                    if first.returncode != 0 or second.pid == first.pid:
                        raise GuiFailure('stock_flutter_independent_process_unverified')
                    ui = StockWindow(second, atspi, glib)
                    ui.find('stock_flutter_original_host_missing', '已恢复 1 个本机资料 · 连接前需重新审查')
                    ui.tap('stock_flutter_original_host_open_missing', '观察会话 · 审查',
                           owner=(before[2], '会话 ' + config['session']))
                    ui.find('stock_flutter_original_device_unverified', '本机原身份已匹配 · 请核验主机指纹后主动审查连接')
                    if not require_peers(approval, 1, all_closed=True):
                        raise GuiFailure('stock_flutter_ssh_before_explicit_review')
                    restored = observe(ui, approval, targets, 2)
                    stop(ui, approval, 2)
                    ui.close()
                try:
                    approval.keyring.verify_existing(request['public_key'])
                except KeyringFailure as error:
                    raise GuiFailure(str(error)) from None
                if (bounded_wire(root / 'authorized_keys', 4096) != authorized or
                        catalog_reference(catalog, config, request) != before):
                    raise GuiFailure('stock_flutter_original_identity_changed')
    if (root / 'received.bin').stat().st_size:
        raise GuiFailure('stock_flutter_peer_received_unexpected_input')
    screens = {'stock-first-before.png': initial[0], 'stock-first-after.png': initial[1],
               'stock-second-before.png': restored[0], 'stock-second-after.png': restored[1]}
    args.output.mkdir(exist_ok=True)
    for name, data in screens.items():
        (args.output / name).write_bytes(data)
    with binary.open('rb') as source:
        binary_sha = hashlib.file_digest(source, 'sha256').hexdigest()
    return {'keyStore': 'private Linux Secret Service', 'paired': True, 'paneChosen': True,
            'restart': {'independentAppProcesses': True, 'naturalWindowClose': True, 'sameSavedHostAndTarget': True,
                        'sameDeviceKeyReauthenticated': True, 'exactPeerAuthentications': 2, 'bothPeersClosed': True,
                        'originalKeyAndAuthorizationUnchanged': True, 'noKeyringWrites': True,
                        'observedIncreasingTicksInBothWindows': True},
            'nativeBundleExecutableSha256': binary_sha,
            'originalX11WindowPngs': {name: hashlib.sha256(data).hexdigest() for name, data in screens.items()}}
