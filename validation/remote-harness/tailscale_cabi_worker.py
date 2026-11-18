#!/usr/bin/env python3
"""Private process exercising the production Tailscale C ABI with an in-memory store."""
import ctypes
import json
from pathlib import Path
import sys
import threading
import time

BytePointer = ctypes.POINTER(ctypes.c_uint8)
ReadCallback = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint64, BytePointer, ctypes.c_uint32,
    ctypes.POINTER(BytePointer), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
)
WriteCallback = ctypes.CFUNCTYPE(
    ctypes.c_int32, ctypes.c_uint64, BytePointer, ctypes.c_uint32,
    BytePointer, ctypes.c_uint32, ctypes.c_uint32,
)
ReleaseCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint64, BytePointer, ctypes.c_uint32)


class Store(ctypes.Structure):
    _fields_ = [('read', ReadCallback), ('write', WriteCallback), ('release', ReleaseCallback)]


def bytes_array(value):
    return (ctypes.c_uint8 * len(value)).from_buffer_copy(value)


def configure_abi(library):
    uint = ctypes.c_uint32
    handle = ctypes.c_uint64
    uint_pointer = ctypes.POINTER(uint)
    handle_pointer = ctypes.POINTER(handle)
    signatures = {
        'node_new': ([BytePointer, uint, ctypes.POINTER(Store), handle, handle_pointer], ctypes.c_int32),
        'node_start': ([handle, uint], ctypes.c_int32),
        'node_status': ([handle, uint, BytePointer, uint, uint_pointer], ctypes.c_int32),
        'node_begin_login': ([handle, uint], ctypes.c_int32),
        'node_dial': ([handle, BytePointer, uint, uint, handle_pointer], ctypes.c_int32),
        'stream_write': ([handle, BytePointer, uint, uint, uint_pointer], ctypes.c_int32),
        'stream_read': ([handle, BytePointer, uint, uint, uint_pointer], ctypes.c_int32),
        'stream_close': ([handle, uint], ctypes.c_int32),
        'stream_release': ([handle], ctypes.c_int32),
        'node_close': ([handle, uint], ctypes.c_int32),
        'node_release': ([handle], ctypes.c_int32),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, 'hp_ts_' + name)
        function.argtypes = arguments
        function.restype = result


def run(work):
    config = json.loads((work / 'request.json').read_text())
    library = ctypes.CDLL(config['library'])
    configure_abi(library)
    values = {}
    buffers = {}
    lock = threading.Lock()

    def read_store(_context, key, key_size, output, length, found):
        with lock:
            name = ctypes.string_at(key, key_size)
            output[0] = BytePointer()
            length[0] = 0
            found[0] = 0
            if name in values:
                value = values[name]
                buffer = ctypes.create_string_buffer(value, max(1, len(value)))
                buffers[ctypes.addressof(buffer)] = buffer
                output[0] = ctypes.cast(buffer, BytePointer)
                length[0] = len(value)
                found[0] = 1
        return 0

    def write_store(_context, key, key_size, data, size, deleted):
        with lock:
            name = ctypes.string_at(key, key_size)
            if deleted:
                values.pop(name, None)
            else:
                values[name] = ctypes.string_at(data, size)
        return 0

    def release_store(_context, data, size):
        with lock:
            ctypes.memset(data, 0, size)
            buffers.pop(ctypes.cast(data, ctypes.c_void_p).value, None)

    store = Store(ReadCallback(read_store), WriteCallback(write_store), ReleaseCallback(release_store))
    node = ctypes.c_uint64()
    stream = ctypes.c_uint64()
    report = {'event': 'cabi_result', 'states': []}

    def status():
        output = (ctypes.c_uint8 * 8192)()
        size = ctypes.c_uint32()
        code = library.hp_ts_node_status(node, 5000, output, len(output), ctypes.byref(size))
        if code != 0:
            raise RuntimeError('node_status_failed')
        value = json.loads(bytes(output[:size.value]))
        if value['state'] not in report['states']:
            report['states'].append(value['state'])
        return value

    try:
        settings = json.dumps({'directory': str(work / 'node'), 'hostname': 'isolated-cabi-client',
                               'control_url': config['controlUrl']}).encode()
        code = library.hp_ts_node_new(bytes_array(settings), len(settings), ctypes.byref(store), 1, ctypes.byref(node))
        if code != 0:
            raise RuntimeError('node_new_failed')
        report['startCode'] = library.hp_ts_node_start(node, 10000)
        if report['startCode'] != 0:
            raise RuntimeError('node_start_failed')
        deadline = time.monotonic() + 10
        while status()['state'] != 'NeedsLogin' and time.monotonic() < deadline:
            time.sleep(.02)
        report['preLoginNoUrl'] = status()['auth_url'] == ''
        address = f"{config['peerIp']}:{config['peerPort']}".encode()
        report['preLoginDialCode'] = library.hp_ts_node_dial(node, bytes_array(address), len(address), 1000, ctypes.byref(stream))
        if report['preLoginDialCode'] != 7 or stream.value != 0:
            raise RuntimeError('prelogin_dial_not_rejected')
        report['beginLoginCode'] = library.hp_ts_node_begin_login(node, 5000)
        if report['beginLoginCode'] != 0:
            raise RuntimeError('begin_login_failed')
        deadline = time.monotonic() + 25
        url = ''
        while time.monotonic() < deadline:
            url = status()['auth_url']
            if url:
                break
            time.sleep(.05)
        report['authUrlPresent'] = bool(url)
        if url:
            (work / 'auth-url').write_text(url)
            print(json.dumps({'event': 'auth_requested'}), flush=True)
            while not (work / 'auth-complete').exists() and time.monotonic() < deadline:
                time.sleep(.05)
            (work / 'auth-url').unlink(missing_ok=True)
            url = ''
            while status()['state'] != 'Running' and time.monotonic() < deadline:
                time.sleep(.05)
            report['running'] = status()['state'] == 'Running'
            if not report['running']:
                raise RuntimeError('running_not_reached')
            report['dialCode'] = library.hp_ts_node_dial(node, bytes_array(address), len(address), 10000, ctypes.byref(stream))
            if report['dialCode'] != 0:
                raise RuntimeError('dial_failed')
            payload = 'C ABI synthetic 中文 😀'.encode()
            written = ctypes.c_uint32()
            code = library.hp_ts_stream_write(stream, bytes_array(payload), len(payload), 5000, ctypes.byref(written))
            if code != 0 or written.value != len(payload):
                raise RuntimeError('write_failed')
            output = (ctypes.c_uint8 * 4096)()
            size = ctypes.c_uint32()
            code = library.hp_ts_stream_read(stream, output, len(output), 5000, ctypes.byref(size))
            report['payloadEqual'] = code == 0 and bytes(output[:size.value]) == payload
            if not report['payloadEqual']:
                raise RuntimeError('echo_mismatch')
    finally:
        if stream.value:
            report['streamCloseCode'] = library.hp_ts_stream_close(stream, 10000)
            report['streamReleaseCode'] = library.hp_ts_stream_release(stream)
        if node.value:
            report['nodeCloseCode'] = library.hp_ts_node_close(node, 10000)
            report['nodeReleaseCode'] = library.hp_ts_node_release(node)
        report['outstandingReadBuffers'] = len(buffers)
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    run(Path(sys.argv[1]))
