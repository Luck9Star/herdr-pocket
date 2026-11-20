import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile

from android_dual_overlay_hosts import live_ssh_ports, observed_peer_close
from paired_dual_demo import prepared_pairing_hosts
from paired_gui import wait_for


def start_config(target):
    key = target.root / 'probe-client'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key],
                   capture_output=True, check=True)
    public = key.with_suffix('.pub')
    (target.root / 'authorized_keys').write_bytes(public.read_bytes())
    config = {**target.config, 'schemaVersion':1, 'privateKeyPem':key.read_text(),
              'reviewConfirmed':True}
    path = target.root / 'probe-config.json'
    path.touch(mode=0o600)
    path.write_text(json.dumps(config))
    fingerprint = subprocess.check_output(['/usr/bin/ssh-keygen','-lf',public,'-E','sha256'],
                                          text=True).split()[1]
    return path, fingerprint


def audit(target, fingerprint):
    source = (target.root / 'sshd.log').read_text()
    prefix = r'Accepted publickey for ' + re.escape(target.config['username'])
    expression = prefix + r' from 127\.0\.0\.1 port ([0-9]+) ssh2: ED25519 (' + re.escape(fingerprint) + r')(?:\s|$)'
    hits = list(re.finditer(expression, source))
    if len(hits) != 1 or source.count('Accepted publickey for ') != 1:
        raise RuntimeError('not_one_approved_ssh_session')
    hit = hits[0]
    close = observed_peer_close(source[hit.end():], hit[1])
    return {'approvedSessions':1, 'active':int(hit[1]) in live_ssh_ports(target.config['port']),
            'peerClose':close, 'capturedBytes':(target.root / 'received.bin').stat().st_size}


def run(executable):
    output = Path(__file__).with_name('result.json')
    result = {'scope':'macOS local TCP transport, two independently running OpenSSH/herdr fixtures',
              'sourceSHA':os.environ['PROBE_SOURCE'], 'checkpoints':{}}
    with tempfile.TemporaryDirectory(prefix='hc-', dir='/tmp') as work:
        root = Path(work)
        with prepared_pairing_hosts(Path(shutil.which('herdr')), root, input_ack=True) as (targets, processes, _):
            configs = {role:start_config(target) for role,target in targets.items()}
            process = subprocess.Popen([executable,configs['et'][0],configs['ts'][0]], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                selector = selectors.DefaultSelector()
                selector.register(process.stdout, selectors.EVENT_READ)
                for step, live in [('both_open',(True,True)),('a_closed_b_advanced',(False,True)),('both_closed',(False,False))]:
                    if not selector.select(25) or process.stdout.readline(120).strip() != step.encode():
                        raise RuntimeError('transport_checkpoint_missing')
                    def probe():
                        sample = {side:audit(targets[role],configs[role][1])
                                  for role,side in [('et','a'),('ts','b')]}
                        complete = all(row['active'] is active and row['capturedBytes']==0 and
                                       row['peerClose'] in (('unconfirmed',) if active else ('peer_eof','client_disconnect'))
                                       for row,active in zip(sample.values(),live))
                        return sample if complete else None
                    result['checkpoints'][step] = wait_for(probe,'independent_peer_evidence_missing',timeout=5)
                    process.stdin.write(b'next\n')
                    process.stdin.flush()
                if process.wait(timeout=5) != 0:
                    raise RuntimeError('transport_failed')
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                for pipe in (process.stdin,process.stdout,process.stderr):
                    pipe.close()
        result['fixtureProcessesExited'] = all(proc.poll() is not None for proc in processes)
    result['temporaryHostMaterialRemoved'] = not root.exists()
    result['status'] = 'passed'
    output.write_text(json.dumps(result,indent=2)+'\n')
    print(output)


run(sys.argv[1])
