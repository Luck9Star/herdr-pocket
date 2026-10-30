#!/usr/bin/env python3
"""Isolated real SSH/herdr test. Never touches the runner user's authorization files."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import signal
import socket
import subprocess
import time
import urllib.request

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('SSH integration is CI-only; refusing local host/authorization changes')
REPO=Path(__file__).resolve().parents[2]
OUT=REPO/'validation/ssh/artifacts'; OUT.mkdir(parents=True,exist_ok=True)
ROOT=Path('/tmp')/('hp-ssh-'+os.environ['GITHUB_RUN_ID'])
ROOT.mkdir(mode=0o700)
HERDR_SHA='14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d'
URL='https://github.com/herdrdev/herdr/releases/download/v0.9.5/herdr-linux-x86_64'
processes=[]
report={'schemaVersion':1,'sourceSHA':os.environ['GITHUB_SHA'],'runUrl':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],'platform':'Ubuntu 24.04 x86_64 loopback fixture','herdr':{'version':'0.9.5','sourceCommit':'2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01','asset':URL,'sha256':HERDR_SHA},'status':'failed','scope':'Separate Linux integration harness; GUI binding, overlay routing, mobile and real-user credentials are unverified.'}
env={k:v for k,v in os.environ.items() if not k.startswith('HERDR_') and k not in ['SSH_AUTH_SOCK','SSH_AGENT_PID','BASH_ENV']}
env.update(XDG_CONFIG_HOME=str(ROOT/'config'),XDG_STATE_HOME=str(ROOT/'state'),XDG_DATA_HOME=str(ROOT/'data'),XDG_CACHE_HOME=str(ROOT/'cache'),HP_FIXTURE_ROOT=str(ROOT),SHELL='/bin/sh')

def run(args,log=None,timeout=60):
    completed=subprocess.run([str(x) for x in args],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
    if log: (OUT/log).write_text(completed.stdout)
    if completed.returncode: raise RuntimeError(f'{Path(str(args[0])).name} exit {completed.returncode}; see {log}')
    return completed.stdout

def spawn(args,log):
    f=(OUT/log).open('w')
    p=subprocess.Popen([str(x) for x in args],env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    processes.append((p,f));return p

try:
    herdr=ROOT/'herdr'
    with urllib.request.urlopen(URL,timeout=60) as response: data=response.read(100*1024*1024+1)
    if len(data)>100*1024*1024 or hashlib.sha256(data).hexdigest()!=HERDR_SHA: raise RuntimeError('herdr release asset hash/size mismatch')
    herdr.write_bytes(data);herdr.chmod(0o700)
    run([herdr,'--version'],'herdr-version.txt')
    for name in ['host','wrong','client']:
        run(['ssh-keygen','-q','-t','ed25519','-N','','-C','ephemeral-herdr-pocket-fixture','-f',ROOT/name])
    # Only this newly created file is offered to the temporary sshd. Never ~/.ssh/authorized_keys.
    (ROOT/'authorized_keys').write_bytes((ROOT/'client.pub').read_bytes())
    (ROOT/'authorized_keys').chmod(0o600)
    with socket.socket() as reserve: reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    user=pwd.getpwuid(os.getuid()).pw_name
    config=f'''Port {port}
ListenAddress 127.0.0.1
HostKey {ROOT}/host
PidFile {ROOT}/sshd.pid
AuthorizedKeysFile {ROOT}/authorized_keys
StrictModes no
UsePAM no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
PermitRootLogin no
AllowUsers {user}
PermitTTY no
AllowAgentForwarding no
AllowTcpForwarding no
AllowStreamLocalForwarding yes
X11Forwarding no
PrintMotd no
LogLevel ERROR
'''
    (ROOT/'sshd_config').write_text(config)
    run(['sudo','mkdir','-p','/run/sshd'])
    run(['sudo','/usr/sbin/sshd','-t','-f',ROOT/'sshd_config'],'sshd-config-check.txt')
    spawn(['sudo','/usr/sbin/sshd','-D','-e','-f',ROOT/'sshd_config'],'sshd.log')
    server=spawn([herdr,'--session','pocket-probe','server'],'herdr-server.log')
    sock=ROOT/'config/herdr/sessions/pocket-probe/herdr.sock'
    deadline=time.monotonic()+20
    while not sock.exists():
        if server.poll() is not None: raise RuntimeError('isolated herdr server exited before socket creation')
        if time.monotonic()>deadline: raise RuntimeError('isolated named-session socket timeout')
        time.sleep(.1)
    created=json.loads(run([herdr,'--session','pocket-probe','workspace','create','--cwd',ROOT,'--label','ssh-fixture'],'workspace-create.json'))
    pane=created['result']['root_pane']['pane_id']
    if not isinstance(pane,str) or len(pane)>128: raise RuntimeError('invalid fixture pane id')
    run([herdr,'api','schema','--json'],'herdr-schema.json')
    capture=ROOT/'capture-input.py'
    shutil.copy2(REPO/'validation/ssh/capture_input.py',capture)
    run([herdr,'--session','pocket-probe','pane','run',pane,shlex.join(['python3',str(capture)])],'capture-start.json')
    deadline=time.monotonic()+10
    while not (ROOT/'capture-ready').exists():
        if time.monotonic()>deadline:raise RuntimeError('raw PTY receiver did not start')
        time.sleep(.05)

    prefix=['/usr/bin/env',f'XDG_CONFIG_HOME={ROOT}/config',f'XDG_STATE_HOME={ROOT}/state',f'XDG_DATA_HOME={ROOT}/data',f'XDG_CACHE_HOME={ROOT}/cache',str(herdr)]
    fixture={'port':port,'user':user,'hostPublicKey':str(ROOT/'host.pub'),'wrongPublicKey':str(ROOT/'wrong.pub'),'clientPrivateKey':str(ROOT/'client'),'socket':str(sock),'pane':pane,'receivedBytes':str(ROOT/'received.bin'),
             'observeCommand':shlex.join(prefix+['--session','pocket-probe','terminal','session','observe',pane,'--cols','80','--rows','24']),
             'missingCommand':shlex.join(prefix+['--session','pocket-missing','terminal','session','observe',pane,'--cols','80','--rows','24'])}
    (ROOT/'fixture.json').write_text(json.dumps(fixture));(ROOT/'fixture.json').chmod(0o600)
    run(['cargo','run','--locked','--manifest-path',REPO/'validation/ssh/Cargo.toml'],'rust-probe.log',timeout=900)
    report['status']='passed'
except Exception as exc:
    report['error']=str(exc)
finally:
    # Exact PIDs/process groups from this fixture only; no system/user service stop commands.
    for p,f in reversed(processes):
        if p.poll() is None:
            subprocess.run(['sudo','kill','-TERM','--','-'+str(p.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:subprocess.run(['sudo','kill','-KILL','--','-'+str(p.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        f.close()
    if (ROOT/'received.bin').exists():
        received=(ROOT/'received.bin').read_bytes()
        (OUT/'received-bytes.json').write_text(json.dumps({'hex':received.hex(),'bytes':len(received),'target':'pocket-probe test pane only'}))
    if (ROOT/'ssh-results.json').exists():shutil.copy2(ROOT/'ssh-results.json',OUT/'ssh-results.json')
    # Keys and fixture config are never copied to logs/artifacts. Remove only the known ephemeral secrets.
    for name in ['client','client.pub','host','host.pub','wrong','wrong.pub','authorized_keys','fixture.json']:
        (ROOT/name).unlink(missing_ok=True)
    shutil.copy2(REPO/'validation/ssh/Cargo.lock',OUT/'Cargo.lock')
    (OUT/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUT/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='SHA256SUMS'))
print(json.dumps(report))
raise SystemExit(0 if report['status']=='passed' else 1)
