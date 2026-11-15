#!/usr/bin/env python3
"""Opt-in API35 transport preflight: three owned echo services, no App or SSH."""
import argparse
import json
import os
from pathlib import Path
import pwd
import select
import shutil
import subprocess
import sys
import tempfile

from android_dual_overlay_relay import AndroidDualOverlayRelay, ROLES, _stop_process
from android_dual_overlay_reverse import OwnedReverseMappings, ReverseError, _adb, assert_owned_avd

ECHO = '''import json,os,socket,threading
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(16)
print(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}),flush=True)
def serve(c):
 with c:
  data=c.recv(256)
  if data:c.sendall(data)
while True:
 c,_=s.accept();threading.Thread(target=serve,args=(c,),daemon=True).start()
'''


def run(output):
    assert_owned_avd()
    run_id,attempt=os.environ.get('GITHUB_RUN_ID',''),os.environ.get('GITHUB_RUN_ATTEMPT','')
    if not run_id.isdigit() or not attempt.isdigit(): raise ReverseError('owned_namespace_required')
    namespace=f'hp-dual-{run_id}-{attempt}'
    base=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    output=Path(output).resolve()
    if output==base or not output.is_relative_to(base): raise ReverseError('owned_output_required')
    output.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='hp-avd-relay-',dir=base));root.chmod(0o700)
    peers=[]; relay=None; mappings=None
    result={'schemaVersion':1,'status':'failed','scope':'API35 x86_64 owned AVD shell and three synthetic TCP echoes; no App, SSH or TLS',
            'deviceEcho':{role:False for role in ROLES},'reverseRemoved':False,'relayClosed':False,
            'peerProcessesStopped':False,'privateRemoved':False}
    try:
        # The caller's workflow owns creation/removal of this exact namespace.
        links=subprocess.run(['sudo','-n','ip','netns','exec',namespace,'ip','-j','link','show'],
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,check=True)
        if [item.get('ifname') for item in json.loads(links.stdout)] != ['lo']:
            raise ReverseError('namespace_scope_invalid')
        for role in ROLES:
            peer=subprocess.Popen(['sudo','-n','ip','netns','exec',namespace,'runuser','-u',pwd.getpwuid(os.getuid()).pw_name,'--',
                                   sys.executable,'-u','-c',ECHO],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,start_new_session=True)
            peers.append(peer)
        records=[]
        for peer in peers:
            if not select.select([peer.stdout],[],[],15)[0]: raise ReverseError('fixture_not_ready')
            data=json.loads(peer.stdout.readline())
            if set(data)!={'pid','port'} or type(data['pid']) is not int or type(data['port']) is not int:
                raise ReverseError('fixture_invalid')
            records.append(data)
        config={'namespace':namespace, **{role:records[i]['port'] for i,role in enumerate(ROLES)},
                'ownerPids':{role:records[i]['pid'] for i,role in enumerate(ROLES)},'sshPorts':[1,2]}
        manifest=root/'manifest.json';manifest.write_text(json.dumps(config));manifest.chmod(0o600)
        relay=AndroidDualOverlayRelay(manifest)
        with relay:
            mappings=OwnedReverseMappings(relay)
            with mappings:
                for role in ROLES:
                    marker=('hp-'+role+'-ok').encode('ascii')
                    # A fixed shell program emits only this role's synthetic marker.
                    script=b"printf '"+marker+b"' | /system/bin/toybox nc -w 5 127.0.0.1 "+str(config[role]).encode()+b"\n"
                    reply=_adb('shell','-T','sh',input_data=script,timeout=15)
                    result['deviceEcho'][role]=reply==marker
                    if not result['deviceEcho'][role]: raise ReverseError('device_echo_mismatch')
            result['reverseRemoved']=mappings.cleanup_confirmed
        result['relayClosed']=not any(t.is_alive() for t in relay._threads) and not relay._workers
        if not result['relayClosed']: raise ReverseError('relay_cleanup_unconfirmed')
        result['status']='passed'
    except (ReverseError,OSError,ValueError,subprocess.SubprocessError) as error:
        result['errorCode']=str(error) if isinstance(error,ReverseError) and str(error) in {
            'owned_avd_required','adb_operation_failed','adb_output_invalid','owned_namespace_required','owned_output_required',
            'fixture_not_ready','fixture_invalid','namespace_scope_invalid','reverse_collision','reverse_install_unconfirmed','reverse_cleanup_unconfirmed',
            'ssh_reverse_forbidden','device_echo_mismatch','relay_cleanup_unconfirmed'} else 'transport_preflight_failed'
    finally:
        if mappings is not None: result['reverseRemoved']=mappings.cleanup_confirmed
        if relay is not None:
            result['relayClosed']=not any(t.is_alive() for t in relay._threads) and not relay._workers
        stopped=True
        for peer in peers:
            try: _stop_process(peer)
            except (OSError,subprocess.SubprocessError): stopped=False
            if peer.stdout: peer.stdout.close()
        result['peerProcessesStopped']=stopped and all(peer.poll() is not None for peer in peers)
        try: shutil.rmtree(root)
        except OSError: pass
        result['privateRemoved']=not root.exists()
        if not all((result['reverseRemoved'],result['relayClosed'],result['peerProcessesStopped'],result['privateRemoved'])):
            result['status']='failed'
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result['status']=='passed'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();sys.exit(0 if run(args.output) else 1)
