#!/usr/bin/env python3
"""Compile pinned patched TUs and run native-only offline tests. No node start.
Requires an already prepared + candidate-patched source root. Never downloads.
"""
from pathlib import Path
import argparse, subprocess, os
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
    with (out/(label+'.log')).open('w') as log:
        subprocess.run(cmd,stdout=log,stderr=log,check=True,env=env)
    print(label+': passed',flush=True)
# Compile actual modified production units, not substitute class definitions.
for name in ['Controls','Events','NodeService','VirtualTap']:
    run('tu-'+name,[*base,'-c',str(source/'src'/(name+'.cpp')),'-o',str(out/(name+'.o'))])
for name in ['hp_zt_identity','hp_zt_lifecycle']:
    run('tu-'+name,[*base,'-c',str(shim/(name+'.cpp')),'-o',str(out/(name+'.o'))])
core=[]
for name in ['Identity','ECC','Salsa20','SHA512','Utils']:
    obj=out/(name+'-san.o');flags=sanitize.copy()
    if name=='ECC':
        # The fixed upstream Curve25519 reference arithmetic uses signed shifts.
        # Keep ASan and other UBSan checks; do not pretend full upstream UBSan is green.
        flags+=['-fno-sanitize=shift-base']
    run('core-'+name,[*base,*flags,'-c',str(source/'ext/ZeroTierOne/node'/(name+'.cpp')),'-o',str(obj)])
    core.append(str(obj))
for name,extra in [('identity',[str(shim/'hp_zt_identity.cpp'),*core]),('projection',[]),('lifecycle',[]),('events',[str(source/'src/Events.cpp'),*core])]:
    binary=out/(name+'-test')
    run('build-'+name,[*base,*sanitize,str(tests/(name+'_test.cpp')),*extra,'-o',str(binary)])
    run('test-'+name,[str(binary)])
print('Offline only: 6 production TUs compiled; identity ABI, real projection helper, worker/frame helper and actual Events TU (unused NodeService boundary stub) tests passed. No full library link, node start, network, identity file or device proof. ECC TU excludes upstream shift-base only.')
