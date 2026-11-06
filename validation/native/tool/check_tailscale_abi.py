#!/usr/bin/env python3
"""Load a real candidate ABI and exercise reserved-node retirement only.

Never binds or calls node_start; never performs login, vault access or networking.
The attempted login/dial calls must reject a node that has not been started.
"""
import ctypes as c
import json
from pathlib import Path
import sys
import tempfile


def check(path):
    lib = c.CDLL(str(Path(path).resolve()))
    byte = c.POINTER(c.c_uint8)
    read_type = c.CFUNCTYPE(c.c_int32, c.c_uint64, byte, c.c_uint32,
                           c.POINTER(byte), c.POINTER(c.c_uint32), c.POINTER(c.c_uint32))
    write_type = c.CFUNCTYPE(c.c_int32, c.c_uint64, byte, c.c_uint32, byte, c.c_uint32, c.c_uint32)
    release_type = c.CFUNCTYPE(None, c.c_uint64, byte, c.c_uint32)
    calls = []

    def unexpected(*args):
        calls.append("unexpected store call")
        return 8

    def unexpected_release(*args):
        calls.append("unexpected store release")

    class Store(c.Structure):
        _fields_ = [("read", read_type), ("write", write_type), ("release", release_type)]

    store = Store(read_type(unexpected), write_type(unexpected), release_type(unexpected_release))
    signatures = {
        "hp_ts_abi_version": ([], c.c_uint32),
        "hp_ts_node_new": ([byte, c.c_uint32, c.POINTER(Store), c.c_uint64, c.POINTER(c.c_uint64)], c.c_int32),
        "hp_ts_node_status": ([c.c_uint64, c.c_uint32, byte, c.c_uint32, c.POINTER(c.c_uint32)], c.c_int32),
        "hp_ts_node_begin_login": ([c.c_uint64, c.c_uint32], c.c_int32),
        "hp_ts_node_dial": ([c.c_uint64, byte, c.c_uint32, c.c_uint32, c.POINTER(c.c_uint64)], c.c_int32),
        "hp_ts_node_close": ([c.c_uint64, c.c_uint32], c.c_int32),
        "hp_ts_node_release": ([c.c_uint64], c.c_int32),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    assert lib.hp_ts_abi_version() == 1
    with tempfile.TemporaryDirectory(prefix="herdr-ts-reserved-") as directory:
        data = json.dumps({"directory": directory, "hostname": "herdr-pocket",
                           "control_url": "https://controlplane.tailscale.com"}).encode()
        raw = (c.c_uint8 * len(data)).from_buffer_copy(data)
        node, duplicate = c.c_uint64(), c.c_uint64()
        assert lib.hp_ts_node_new(raw, len(data), c.byref(store), 1, c.byref(node)) == 0 and node.value != 0
        assert lib.hp_ts_node_new(raw, len(data), c.byref(store), 2, c.byref(duplicate)) == 3 and duplicate.value == 0
        output, length = (c.c_uint8 * 8192)(), c.c_uint32()
        assert lib.hp_ts_node_status(node, 1000, output, len(output), c.byref(length)) == 0
        assert json.loads(bytes(output[:length.value])) == {"state": "Stopped", "auth_url": ""}
        assert lib.hp_ts_node_begin_login(node, 1000) == 7
        address = b"synthetic.invalid:22"
        raw_address = (c.c_uint8 * len(address)).from_buffer_copy(address)
        stream = c.c_uint64()
        assert lib.hp_ts_node_dial(node, raw_address, len(address), 1000, c.byref(stream)) == 7 and stream.value == 0
        assert lib.hp_ts_node_release(node) == 3
        assert lib.hp_ts_node_close(node, 1000) == 0
        assert lib.hp_ts_node_release(node) == 0
        assert lib.hp_ts_node_status(node, 1000, output, len(output), c.byref(length)) == 2
        assert list(Path(directory).iterdir()) == []
    assert calls == []
    print(json.dumps({"abiVersion": 1, "reservedNodeRetired": True,
                      "nodeStarted": False, "storeCallbacks": len(calls), "networkCalls": False}))


if __name__ == "__main__":
    check(sys.argv[1])
