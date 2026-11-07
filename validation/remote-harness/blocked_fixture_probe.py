#!/usr/bin/env python3
"""Optional local proof with an existing herdr binary; no SSH, SDK or network.

Copies the explicit SHA256-checked binary into a short-lived private directory,
disables both background update checks, and uses only its newly owned Unix socket.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from blocked_fixture import BlockedTargets, BlockedFixtureFailure, rpc, snapshot

HERE=Path(__file__).resolve().parent


def wait(check,code):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if check():return
        time.sleep(0.05)
    raise BlockedFixtureFailure(code)


def probe(binary,expected_hash):
    data=Path(binary).read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected_hash:
        raise BlockedFixtureFailure('blocked_probe_binary_hash_mismatch')
    with tempfile.TemporaryDirectory(prefix='hpb-',dir=str(Path('/tmp').resolve())) as name:
        root=Path(name)
        root.chmod(0o700)
        env={'PATH':'/usr/bin:/bin','HOME':str(root/'home'),'SHELL':'/bin/sh','TERM':'xterm-256color',
             'LANG':'C','LC_ALL':'C','TMPDIR':str(root/'tmp'),
             'XDG_CONFIG_HOME':str(root/'config'),'XDG_STATE_HOME':str(root/'state'),
             'XDG_DATA_HOME':str(root/'data'),'XDG_CACHE_HOME':str(root/'cache'),
             'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull}
        for key in ('HOME','TMPDIR','XDG_CONFIG_HOME','XDG_STATE_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
            Path(env[key]).mkdir(mode=0o700,parents=True)
        config_root=root/'config/herdr'
        config_root.mkdir()
        (config_root/'config.toml').write_text('[update]\nversion_check = false\nmanifest_check = false\n')
        executable=root/'herdr'
        executable.write_bytes(data)
        executable.chmod(0o700)
        for filename in ('capture_input.py','blocked_fixture.py'):
            shutil.copy2(HERE/filename,root/filename)
        shutil.copy2(HERE.parent/'shared/fixture.json',root/'terminal-fixture.json')
        def command(argv):
            result=subprocess.run(list(map(str,argv)),env=env,cwd=root,capture_output=True,timeout=20)
            if result.returncode or len(result.stdout)>1_048_576 or len(result.stderr)>1_048_576:
                raise BlockedFixtureFailure('blocked_probe_command_failed')
            return result.stdout
        if command([executable,'--version']).strip()!=b'herdr 0.9.5':
            raise BlockedFixtureFailure('blocked_probe_version_mismatch')
        controller=None
        process=None
        report={'schemaVersion':1,'sourceContractCommit':'2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01',
                'binarySha256':expected_hash,'sourceCommitVerifiedForBinary':False,
                'backgroundUpdateChecksDisabled':True,'hostObserveLeaseRequests':0,
                'hostResizeRequests':0,'hostInputRequests':0,'userAuthorizationFilesTouched':False}
        with (root/'server.log').open('wb') as log:
            try:
                process=subprocess.Popen([str(executable),'--session','pocket-probe','server'],
                    env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                path=config_root/'sessions/pocket-probe/herdr.sock'
                def ready():
                    if process.poll() is not None:
                        raise BlockedFixtureFailure('blocked_probe_server_exited')
                    return path.exists()
                wait(ready,'blocked_probe_socket_missing')
                created=json.loads(command([executable,'--session','pocket-probe','workspace','create',
                                             '--cwd',root,'--label','mobile-readonly']))
                pane=created['result']['root_pane']['pane_id']
                config={'socketPath':str(path),'session':'pocket-probe','paneId':pane,'herdrPath':str(executable)}
                command([executable,'--session','pocket-probe','pane','run',pane,
                         shlex.join([sys.executable,str(root/'capture_input.py')])])
                wait(lambda:(root/'capture-ready').exists(),'blocked_probe_primary_not_ready')
                controller=BlockedTargets(root,config,command)
                targets=controller.prepare()
                rows=snapshot(path)
                report['blockedTargets']=[{**target,'label':next(row['label'] for row in rows
                    if row['pane_id']==target['paneId']),'state':next(row['agent_status'] for row in rows
                    if row['pane_id']==target['paneId'])} for target in targets]
                sentinel=[]
                for sample,target in zip(('A','B'),targets):
                    result=rpc(path,'pane.read',{'pane_id':target['paneId'],'source':'visible','format':'text','strip_ansi':True})
                    sentinel.append(('POCKET-BLOCKED-'+sample) in json.dumps(result))
                if sentinel!=[True,True]:
                    raise BlockedFixtureFailure('blocked_probe_sentinel_missing')
                report['distinguishableRealPaneOutput']=True
                report['waitingProcesses']=controller.stop()
                (root/'stop-capture').write_bytes(b'stop\n')
                wait(lambda:not (root/'capture-running').exists(),'blocked_probe_primary_stop_timeout')
                size=json.loads((root/'pty-size.json').read_text())
                if ((root/'received.bin').read_bytes() or size['state']!=2 or size['changes']!=0 or
                        size['initialRows']!=size['rows'] or size['initialColumns']!=size['columns']):
                    raise BlockedFixtureFailure('blocked_probe_primary_changed')
                report['primaryUntouched']=True
                report['primaryPty']={key:size[key] for key in ('initialRows','initialColumns','rows','columns','changes')}
            finally:
                if controller and not controller.stopped:
                    try:controller.stop()
                    except (OSError,ValueError):pass
                (root/'stop-capture').write_bytes(b'stop\n')
                if process and process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL)
                        process.wait(timeout=5)
                report['ownedServerStopped']=process is not None and process.poll() is not None
        report['ownedTemporaryDirectoryRemoved']=True
    if root.exists():
        raise BlockedFixtureFailure('blocked_probe_cleanup_unconfirmed')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--binary-sha256',required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(probe(args.binary,args.binary_sha256),sort_keys=True))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):
        print(json.dumps({'status':'failed','errorCode':'blocked_probe_failed'}))
        raise SystemExit(1)
