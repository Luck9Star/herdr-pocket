#!/usr/bin/env python3
"""Owned API35 instrumented Go TLS probe; private CA, disposable package only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import select
import shutil
import subprocess
import sys
import tempfile

from android_dual_overlay_relay import AndroidDualOverlayRelay, ROLES, _stop_process
from android_dual_overlay_reverse import OwnedReverseMappings, ReverseError, _adb, _text, assert_owned_avd
from android_dual_overlay_transport import ECHO

PACKAGE='org.herdr.tlsprobe'
RUNNER=PACKAGE+'/.ProbeInstrumentation'
TLS_SERVER='''import json,os,socket,ssl,sys,threading
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(sys.argv[1],sys.argv[2])
s=socket.socket();s.bind(('127.0.0.1',0));s.listen(16)
print(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}),flush=True)
def serve(raw):
 try:
  with context.wrap_socket(raw,server_side=True) as conn:
   request=conn.recv(4096)
   if request.startswith(b'GET /key '):
    body=b'HP-GO-TLS-OK';conn.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length: 12\\r\\nConnection: close\\r\\n\\r\\n'+body)
 except (OSError,ssl.SSLError):raw.close()
while True:
 client,_=s.accept();threading.Thread(target=serve,args=(client,),daemon=True).start()
'''


def package_present():
    return 'package:'+PACKAGE in _text('shell','pm','list','packages',PACKAGE).splitlines()


def instrument(port):
    _adb('shell','am','force-stop',PACKAGE)
    output=_adb('shell','am','instrument','-w','-e','port',str(port),RUNNER,timeout=60)
    matches=re.findall(rb'HP_TLS_RESULT pid=([0-9]+) code=([0-9]+) wrong=([0-9]+) prep=([0-9]+) wrap=([01]) executable=([01]) javaEnv=([01])',output)
    if len(matches)!=1: raise ReverseError('instrument_result_invalid')
    return tuple(int(value) for value in matches[0])


def run(apk,output):
    assert_owned_avd()
    run_id,attempt=os.environ.get('GITHUB_RUN_ID',''),os.environ.get('GITHUB_RUN_ATTEMPT','')
    if not run_id.isdigit() or not attempt.isdigit(): raise ReverseError('owned_namespace_required')
    namespace=f'hp-dual-{run_id}-{attempt}'
    base=Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    apk=Path(apk).resolve(strict=True);output=Path(output).resolve()
    if apk==base or output==base or not apk.is_relative_to(base) or not output.is_relative_to(base) or not apk.is_file():
        raise ReverseError('owned_path_required')
    output.mkdir(parents=True,exist_ok=True)
    if package_present(): raise ReverseError('probe_package_already_present')
    root=Path(tempfile.mkdtemp(prefix='hp-private-ca-',dir=base));root.chmod(0o700)
    result={'schemaVersion':1,'status':'failed','scope':'API35 x86_64 disposable debug instrumentation and standard Go TLS with test-only private-path Go environment initialization; synthetic CA; no product App or system trust changes',
            'caAbsentRejected':False,'privateCaAccepted':False,'wrongHostnameRejected':False,'caRemovedRejected':False,
            'freshProcesses':False,'reverseRemoved':False,'relayClosed':False,'packageRemoved':False,
            'peerProcessesStopped':False,'privateRemoved':False}
    installed=False;peers=[];relay=None;mappings=None;phase='certificate'
    try:
        def command(args):
            subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=True)
        ca_key,ca_cert,leaf_key,leaf_csr,leaf_cert=(root/name for name in ('ca.key','ca.pem','leaf.key','leaf.csr','leaf.pem'))
        ext=root/'leaf.ext';ext.write_text('subjectAltName=IP:127.0.0.1\nextendedKeyUsage=serverAuth\n')
        command(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Disposable TLS CA','-keyout',str(ca_key),'-out',str(ca_cert)])
        command(['openssl','req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=127.0.0.1','-keyout',str(leaf_key),'-out',str(leaf_csr)])
        command(['openssl','x509','-req','-days','1','-in',str(leaf_csr),'-CA',str(ca_cert),'-CAkey',str(ca_key),'-CAcreateserial','-extfile',str(ext),'-out',str(leaf_cert)])
        phase='namespace_check'
        links=subprocess.run(['sudo','-n','ip','netns','exec',namespace,'ip','-j','link','show'],stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL,timeout=10,check=True)
        if [item.get('ifname') for item in json.loads(links.stdout)] != ['lo']: raise ReverseError('namespace_scope_invalid')
        phase='fixture_setup'
        for role in ROLES:
            args=[sys.executable,'-u','-c',TLS_SERVER,str(leaf_cert),str(leaf_key)] if role=='control' else [sys.executable,'-u','-c',ECHO]
            peer=subprocess.Popen(['sudo','-n','ip','netns','exec',namespace,'runuser','-u',pwd.getpwuid(os.getuid()).pw_name,'--',*args],
                                  stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
            peers.append(peer)
        records=[]
        for peer in peers:
            if not select.select([peer.stdout],[],[],15)[0]: raise ReverseError('fixture_not_ready')
            data=json.loads(peer.stdout.readline())
            if set(data)!={'pid','port'} or type(data['pid']) is not int or type(data['port']) is not int: raise ReverseError('fixture_invalid')
            records.append(data)
        config={'namespace':namespace,**{role:records[i]['port'] for i,role in enumerate(ROLES)},
                'ownerPids':{role:records[i]['pid'] for i,role in enumerate(ROLES)},'sshPorts':[1,2]}
        manifest=root/'manifest.json';manifest.write_text(json.dumps(config));manifest.chmod(0o600)
        phase='install'
        _adb('install','-t',str(apk),timeout=90);installed=True
        _adb('shell','run-as',PACKAGE,'mkdir','-p','files/empty-ca')
        _adb('shell','run-as',PACKAGE,'touch','files/enable-private-ca-probe')
        relay=AndroidDualOverlayRelay(manifest)
        with relay:
            mappings=OwnedReverseMappings(relay)
            with mappings:
                phase='without_ca'
                pid1,code1,_,prep,wrap,executable,java_env=instrument(config['control'])
                result['goEnvironmentPreparation']=prep if prep in (1,2,8,9,99) else -1
                result['wrapExtracted']=bool(wrap)
                result['wrapExecutable']=bool(executable)
                result['javaEnvironmentMatches']=bool(java_env)
                result['withoutCaCode']=code1 if code1 in (0,1,2,8,9,10,99) else -1
                result['caAbsentRejected']=code1==1
                if not result['caAbsentRejected']: raise ReverseError('ca_absent_not_rejected')
                phase='with_private_ca'
                _adb('shell','-T','run-as',PACKAGE,'tee','files/ca.pem',input_data=ca_cert.read_bytes())
                pid2,code2,wrong,_,_,_,_=instrument(config['control'])
                result['withCaCode']=code2 if code2 in (0,1,2,8,9,10,99) else -1
                result['wrongHostCode']=wrong if wrong in (0,1,2,8,9,10,99) else -1
                result['privateCaAccepted']=code2==0
                result['wrongHostnameRejected']=wrong==2
                if not result['privateCaAccepted'] or not result['wrongHostnameRejected']: raise ReverseError('private_ca_verification_failed')
                phase='after_ca_removal'
                _adb('shell','run-as',PACKAGE,'rm','-f','files/ca.pem')
                pid3,code3,_,_,_,_,_=instrument(config['control'])
                result['afterRemovalCode']=code3 if code3 in (0,1,2,8,9,10,99) else -1
                result['caRemovedRejected']=code3==1
                result['freshProcesses']=len({pid1,pid2,pid3})==3
                if not result['caRemovedRejected'] or not result['freshProcesses']: raise ReverseError('ca_removal_or_freshness_failed')
            result['reverseRemoved']=mappings.cleanup_confirmed
        result['relayClosed']=not any(thread.is_alive() for thread in relay._threads) and not relay._workers
        result['status']='passed'
    except (ReverseError,OSError,ValueError,subprocess.SubprocessError) as error:
        result['failurePhase']=phase
        result['errorCode']=str(error) if isinstance(error,ReverseError) and re.fullmatch(r'[a-z_]{1,60}',str(error)) else 'private_ca_probe_failed'
        if getattr(error,'cleanup_code',None):result['cleanupErrorCode']='reverse_cleanup_unconfirmed'
    finally:
        if mappings is not None:result['reverseRemoved']=mappings.cleanup_confirmed
        if relay is not None:result['relayClosed']=not any(t.is_alive() for t in relay._threads) and not relay._workers
        try:
            if installed:_adb('uninstall',PACKAGE)
            result['packageRemoved']=not package_present()
        except (ReverseError,OSError,subprocess.SubprocessError):pass
        stopped=True
        for peer in peers:
            try:_stop_process(peer)
            except (OSError,subprocess.SubprocessError):stopped=False
            if peer.stdout:peer.stdout.close()
        result['peerProcessesStopped']=stopped and all(peer.poll() is not None for peer in peers)
        try:shutil.rmtree(root)
        except OSError:pass
        result['privateRemoved']=not root.exists()
        if not all(result[key] for key in ('caAbsentRejected','privateCaAccepted','wrongHostnameRejected','caRemovedRejected',
                                           'freshProcesses','reverseRemoved','relayClosed','packageRemoved','peerProcessesStopped','privateRemoved')):
            result['status']='failed'
        result['apkSha256']=hashlib.sha256(apk.read_bytes()).hexdigest()
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result['status']=='passed'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apk',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();sys.exit(0 if run(args.apk,args.output) else 1)
