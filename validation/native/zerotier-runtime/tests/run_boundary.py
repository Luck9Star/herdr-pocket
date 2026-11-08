#!/usr/bin/env python3
"""Compile actual patched TUs/lwIP and test an entirely in-memory TCP wire.

No ZeroTier node, identity, kernel/network socket, SDK or download. All output
stays in a fresh external directory; --compile-only never runs the test binary.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--compile-only', action='store_true')
args = parser.parse_args()
source, output = args.source.resolve(), args.output.resolve()
if output.exists() or output == source or source in output.parents:
    parser.error('output must be fresh and outside the source tree')
output.mkdir(parents=True)
(output/'tmp').mkdir()
tests = Path(__file__).resolve().parent
include = [source/'src', source/'include', source/'ext/lwip/src/include',
           source/'ext/lwip-contrib/ports/unix/port/include',
           source/'ext/ZeroTierOne', source/'ext/ZeroTierOne/include',
           source/'ext/ZeroTierOne/node', source/'ext/ZeroTierOne/osdep',
           source/'ext/ZeroTierOne/ext/libnatpmp', source/'ext/concurrentqueue',
           source/'ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/core/include',
           source/'ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/simpleapi/include']
flags = ['-O1','-g','-fPIC','-fsanitize=address,undefined','-fno-omit-frame-pointer',
         '-DZT_SDK=1','-DZT_USE_MINIUPNPC=1','-D_USING_LWIP_DEFINITIONS_=0',
         '-DOMIT_JSON_SUPPORT=1','-Wno-unused-parameter',
         *[item for path in include for item in ['-I',str(path)]]]
environment = {'PATH':os.environ.get('PATH','/usr/bin:/bin'),
               'TMPDIR':str(output/'tmp'),
               'ASAN_OPTIONS':'abort_on_error=1',
               'UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=0'}
lwip = source/'ext/lwip/src'
c_sources = sorted((lwip/'api').glob('*.c'))+sorted((lwip/'core').glob('*.c'))
c_sources += sorted((lwip/'core/ipv4').glob('*.c'))+sorted((lwip/'core/ipv6').glob('*.c'))
c_sources += [p for p in sorted((lwip/'netif').glob('*.c')) if p.name != 'slipif.c']
c_sources += [source/'ext/lwip-contrib/ports/unix/port/sys_arch.c']
cpp_sources = [source/'src/HpBoundRoutes.cpp', source/'src/HpBoundSockets.cpp']
tu_only = [source/'src/VirtualTap.cpp',source/'src/NodeService.cpp']
tap_extras = [source/'ext/ZeroTierOne/node/InetAddress.cpp',source/'ext/ZeroTierOne/osdep/OSUtils.cpp',
              source/'ext/ZeroTierOne/node/Utils.cpp',source/'ext/ZeroTierOne/node/Salsa20.cpp']

def run(label, command, timeout=None):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, env=environment, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or b''
        if isinstance(partial, bytes):
            partial = partial.decode('utf-8', errors='replace')
        (output/(label+'.log')).write_text(partial+'\nTIMEOUT: original isolated subprocess was killed\n')
        raise RuntimeError(label+' timed out; log retained') from None
    (output/(label+'.log')).write_text(result.stdout)
    if result.returncode:
        raise RuntimeError(label+' failed; see '+str(output/(label+'.log')))

def compile_one(path):
    label = path.stem+'-'+hashlib.sha256(str(path.relative_to(source)).encode()).hexdigest()[:8]
    obj = output/(label+'.o')
    cpp = path.suffix == '.cpp'
    command = ['clang++' if cpp else 'clang', *flags,
               *(['-std=c++11','-Wall','-Wextra','-Werror=misleading-indentation',
                  '-DZTS_C_API_ONLY=1','-DZTS_DISABLE_CENTRAL_API=1'] if cpp else
                 ['-Wno-tautological-constant-out-of-range-compare','-Wno-parentheses-equality','-DLWIP_DBG_TYPES_ON=0']),
               '-c',str(path),'-o',str(obj)]
    (output/(label+'.command.json')).write_text(json.dumps(command))
    run(label, command)
    return obj

with ThreadPoolExecutor(max_workers=4) as pool:
    paths = c_sources+cpp_sources+tu_only+tap_extras
    objects = dict(zip(paths,pool.map(compile_one,paths)))
print('Compiled '+str(len(objects))+' actual patched lwIP/boundary/VirtualTap/NodeService TUs',flush=True)
if not args.compile_only:
    binary = output/'boundary-test'
    run('link',['clang++',*flags,'-std=c++11',str(tests/'boundary_test.cpp'),
                *[str(objects[path]) for path in c_sources+cpp_sources],'-pthread','-o',str(binary)])
    run('test',[str(binary)],timeout=20)
    print((output/'test.log').read_text().strip(),flush=True)
    tap_binary = output/'tap-reconfig-test'
    tap_objects = c_sources+[source/'src/HpBoundRoutes.cpp',source/'src/VirtualTap.cpp']+tap_extras
    run('link-tap',['clang++',*flags,'-std=c++11','-DZTS_C_API_ONLY=1','-DZTS_DISABLE_CENTRAL_API=1',
                    str(tests/'tap_reconfig_test.cpp'),*[str(objects[path]) for path in tap_objects],
                    '-Wl,-dead_strip','-pthread','-o',str(tap_binary)])
    run('test-tap',[str(tap_binary)],timeout=20)
    print((output/'test-tap.log').read_text().strip(),flush=True)
    gate_binary = output/'gate-reopen-test'
    run('link-gate',['clang++',*flags,'-std=c++11','-Wall','-Wextra',
                     '-Werror=misleading-indentation','-Wno-unused-parameter',
                     '-DZTS_C_API_ONLY=1','-DZTS_DISABLE_CENTRAL_API=1',
                     str(tests/'gate_reopen_test.cpp'),'-pthread','-o',str(gate_binary)])
    run('test-gate',[str(gate_binary)],timeout=20)
    print((output/'test-gate.log').read_text().strip(),flush=True)
print('No ZeroTier node/identity or real network was used.')
