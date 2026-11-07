"""Share public coordinates, review pairing, or explicitly change authorization."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from .wire import MAX_BYTES, fingerprint, public_key


def read_request(path):
    if path == '-':
        return sys.stdin.buffer.read(MAX_BYTES + 1)
    with Path(path).open('rb') as stream:
        return stream.read(MAX_BYTES + 1)


def read_host_public(path):
    if not path.endswith('.pub'):
        raise ValueError('a .pub SSH host public-key file is required')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        record = stream.read(4097)
    if len(record) > 4096 or len(record.splitlines()) != 1:
        raise ValueError('expected one host public key')
    words = record.decode('ascii').split()
    return public_key(' '.join(words[:2]))


def confirm(action, req):
    phrase = action + ' ' + req['request_id']
    with open('/dev/tty', 'r+', encoding='utf-8') as tty:
        tty.write(f"账号 {req['account']}\n主机指纹 {req['host_key']}\n"
                  f"设备 {req['device']} · {fingerprint(req['public_key'])}\n"
                  f"请求 {req['request_id']}\n输入 {phrase} 以确认，其他输入取消：\n")
        tty.flush()
        if tty.readline(100).rstrip('\r\n') != phrase:
            raise ValueError('cancelled by host operator')
    return req['request_id']


def emit_response(raw, output_format, *, newline=True):
    if output_format == 'json':
        sys.stdout.buffer.write(raw + (b'\n' if newline else b''))
        return
    import qrcode
    from qrcode.image.svg import SvgPathFillImage
    image = qrcode.make(raw, image_factory=SvgPathFillImage, border=4)
    image.save(sys.stdout.buffer)


def main(argv=None):
    parser = argparse.ArgumentParser(description='herdr-pocket 一次性主机配对工具（POSIX OpenSSH 默认授权文件）。')
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('preview', 'authorize', 'revoke'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--host-public-key', required=True, metavar='FILE.pub')
        if action == 'revoke':
            cmd.add_argument('--request-id', required=True)
        else:
            cmd.add_argument('--request', required=True, metavar='FILE|-')
        if action != 'preview':
            cmd.add_argument('--format', choices=('json','svg'), default='json')
    profile = sub.add_parser('profile', help='输出公开连接资料；不会添加设备授权')
    profile.add_argument('--host-public-key', required=True, metavar='FILE.pub')
    profile.add_argument('--host', required=True)
    profile.add_argument('--port', required=True, type=int)
    profile.add_argument('--provider', required=True, choices=('direct', 'tailscale', 'easytier', 'zerotier'))
    profile.add_argument('--session', required=True)
    profile.add_argument('--socket-path', required=True)
    profile.add_argument('--herdr-path', required=True)
    profile.add_argument('--format', choices=('json', 'svg'), default='json')
    args = parser.parse_args(argv)
    try:
        if os.name != 'posix' or os.getuid() != os.geteuid() or os.geteuid() == 0:
            raise ValueError('use a non-root POSIX SSH login account')
        import pwd
        account = pwd.getpwuid(os.geteuid())
        if args.action == 'profile':
            from .profile import encode_profile
            raw = encode_profile({'version': 1, 'type': 'herdr-connection-profile',
                                  'host': args.host, 'port': args.port, 'username': account.pw_name,
                                  'provider': args.provider, 'session': args.session,
                                  'socketPath': args.socket_path, 'herdrPath': args.herdr_path,
                                  'expectedHostKey': read_host_public(args.host_public_key)})
            emit_response(raw, args.format, newline=False)
            return 0
        from .store import Host
        host = Host(Path(account.pw_dir), account.pw_name, read_host_public(args.host_public_key))
        if getattr(args, 'format', 'json') == 'svg':
            # Resolve optional format support before any authorization change.
            from qrcode.image.svg import SvgPathFillImage  # noqa: F401
        if args.action == 'revoke':
            req = host.review_revocation(args.request_id)
            raw = host.revoke(args.request_id, confirm('REVOKE', req))
        else:
            request = read_request(args.request)
            req = host.review(request, int(time.time()))
            if args.action == 'preview':
                print(json.dumps({'account':req['account'], 'device':req['device'], 'request_id':req['request_id'],
                                  'device_fingerprint':fingerprint(req['public_key']), 'host_key':host.pin,
                                  'expires_at':req['expires_at'], 'authorization_written':False}))
                return 0
            raw = host.authorize(request, confirm('AUTHORIZE', req))
        emit_response(raw, args.format)
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        if args.action == 'profile':
            print('未生成连接资料。请核对显式目标、端口、命名会话、绝对路径和主机 .pub 公钥；资料仅用于连接审查，不能授权设备。', file=sys.stderr)
            return 1
        print('配对操作未确认完成。核对账号、请求期限、文件权限及本机收据后重试；如授权状态未知，请按原请求 ID 核查。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
