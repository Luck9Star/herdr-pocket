#!/usr/bin/env python3
"""Compile the actual manager against the pinned header and a synthetic engine."""
import argparse
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('libzt', type=Path, help='prepared pinned libzt source (read only)')
parser.add_argument('--output', required=True, type=Path, help='fresh external output directory')
args = parser.parse_args()
source = args.libzt.resolve()
output = args.output.resolve()
if output == source or source in output.parents or output.exists():
    parser.error('output must be a fresh directory outside the libzt tree')
output.mkdir(parents=True)
runtime = Path(__file__).resolve().parent.parent
shim = runtime.parent / 'candidates' / 'zerotier' / 'shim'
environment = os.environ.copy()
environment['ASAN_OPTIONS'] = 'abort_on_error=1'
environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=0'
binary = output / 'manager-test'
command = ['clang++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
           '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
           '-I', str(runtime), '-I', str(shim), '-isystem', str(source / 'include'),
           str(runtime / 'manager.cpp'), str(runtime / 'tests' / 'manager_test.cpp'),
           str(runtime / 'tests' / 'bound_fixture.cpp'), '-o', str(binary)]
def run(label, argv):
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment)
    (output / (label + '.log')).write_text(result.stdout)
    print(label + (': passed' if result.returncode == 0 else ': FAILED'), flush=True)
    return result.returncode

if run('compile', command):
    raise SystemExit(1)
ordinary = run('manager', [str(binary)])
fence = run('online-fence', [str(binary), 'online-fence'])
if ordinary or fence:
    raise SystemExit(1)
stream_binary = output / 'stream-test'
stream_command = [str(runtime / 'tests' / 'stream_test.cpp') if item == str(runtime / 'tests' / 'manager_test.cpp')
                  else str(stream_binary) if item == str(binary) else item for item in command]
if run('compile-stream', stream_command) or run('stream', [str(stream_binary)]):
    raise SystemExit(1)
print('Offline synthetic engine only; no actual ZeroTier node or device validation.')
