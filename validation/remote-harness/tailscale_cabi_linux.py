#!/usr/bin/env python3
"""Isolated Linux C ABI test against the private, loopback-only tsnet fixture."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class Failure(ValueError):
    pass


class WorkerEnded(Failure):
    def __init__(self, evidence):
        super().__init__('authorization_url_not_received')
        self.evidence = evidence


def partial_checked(value):
    result = {}
    states = value.get('states')
    allowed = {'NeedsLogin', 'Running', 'Starting', 'Stopped', 'NoState', 'NeedsMachineAuth'}
    if isinstance(states, list):
        result['states'] = [state for state in states if isinstance(state, str) and state in allowed][:8]
    for key in ('preLoginNoUrl', 'authUrlPresent', 'running', 'payloadEqual'):
        if type(value.get(key)) is bool: result[key] = value[key]
    for key in ('startCode', 'preLoginDialCode', 'beginLoginCode', 'dialCode', 'streamCloseCode',
                'streamReleaseCode', 'nodeCloseCode', 'nodeReleaseCode', 'outstandingReadBuffers'):
        if type(value.get(key)) is int and 0 <= value[key] <= 1000: result[key] = value[key]
    return result


def ready_checked(event, root):
    if not isinstance(event, dict) or event.get('event') != 'ready' or event.get('peerPort') != 2222:
        raise Failure('fixture_ready_invalid')
    try:
        url = urllib.parse.urlsplit(event['controlUrl'])
        ip = ipaddress.ip_address(event['peerIp'])
        ca = Path(event['caFile']).resolve(strict=True)
        if (url.scheme != 'https' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password or
                url.path not in ('', '/') or url.query or url.fragment or
                ip not in ipaddress.ip_network('100.64.0.0/10') or
                not ca.is_file() or not ca.is_relative_to(root.resolve())):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OSError):
        raise Failure('fixture_ready_invalid') from None
    return event['controlUrl'], str(ca), str(ip), 2222


def auth_checked(url, control):
    try:
        actual, expected = urllib.parse.urlsplit(url), urllib.parse.urlsplit(control)
        if actual.scheme != 'https' or actual.netloc != expected.netloc or not actual.path.startswith('/') or actual.fragment:
            raise ValueError()
    except (ValueError, TypeError):
        raise Failure('authorization_url_invalid') from None
    return url


def report_checked(value):
    if not isinstance(value, dict) or value.get('event') != 'cabi_result':
        raise Failure('cabi_result_invalid')
    required = {'startCode':0, 'preLoginNoUrl':True, 'preLoginDialCode':7, 'beginLoginCode':0,
                'authUrlPresent':True, 'running':True, 'dialCode':0, 'payloadEqual':True,
                'streamCloseCode':0, 'streamReleaseCode':0, 'nodeCloseCode':0,
                'nodeReleaseCode':0, 'outstandingReadBuffers':0}
    if any(type(value.get(k)) is not type(v) or value[k] != v for k,v in required.items()):
        raise Failure('cabi_evidence_incomplete')
    return required


def diagnostics_checked(value):
    counts = ('keyRequests','noiseRequests','registerRequests','mapRequests','tlsHandshakeErrors','authCompletions')
    if (not isinstance(value,dict) or value.get('event') != 'diagnostics' or
            any(type(value.get(key)) is not int or not 0 <= value[key] <= 1000000 for key in counts) or
            type(value.get('secondClientRegistered')) is not bool):
        raise Failure('control_diagnostics_invalid')
    return {**{key:value[key] for key in counts}, 'secondClientRegistered':value['secondClientRegistered']}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def control_reached(url, ca):
    request = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca))).open(request, timeout=5) as response:
            return 100 <= response.status <= 599
    except urllib.error.HTTPError as response:
        return 100 <= response.code <= 599
    except (OSError, urllib.error.URLError):
        return False


def read_event(events, proc, name, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: line = events.get(timeout=.1)
        except queue.Empty:
            if proc.poll() is not None: break
            continue
        try: value = json.loads(line)
        except (ValueError, UnicodeError): continue
        if isinstance(value, dict) and value.get('event') == name: return value
        if name == 'auth_requested' and isinstance(value, dict) and value.get('event') == 'cabi_result':
            raise WorkerEnded(partial_checked(value))
    raise Failure(name + '_not_received')


def network_checked(mode, links, addresses, routes4, routes6):
    if mode not in ('loopback', 'dummy') or not all(isinstance(value,list) for value in (links,addresses,routes4,routes6)):
        raise Failure('network_scope_invalid')
    names = {item.get('ifname') for item in links}
    expected = {'lo'} if mode == 'loopback' else {'lo','hp-fixture0'}
    if names != expected or len(links) != len(expected) or routes4 or routes6:
        raise Failure('network_scope_invalid')
    if {item.get('ifname') for item in addresses} != expected or len(addresses) != len(expected):
        raise Failure('network_scope_invalid')
    loop = next(item for item in addresses if item.get('ifname') == 'lo')
    loop_addresses = {(item.get('family'),item.get('local'),item.get('prefixlen')) for item in loop.get('addr_info',[])}
    if ('inet','127.0.0.1',8) not in loop_addresses or not loop_addresses <= {('inet','127.0.0.1',8),('inet6','::1',128)}:
        raise Failure('network_scope_invalid')
    if mode == 'dummy':
        link = next(item for item in links if item.get('ifname') == 'hp-fixture0')
        if link.get('linkinfo',{}).get('info_kind') != 'dummy' or 'UP' not in link.get('flags',[]):
            raise Failure('network_scope_invalid')
        matching = [item for item in addresses if item.get('ifname') == 'hp-fixture0']
        if len(matching) != 1 or [(item.get('family'),item.get('local'),item.get('prefixlen')) for item in matching[0].get('addr_info',[])] != [('inet','192.0.2.1',32)]:
            raise Failure('network_scope_invalid')
    return True


def run(bundle, output, mode):
    if sys.platform != 'linux' or os.geteuid() == 0 or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise Failure('owned_linux_runner_required')
    run_id, attempt = os.environ.get('GITHUB_RUN_ID',''), os.environ.get('GITHUB_RUN_ATTEMPT','')
    if not run_id.isdigit() or not attempt.isdigit(): raise Failure('owned_namespace_required')
    expected = f'/run/netns/hp-ts-cabi-{run_id}-{attempt}'
    if os.stat(expected).st_ino != os.stat('/proc/self/ns/net').st_ino: raise Failure('owned_namespace_required')
    def ip_json(*args):
        reply = subprocess.run(['ip','-j',*args],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10,check=True)
        return json.loads(reply.stdout)
    network_checked(mode,ip_json('-d','link','show'),ip_json('address','show'),
                    ip_json('-4','route','show','table','main'),ip_json('-6','route','show','table','main'))
    owned_root = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    bundle = Path(bundle).resolve(strict=True)
    output = Path(output).resolve()
    if bundle == owned_root or output == owned_root or not bundle.is_relative_to(owned_root) or not output.is_relative_to(owned_root):
        raise Failure('owned_paths_required')
    library, fixture, netmon = bundle/'libhp_tailscale.so', bundle/'ts-fixture', bundle/'netmon-probe'
    if not library.is_file() or not fixture.is_file() or not netmon.is_file(): raise Failure('candidate_missing')
    output = Path(output); output.mkdir(parents=True,exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='hp-cabi-',dir=os.environ['RUNNER_TEMP'])); root.chmod(0o700)
    helper_dir, worker_dir = root/'fixture',root/'worker'
    for item in (helper_dir,worker_dir): item.mkdir(mode=0o700)
    processes=[]; readers=[]; error_files=[]
    helper = None; events = None
    result={'schemaVersion':1,'networkMode':mode,'status':'failed','stage':'start','controlReached':False,
            'authorizationCompleted':False,'fixtureCleanup':False,'processesStopped':False,'privateRemoved':False}
    env={k:v for k,v in os.environ.items() if not k.startswith('HERDR_') and k not in ('SSH_AUTH_SOCK','SSH_AGENT_PID','BASH_ENV')}
    env.update(SHELL='/bin/sh', LD_LIBRARY_PATH=str(bundle))
    result['proxyEnvironment']={name:bool(env.get(name)) for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy')}
    result['sslCertDirInherited']=bool(env.get('SSL_CERT_DIR'))
    def launch(args, child_env):
        error_path=root / ('helper.stderr' if not processes else 'worker.stderr')
        error_file=error_path.open('wb'); error_files.append(error_file)
        proc=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=error_file,env=child_env,start_new_session=True)
        processes.append(proc); events=queue.Queue()
        thread=threading.Thread(target=lambda: [events.put(line) for line in proc.stdout],daemon=True)
        readers.append(thread);thread.start();return proc,events
    try:
        result['stage']='netmon'
        probe=subprocess.run([str(netmon)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env=env,timeout=10,check=True)
        state=json.loads(probe.stdout)
        if not isinstance(state,dict) or set(state) != {'haveV4','haveV6','anyInterfaceUp'} or any(type(v) is not bool for v in state.values()):
            raise Failure('netmon_result_invalid')
        result['netmon']=state
        result['stage']='fixture'
        helper,events=launch([str(fixture),'-test.run=^TestServeFixture$','-test.timeout=180s'],dict(env,HP_TS_FIXTURE_WORK_DIR=str(helper_dir)))
        ready=read_event(events,helper,'ready');control,ca,peer,port=ready_checked(ready,helper_dir)
        result['controlReached']=control_reached(control,ca)
        if not result['controlReached']: raise Failure('control_unreachable')
        def diagnostics():
            helper.stdin.write(b'{"op":"diagnostics"}\n'); helper.stdin.flush()
            return diagnostics_checked(read_event(events,helper,'diagnostics',timeout=5))
        result['controlDiagnostics']={'baseline':diagnostics()}
        request={'library':str(library),'controlUrl':control,'peerIp':peer,'peerPort':port}
        (worker_dir/'request.json').write_text(json.dumps(request)); (worker_dir/'request.json').chmod(0o600)
        result['stage']='authorization_url'
        worker,wevents=launch([sys.executable,str(Path(__file__).with_name('tailscale_cabi_worker.py')),str(worker_dir)],dict(env,SSL_CERT_FILE=ca))
        read_event(wevents,worker,'auth_requested',timeout=50)
        result['controlDiagnostics']['beforeAuthorization']=diagnostics()
        auth_file=worker_dir/'auth-url';auth=auth_checked(auth_file.read_text(),control)
        helper.stdin.write((json.dumps({'op':'complete_auth','url':auth})+'\n').encode());helper.stdin.flush();auth=''
        event=read_event(events,helper,'auth_completed')
        if event.get('ok') is not True: raise Failure('authorization_not_completed')
        result['authorizationCompleted']=True
        result['controlDiagnostics']['afterAuthorization']=diagnostics()
        (worker_dir/'auth-complete').touch(mode=0o600)
        result['stage']='running_and_echo'
        evidence=read_event(wevents,worker,'cabi_result',timeout=50)
        result['cabi']=report_checked(evidence)
        if worker.wait(timeout=15) != 0: raise Failure('cabi_worker_failed')
        result['controlDiagnostics']['afterRun']=diagnostics()
        helper.stdin.write(b'{"op":"stop"}\n');helper.stdin.flush()
        event=read_event(events,helper,'cleanup',timeout=30)
        result['fixtureCleanup']=event.get('peerClosed') is True and event.get('bridgeConnections') == 0
        if not result['fixtureCleanup'] or helper.wait(timeout=15) != 0: raise Failure('fixture_cleanup_failed')
        result['stage']='complete';result['status']='passed'
    except (Failure, OSError, subprocess.SubprocessError, ValueError) as error:
        if isinstance(error, WorkerEnded): result['partialCabi'] = error.evidence
        result['errorCode']=str(error) if isinstance(error,Failure) else 'isolated_runner_failed'
        if helper is not None:
            result['fixtureAliveAtFailure'] = helper.poll() is None
            if helper.poll() is not None: result['fixtureExitCodeAtFailure'] = helper.returncode
        if helper is not None and events is not None and helper.poll() is None and 'controlDiagnostics' in result:
            try:
                result['controlDiagnostics']['failure']=diagnostics()
                result['failureDiagnosticsOutcome']='received'
            except (Failure, OSError, ValueError) as diag_error:
                result['failureDiagnosticsOutcome'] = ('event_missing' if isinstance(diag_error, Failure) and str(diag_error) == 'diagnostics_not_received'
                                                       else 'invalid_or_io')
    finally:
        if helper is not None and events is not None and helper.poll() is None and not result['fixtureCleanup']:
            try:
                helper.stdin.write(b'{"op":"stop"}\n'); helper.stdin.flush()
                cleanup_event = read_event(events,helper,'cleanup',timeout=15)
                result['fixtureCleanup'] = cleanup_event.get('peerClosed') is True and cleanup_event.get('bridgeConnections') == 0
                result['fixtureStopOutcome'] = 'confirmed' if result['fixtureCleanup'] else 'incomplete'
            except (Failure, OSError, ValueError) as stop_error:
                result['fixtureStopOutcome'] = ('event_missing' if isinstance(stop_error,Failure) and str(stop_error) == 'cleanup_not_received'
                                                else 'invalid_or_io')
        elif helper is not None and not result['fixtureCleanup']:
            result['fixtureStopOutcome'] = 'process_already_exited'
        for proc in processes:
            if proc.poll() is None:
                try: os.killpg(proc.pid,signal.SIGTERM)
                except ProcessLookupError: pass
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
            for pipe in (proc.stdin,proc.stdout):
                try: pipe.close()
                except (OSError,ValueError): pass
        for thread in readers: thread.join(timeout=2)
        for error_file in error_files: error_file.close()
        helper_log=root/'helper.stderr'
        if helper_log.exists():
            with helper_log.open('rb') as source:
                source.seek(max(0, helper_log.stat().st_size - 1048576))
                safe_text=source.read().lower()
            result['fixtureStderrIndicators']={key:token in safe_text for key,token in
                (('panic',b'panic:'),('testTimeout',b'test timed out'),('tlsError',b'tls handshake error'),('testFailure',b'--- fail:'))}
        result['processesStopped']=all(proc.poll() is not None for proc in processes) and not any(t.is_alive() for t in readers)
        try:
            shutil.rmtree(root)
        except OSError:
            pass
        result['privateRemoved']=not root.exists()
        if not all(result[k] for k in ('fixtureCleanup','processesStopped','privateRemoved')): result['status']='failed'
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result['status']=='passed'


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',required=True);parser.add_argument('--output',required=True);parser.add_argument('--network-mode',choices=('loopback','dummy'),required=True)
    args=parser.parse_args();sys.exit(0 if run(args.bundle,args.output,args.network_mode) else 1)
