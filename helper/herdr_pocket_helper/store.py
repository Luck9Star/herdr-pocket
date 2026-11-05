"""Manage only exact, marked lines and per-request receipts for one POSIX user."""
from __future__ import annotations
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

from .wire import MAX_TTL, REQUEST, RESPONSE, VERSION, decode, encode, fingerprint


MAX_FILE = 4 * 1024 * 1024
AUTH = 'authorized_keys'
RECEIPTS = 'herdr-pocket-receipts'


class Refuse(ValueError):
    pass


def check_info(fd, *, directory):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise Refuse('owner or permissions require manual review')
    if directory:
        if not stat.S_ISDIR(info.st_mode):
            raise Refuse('directory required')
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
        raise Refuse('expected a bounded, single-link regular file')
    return info


@contextmanager
def directory(path, *, parent=None, create=False):
    if create:
        try:
            os.mkdir(path, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        check_info(fd, directory=True)
        yield fd
    finally:
        os.close(fd)


def read_at(parent, name, *, missing=None):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        return missing
    with os.fdopen(fd, 'rb') as stream:
        check_info(fd, directory=False)
        value = stream.read(MAX_FILE + 1)
        if len(value) > MAX_FILE:
            raise Refuse('file exceeds size limit')
        return value


def replace(parent, name, value, expected):
    if len(value) > MAX_FILE:
        raise Refuse('file exceeds size limit')
    temp = '.pocket-' + secrets.token_hex(16)
    fd = os.open(temp, os.O_WRONLY | os.O_EXCL | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if read_at(parent, name) != expected:
            raise Refuse('file changed during review; stop and inspect')
        os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temp, dir_fd=parent)
        except FileNotFoundError:
            pass


def classify(content, key, owned):
    """Never claim existing options, comments, duplicates, or a different owner's key."""
    matches = []
    blob = key.split()[1].encode()
    for line in content.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith(b'#'):
            continue
        fields = stripped.split()
        if blob in fields:
            if line == owned:
                matches.append('owned')
            elif fields[:2] == [b'ssh-ed25519', blob]:
                matches.append('existing')
            else:
                raise Refuse('key has options or ambiguous fields; inspect manually')
    if len(matches) > 1:
        raise Refuse('duplicate public key; inspect manually')
    return matches[0] if matches else 'absent'


def request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise Refuse('invalid request ID')
    return value


class Host:
    def __init__(self, home: Path, account: str, host_public: str):
        self.home = home
        self.account = account
        self.pin = fingerprint(host_public)

    def review(self, raw, now):
        req = decode(raw, now=now)
        if req['type'] != REQUEST or req['account'] != self.account or req['host_key'] != self.pin:
            raise Refuse('request account or expected host fingerprint differs')
        return req

    @contextmanager
    def transaction(self, *, create):
        with ExitStack() as stack:
            home = stack.enter_context(directory(self.home))
            ssh = stack.enter_context(directory('.ssh', parent=home, create=create))
            receipts = stack.enter_context(directory(RECEIPTS, parent=ssh, create=create))
            lock = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600, dir_fd=receipts)
            stack.callback(os.close, lock)
            check_info(lock, directory=False)
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield ssh, receipts

    @staticmethod
    def owned_line(req):
        return (req['public_key'] + ' herdr-pocket:v2:' + req['request_id'] + '\n').encode('ascii')

    def authorize(self, raw, confirmed_id, *, now=None):
        clock = (lambda: int(time.time())) if now is None else (lambda: now)
        req = self.review(raw, clock())
        rid = request_id(confirmed_id)
        if rid != req['request_id']:
            raise Refuse('confirmation does not match request')
        name = rid + '.json'
        line = self.owned_line(req)
        with self.transaction(create=True) as (ssh, receipts):
            now = clock()
            self.review(raw, now)
            before = read_at(ssh, AUTH)
            raw_receipt = read_at(receipts, name)
            kind = classify(before or b'', req['public_key'], line)
            if raw_receipt is None:
                if kind == 'owned':
                    raise Refuse('marked line without matching receipt')
                receipt = {'request':req, 'phase':'adding', 'added':kind == 'absent',
                           'separator':bool(before and not before.endswith(b'\n')),
                           'beforeHash':hashlib.sha256(before or b'').hexdigest()}
                raw_receipt = encode(receipt)
                replace(receipts, name, raw_receipt, None)
            else:
                receipt = json.loads(raw_receipt)
                if receipt['request'] != req or receipt['phase'] not in ('adding', 'authorized'):
                    raise Refuse('consumed or mismatched request')
            if receipt['added']:
                if kind == 'absent' and receipt['phase'] == 'adding':
                    if hashlib.sha256(before or b'').hexdigest() != receipt['beforeHash']:
                        raise Refuse('authorization changed since intent was recorded')
                    replace(ssh, AUTH, (before or b'') + (b'\n' if receipt['separator'] else b'') + line, before)
                elif kind != 'owned':
                    raise Refuse('owned key is missing or externally modified')
            elif kind != 'existing':
                raise Refuse('pre-existing key changed; inspect manually')
            if receipt['phase'] == 'adding':
                receipt['phase'] = 'authorized'
                replace(receipts, name, encode(receipt), raw_receipt)
            return self.response(req, 'authorized', receipt['added'], now)

    def revoke(self, rid, confirmed_id, *, now=None):
        now = int(time.time()) if now is None else now
        if request_id(rid) != confirmed_id:
            raise Refuse('confirmation does not match request')
        name = rid + '.json'
        with self.transaction(create=False) as (ssh, receipts):
            raw = read_at(receipts, name)
            if raw is None:
                raise Refuse('no local receipt')
            receipt = json.loads(raw)
            req = receipt['request']
            if (req['request_id'] != rid or req['account'] != self.account or req['host_key'] != self.pin
                    or receipt['phase'] not in ('adding','authorized','revoking','revoked') or receipt['added'] is not True):
                raise Refuse('no owned authorization for this host and account')
            line = self.owned_line(req)
            before = read_at(ssh, AUTH)
            kind = classify(before or b'', req['public_key'], line)
            if receipt['phase'] == 'revoked':
                if kind != 'absent':
                    raise Refuse('authorization changed after revocation')
                return self.response(req, 'revoked', True, now)
            if kind == 'existing' or kind == 'absent' and receipt['phase'] == 'authorized':
                raise Refuse('owned entry was modified; inspect manually')
            if receipt['phase'] != 'revoking':
                receipt['phase'] = 'revoking'
                updated = encode(receipt)
                replace(receipts, name, updated, raw)
                raw = updated
            if kind == 'owned':
                remaining = b''.join(entry for entry in before.splitlines(keepends=True) if entry != line)
                if receipt['separator'] and remaining.endswith(b'\n') and hashlib.sha256(remaining[:-1]).hexdigest() == receipt['beforeHash']:
                    remaining = remaining[:-1]
                replace(ssh, AUTH, remaining, before)
            receipt['phase'] = 'revoked'
            replace(receipts, name, encode(receipt), raw)
            return self.response(req, 'revoked', True, now)

    def response(self, req, state, added, now):
        end = min(now + MAX_TTL, req['expires_at']) if state == 'authorized' else now + MAX_TTL
        obj = {'version':VERSION,'type':RESPONSE,'request_id':req['request_id'],'account':self.account,
               'host_key':self.pin,'fingerprint':fingerprint(req['public_key']),'status':state,
               'authorization_added':added,'issued_at':now,'expires_at':end}
        return encode(obj)

    def review_revocation(self, rid):
        name = request_id(rid) + '.json'
        with directory(self.home) as home, directory('.ssh', parent=home) as ssh, directory(RECEIPTS, parent=ssh) as receipts:
            raw = read_at(receipts, name)
            if raw is None:
                raise Refuse('no local receipt')
            r = json.loads(raw)
            req = r['request']
            if req['request_id'] != rid or req['account'] != self.account or req['host_key'] != self.pin or r['added'] is not True:
                raise Refuse('no owned authorization for this host and account')
            return req
