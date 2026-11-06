#!/usr/bin/env python3
"""Compile pinned patched TUs and run native-only offline tests. No node start.
Requires an already prepared + candidate-patched source root. Never downloads.
"""
from pathlib import Path
import argparse, subprocess, os, re, shutil, hashlib
parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
source=args.source.resolve();out=args.output.resolve()
if out==source or source in out.parents:
    parser.error('output must stay outside the verified source tree')
if out.exists():
    parser.error('output must be fresh/nonexistent; preserve earlier logs')
out.mkdir(parents=True,exist_ok=False)
env=os.environ.copy()
env['UBSAN_OPTIONS']='halt_on_error=1:print_stacktrace=0'
env['ASAN_OPTIONS']='abort_on_error=1'
candidate=Path(__file__).resolve().parents[1];shim=candidate/'shim';tests=candidate/'tests'
inc=[source/'src',source/'include',source/'ext/ZeroTierOne',source/'ext/ZeroTierOne/include',source/'ext/ZeroTierOne/node',source/'ext/ZeroTierOne/osdep',source/'ext/ZeroTierOne/ext/libnatpmp',source/'ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/core/include',source/'ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/simpleapi/include',source/'ext/concurrentqueue',source/'ext/lwip/src/include',source/'ext/lwip-contrib/ports/unix/port/include',shim]
base=['clang++','-std=c++11','-Wall','-Wextra','-Werror=misleading-indentation','-Wno-unused-parameter','-DZT_SDK=1','-DZT_USE_MINIUPNPC=1','-D_USING_LWIP_DEFINITIONS_=0','-DZTS_C_API_ONLY=1','-DZTS_DISABLE_CENTRAL_API=1','-DOMIT_JSON_SUPPORT=1',*[v for p in inc for v in ('-I',str(p))]]
sanitize=['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer']
def run(label,cmd):
    result=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
    # A regression must fail without persisting UBSan's scalar/key operands.
    output=re.sub(r'runtime error:.*', 'runtime error: [operands redacted]', result.stdout)
    with (out/(label+'.log')).open('w') as log:
        log.write(output)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode,cmd)
    print(label+': passed',flush=True)
# Compile actual modified production units, not substitute class definitions.
for name in ['Controls','Events','NodeService','VirtualTap']:
    run('tu-'+name,[*base,'-c',str(source/'src'/(name+'.cpp')),'-o',str(out/(name+'.o'))])
for name in ['hp_zt_identity','hp_zt_lifecycle']:
    run('tu-'+name,[*base,'-c',str(shim/(name+'.cpp')),'-o',str(out/(name+'.o'))])
core=[]
for name in ['Identity','ECC','Salsa20','SHA512','Utils']:
    obj=out/(name+'-san.o')
    run('core-'+name,[*base,*sanitize,'-c',str(source/'ext/ZeroTierOne/node'/(name+'.cpp')),'-o',str(obj)])
    core.append(str(obj))
# Includes the actual ECC.cpp in the test TU to reach its private static helpers.
# Its bigint oracle is independent of ECC.cpp and uses public deterministic data.
# Do this before random identity generation so an old-source regression never
# persists diagnostics from a temporary private identity.
ecc_dependencies=[str(out/(name+'-san.o')) for name in ['Salsa20','SHA512','Utils']]
# Reconstruct the exact pinned ECC preimage outside the source tree. These
# deliberate failures prove the tests detect the removed UB, rather than merely
# accepting any exit status or changing a sanitizer/standard flag to hide it.
control=out/'unpatched-control';control.mkdir()
shutil.copyfile(source/'ext/ZeroTierOne/node/ECC.cpp',control/'ECC.cpp')
run('reconstruct-ecc-preimage',['patch','--reverse','--batch','--fuzz=0','-p4','--directory',str(control),'--input',str(candidate/'patches/0007-defined-ecc-shifts.patch')])
if hashlib.sha256((control/'ECC.cpp').read_bytes()).hexdigest()!='9a9aa9ce6d15745f22babfad7e9905661532f67e9d87fc2518ca75e43cfc581b':
    raise ValueError('unpatched ECC preimage mismatch')
binary=out/'ecc-unpatched-driver'
run('build-ecc-negative-control',[base[0],'-I',str(control),*base[1:],*sanitize,str(tests/'ecc_driver.cpp'),*ecc_dependencies,'-o',str(binary)])
run('test-ecc-negative-control',['python3',str(tests/'ecc_reference_test.py'),str(binary),'--negative-control'])
for standard,optimization in [('c++11','-O0'),('c++11','-O2'),('c++17','-O2'),('c++20','-O2')]:
    label='ecc-'+standard+'-'+optimization[1:]
    binary=out/(label+'-driver')
    run('build-'+label,[*base,*sanitize,'-std='+standard,optimization,str(tests/'ecc_driver.cpp'),*ecc_dependencies,'-o',str(binary)])
    run('test-'+label,['python3',str(tests/'ecc_reference_test.py'),str(binary)])
for name,extra in [('identity',[str(shim/'hp_zt_identity.cpp'),*core]),('projection',[]),('lifecycle',[]),('events',[str(source/'src/Events.cpp'),*core])]:
    binary=out/(name+'-test')
    run('build-'+name,[*base,*sanitize,str(tests/(name+'_test.cpp')),*extra,'-o',str(binary)])
    run('test-'+name,[str(binary)])
print('Offline only: 6 production TUs compiled; full ASan/UBSan (no ECC exclusion), four ECC public bigint/vector configurations, identity ABI, real projection helper, worker/frame helper and actual Events TU (unused NodeService boundary stub) tests passed. No full library link, node start, network, identity file or device proof.')
