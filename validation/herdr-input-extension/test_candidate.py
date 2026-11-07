"""Temporary files/processes and a synthetic Unix peer; never an installed herdr."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('host_candidate', Path(__file__).with_name('candidate.py'))
C = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(C)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='hp-candidate-test-', dir=C.TEMP_PARENT)
        self.root = Path(self.temporary.name).resolve()
    def tearDown(self):
        self.temporary.cleanup()
    def fake(self, mode='ok'):
        """The fixture implements only these RPC shapes, not herdr/PTY behavior."""
        path = self.root / ('fake-' + mode)
        path.write_text('#!' + sys.executable + '\n' + '''
import json,os,pathlib,socket,sys,time
MODE=MODE_VALUE
if '--version' in sys.argv:
    print('herdr 0.9.5' if MODE!='version' else 'herdr 0.9.4');raise SystemExit
session=sys.argv[sys.argv.index('--session')+1]
if 'workspace' in sys.argv:
    print(json.dumps({'result':{'root_pane':{'pane_id':'w1:p1'}}}));raise SystemExit
root=pathlib.Path(os.environ['HOME']).parent
(root/'pid').write_text(str(os.getpid()))
if MODE=='hang': time.sleep(30);raise SystemExit
sock=root/'config/herdr/sessions'/session/'herdr.sock';sock.parent.mkdir(parents=True)
listener=socket.socket(socket.AF_UNIX);listener.bind(str(sock));listener.listen()
while True:
    conn,_=listener.accept()
    with conn:
        data=bytearray()
        while b'\\n' not in data:data.extend(conn.recv(4096))
        request=json.loads(data);method=request['method'];response={'id':request['id']}
        if method=='session.snapshot':response['result']={'type':'session_snapshot','snapshot':{'version':'0.9.5','protocol':22,'panes':[{'pane_id':'w1:p1','terminal_id':'term_abc'}]}}
        elif method=='pocket.input.capabilities':
            response['result']={'type':'pocket_input_capabilities','version':1,'protocol':22,'atomic_terminal_guard':True,'raw_bytes':True,'max_input_bytes':4096}
            if MODE=='capability':response['result']['atomic_terminal_guard']=1
        elif method=='pocket.input.send':
            params=request['params']
            if params['expected_terminal_id']!='term_abc':response['error']={'code':'pocket_input_rejected'}
            else:
                if MODE=='lost': continue
                response['result']={'type':'pocket_input_accepted','pane_id':'w1:p1','terminal_id':'term_abc','accepted_bytes':1}
                if MODE=='receipt':response['result']['accepted_bytes']=True
        else:response['error']={'code':'unexpected'}
        conn.sendall(json.dumps(response).encode()+b'\\n')
'''.replace('MODE_VALUE', repr(mode)))
        path.chmod(0o700)
        return path
    def package(self, mode='ok'):
        binary = self.fake(mode); out = self.root / ('package-' + mode);out.mkdir()
        (out / C.NAME).write_bytes(binary.read_bytes());(out / C.NAME).chmod(0o700)
        (out / C.PATCH.name).write_bytes(C.PATCH.read_bytes());(out/'LICENSE').write_bytes(b'fixture license')
        manifest={'schemaVersion':1,'scope':C.SCOPE,'status':'built','upstreamSHA':C.BASE,
                  'patchSHA256':C.PATCH_HASH,'sourceSHA':C.BASE,'buildProfile':'release','binaryDebugAssertions':False,
                  'releaseGuardTestPassed':True,'platform':{'system':platform.system(),'machine':platform.machine()},
                  'binary':{'name':C.NAME,'sha256':C.digest(out/C.NAME)},'license':{'name':'LICENSE','sha256':C.digest(out/'LICENSE')}}
        (out/'manifest.json').write_text(json.dumps(manifest));return out,manifest
    def test_no_credentials_or_shell_hooks_reach_owned_environment(self):
        with patch.dict(os.environ,{'SSH_AUTH_SOCK':'secret','HERDR_SESSION':'real','ENV':'startup','API_KEY':'secret'}):
            env=C.clean_env(self.root/'sandbox')
        self.assertFalse({'SSH_AUTH_SOCK','HERDR_SESSION','ENV','API_KEY'} & env.keys())
        for name in ('HOME','XDG_CONFIG_HOME','XDG_STATE_HOME','XDG_DATA_HOME','XDG_CACHE_HOME','TMPDIR'):
            self.assertTrue(Path(env[name]).is_relative_to(self.root))
            self.assertEqual(Path(env[name]).stat().st_mode & 0o777,0o700)
    def test_new_output_never_overwrites_or_follows_links(self):
        existing=self.root/'existing';existing.mkdir();(existing/'work').write_text('keep')
        for value in (existing,self.root/'missing-parent'/'output'):
            with self.assertRaises(C.Refused):C.new_output(value)
        (self.root/'link').symlink_to(existing,target_is_directory=True)
        with self.assertRaises(C.Refused):C.new_output(self.root/'link'/'output')
        self.assertEqual((existing/'work').read_text(),'keep')
    def test_archive_rejects_escape_and_external_symlink(self):
        for name,link in (('../outside',None),('escape','/outside')):
            archive=self.root/'source.tar'
            with tarfile.open(archive,'w') as tar:
                item=tarfile.TarInfo(name)
                if link:item.type=tarfile.SYMTYPE;item.linkname=link;tar.addfile(item)
                else:item.size=1;tar.addfile(item,io.BytesIO(b'x'))
            work=self.root/'work';work.mkdir(exist_ok=True)
            with self.assertRaises(C.Refused):C.extract_source(archive,work)
    def test_manifest_refuses_dev_tamper_wrong_platform_before_execution(self):
        folder,manifest=self.package()
        C.candidate(folder)
        for key,value in [('buildProfile','dev'),('binaryDebugAssertions',True),('releaseGuardTestPassed',False),('upstreamSHA','other'),('patchSHA256','0'*64),('platform',{'system':'other','machine':'other'})]:
            (folder/'manifest.json').write_text(json.dumps(dict(manifest,**{key:value})))
            with self.assertRaises(C.Refused):C.candidate(folder)
        (folder/'manifest.json').write_text(json.dumps(manifest));(folder/C.NAME).write_bytes(b'tampered')
        with self.assertRaises(C.Refused):C.candidate(folder)
    def test_synthetic_peer_exercises_receipts_and_reports_cleanup(self):
        folder,manifest=self.package();out=self.root/'evidence'
        result=C.preflight(folder,out)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['inputQueueAcceptedBytes'],1)
        self.assertTrue(result['wrongTerminalRejected'])
        self.assertTrue(result['ownedServerProcessStopped'])
        self.assertTrue(result['temporaryDataRemoved'])
        self.assertFalse(result['serverReportedSessionIdentity'])
        self.assertFalse(result['ptyDeliveryVerified'])
        self.assertEqual(json.loads((out/'preflight.json').read_text())['binarySHA256'],manifest['binary']['sha256'])
    def test_failure_paths_retain_stage_and_cleanup_without_claiming_acceptance(self):
        for mode,code in [('capability','candidate_capability_mismatch'),('receipt','candidate_queue_receipt_invalid'),('lost','rpc_response_invalid'),('hang','candidate_readiness_timeout')]:
            with self.subTest(mode=mode):
                result=C.probe(self.fake(mode),deadline_seconds=0.1)
                self.assertEqual(result['status'],'failed');self.assertEqual(result['errorCode'],code)
                self.assertEqual(result['inputQueueAcceptedBytes'],0)
                self.assertTrue(result['ownedServerProcessStopped']);self.assertTrue(result['temporaryDataRemoved'])
    def test_owned_process_cleanup_escalates_only_recorded_group(self):
        from unittest.mock import Mock,call
        process=Mock(pid=918273)
        process.poll.side_effect=[None,0]
        process.wait.side_effect=[subprocess.TimeoutExpired('owned',5),0]
        with patch.object(C.os,'killpg') as kill:
            self.assertTrue(C.stop_owned(process))
        self.assertEqual(kill.call_args_list,[call(918273,signal.SIGTERM),call(918273,signal.SIGKILL)])
    def test_missing_build_tools_do_not_create_output_or_mutate_source(self):
        source=self.root/'source';source.mkdir();out=self.root/'candidate';cache=self.root/'cargo';cache.mkdir()
        with patch.object(C,'run',return_value=C.BASE),patch.object(C,'tool',side_effect=C.Refused('zig_missing')):
            with self.assertRaisesRegex(C.Refused,'zig_missing'):C.build(source,out,cache)
        self.assertFalse(out.exists());self.assertEqual(list(source.iterdir()),[])
    def test_failed_build_manifest_does_not_publish_a_binary(self):
        source=self.root/'source';source.mkdir();cache=self.root/'cargo';cache.mkdir();out=self.root/'candidate'
        def command(argv,**kwargs):
            if 'rev-parse' in argv:return C.BASE
            if 'archive' in argv:
                with tarfile.open(fileobj=kwargs['stdout'],mode='w'):pass
                return ''
            raise C.Refused('tool_failed')
        with patch.object(C,'run',side_effect=command),patch.object(C,'tool',side_effect=lambda name,prefix:('/usr/bin/'+name,prefix)):
            with self.assertRaises(C.Refused):C.build(source,out,cache)
        manifest=json.loads((out/'manifest.json').read_text())
        self.assertEqual(manifest['status'],'failed');self.assertEqual(manifest['buildProfile'],'release')
        self.assertEqual(manifest['upstreamSHA'],C.BASE);self.assertFalse((out/C.NAME).exists())
    def test_build_uses_offline_release_and_records_verified_source_hashes(self):
        source=self.root/'source';source.mkdir();cache=self.root/'cargo';cache.mkdir();out=self.root/'candidate';commands=[]
        def command(argv,**kwargs):
            commands.append(list(map(str,argv)))
            if 'rev-parse' in argv:return C.BASE
            if 'archive' in argv:
                with tarfile.open(fileobj=kwargs['stdout'],mode='w'):pass
                return ''
            if 'test' in argv:return 'test result: ok. 1 passed; 0 failed; 0 ignored;'
            if 'rustc' in argv:
                target=Path(kwargs['cwd'])/'target/release';target.mkdir(parents=True);(target/'herdr').write_bytes(b'fixture binary');(Path(kwargs['cwd'])/'LICENSE').write_bytes(b'fixture license')
            return ''
        with patch.object(C,'run',side_effect=command),patch.object(C,'tool',side_effect=lambda name,prefix:('/usr/bin/'+name,prefix)):
            manifest=C.build(source,out,cache)
        for command in (c for c in commands if any(x in c for x in ('test','rustc'))):
            self.assertTrue({'--offline','--locked','--release'} <= set(command))
        self.assertEqual(manifest['binary']['sha256'],hashlib.sha256(b'fixture binary').hexdigest())
        self.assertEqual(manifest['patchSHA256'],C.PATCH_HASH);self.assertEqual(manifest['status'],'built')
        self.assertEqual(list(source.iterdir()),[])

    def test_wrong_source_and_sensitive_cache_are_refused_before_build(self):
        source=self.root/'source';source.mkdir();cache=self.root/'cache';cache.mkdir()
        with patch.object(C,'run',return_value='wrong'),patch.object(C,'tool') as tool:
            with self.assertRaisesRegex(C.Refused,'source_commit_mismatch'):C.build(source,self.root/'out',cache)
            tool.assert_not_called()
        (cache/'credentials.toml').write_text('sentinel must not be read')
        with patch.object(C,'run',return_value=C.BASE),patch.object(C,'tool',side_effect=lambda name,prefix:('/usr/bin/'+name,'0.16.0' if name=='zig' else prefix)):
            with self.assertRaisesRegex(C.Refused,'dedicated_offline_cargo_cache_required'):C.build(source,self.root/'out',cache)
        self.assertFalse((self.root/'out').exists())
    def test_candidate_refuses_symlink_manifest_without_reading_external_target(self):
        folder,_=self.package();(folder/'manifest.json').unlink()
        external=self.root/'external';external.write_text('sentinel')
        (folder/'manifest.json').symlink_to(external)
        with self.assertRaisesRegex(C.Refused,'candidate_file_invalid'):C.candidate(folder)
        self.assertEqual(external.read_text(),'sentinel')
    def test_unconfirmed_cleanup_retains_only_owned_temporary_directory(self):
        def unconfirmed(_binary,root,result,_deadline):
            result.update(serverStarted=True,status='passed')
        with patch.object(C,'_probe_in_root',side_effect=unconfirmed):result=C.probe(self.fake())
        retained=Path(result['retainedTemporaryRoot'])
        try:
            self.assertEqual(result['status'],'failed');self.assertFalse(result['temporaryDataRemoved'])
            self.assertTrue(retained.exists());self.assertTrue(retained.name.startswith('hp-host-probe-'))
        finally:retained.rmdir()
    def test_timeout_retires_tool_process_group_and_returns_static_code(self):
        from unittest.mock import Mock
        process=Mock();process.communicate.side_effect=subprocess.TimeoutExpired('fixture',1)
        with patch.object(C.subprocess,'Popen',return_value=process),patch.object(C,'stop_owned',return_value=True) as stop:
            with self.assertRaisesRegex(C.Refused,'tool_timed_out'):C.run(['fixture'],timeout=1)
            stop.assert_called_once_with(process)

    def test_zero_matching_guard_tests_cannot_publish_a_release_candidate(self):
        source=self.root/'source';source.mkdir();cache=self.root/'cargo';cache.mkdir();out=self.root/'candidate'
        def command(argv,**kwargs):
            if 'rev-parse' in argv:return C.BASE
            if 'archive' in argv:
                with tarfile.open(fileobj=kwargs['stdout'],mode='w'):pass
            if 'test' in argv:return 'test result: ok. 0 passed; 0 failed;'
            return ''
        with patch.object(C,'run',side_effect=command),patch.object(C,'tool',side_effect=lambda name,prefix:('/usr/bin/'+name,prefix)):
            with self.assertRaisesRegex(C.Refused,'release_guard_test_not_proven'):C.build(source,out,cache)
        self.assertEqual(json.loads((out/'manifest.json').read_text())['status'],'failed')
        self.assertFalse((out/C.NAME).exists())
    def test_malformed_manifest_is_a_bounded_refusal(self):
        folder,_=self.package()
        for value in ([],{'binary':[]},'x'*16385):
            (folder/'manifest.json').write_text(json.dumps(value))
            with self.assertRaises(C.Refused):C.candidate(folder)

    def test_cloud_summary_links_stages_and_discards_paths_raw_output_and_unknown_fields(self):
        folder,manifest=self.package();manifest.update(producerSHA256='a'*64,temporaryDataRemoved=True,
          toolchains={'cargo':'cargo 1.96.0 (30a34c682 2026-05-25)','rustc':'rustc 1.96.0 (ac68faa20 2026-05-25)','zig':'0.16.0'},
          retainedTemporaryRoot='/secret/path',rawLog='secret-token')
        (folder/'manifest.json').write_text(json.dumps(manifest));pre=self.root/'pre';pre.mkdir()
        result={'sourceSHA':C.BASE,'upstreamSHA':C.BASE,'patchSHA256':C.PATCH_HASH,'buildProfile':'release','binarySHA256':manifest['binary']['sha256'],
                'status':'passed','inputQueueAcceptedBytes':1,'rawText':'secret-terminal',
                **{k:True for k in ('versionChecked','capabilityChecked','namedSocketIsolationChecked','wrongTerminalRejected','serverStarted','ownedServerProcessStopped','temporaryDataRemoved')}}
        (pre/'preflight.json').write_text(json.dumps(result));tests=self.root/'tests.json'
        tests.write_text(json.dumps({'sourceSHA':C.BASE,'status':'passed','testsRun':16,'failures':0,'errors':0,'skipped':0,'rawLog':'secret-test'}))
        out=self.root/'summary'
        evidence=C.cloud_evidence(folder,pre,tests,out,C.BASE,C.ZIG_ARCHIVE_HASH)
        self.assertEqual(evidence['status'],'passed');self.assertFalse(evidence['candidateBinaryUploaded'])
        self.assertEqual(evidence['dependencyDistributionReview'],'pending')
        self.assertNotIn('secret',(out/'summary.json').read_text());self.assertEqual(list(out.iterdir()),[out/'summary.json'])
        result['binarySHA256']='f'*64;(pre/'preflight.json').write_text(json.dumps(result))
        failed=C.cloud_evidence(folder,pre,tests,self.root/'mismatch',C.BASE,C.ZIG_ARCHIVE_HASH)
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['preflight']['status'],'not-run')
    def test_cloud_summary_missing_reports_never_claims_success(self):
        report=C.cloud_evidence(self.root/'absent',self.root/'absent',self.root/'absent',self.root/'evidence',C.BASE,C.ZIG_ARCHIVE_HASH)
        self.assertEqual(report['status'],'failed');self.assertIsNone(report['binarySHA256'])
        self.assertEqual(report['toolTests']['status'],'not-run')
        with self.assertRaises(C.Refused):C.cloud_evidence(self.root,self.root,self.root,self.root/'nope',C.BASE,'0'*64)
    def test_optional_cloud_lane_keeps_normal_dev_and_gui_dependencies_separate(self):
        import re
        repo=Path(__file__).resolve().parents[2]
        reusable=(repo/'.github/workflows/input-extension-validation.yml').read_text()
        caller=(repo/'.github/workflows/android-network-experiment.yml').read_text()
        def job(text,name):
            match=re.search(r'^  '+re.escape(name)+r':\n(.*?)(?=^  [a-z][a-z0-9-]*:|\Z)',text,re.M|re.S)
            self.assertIsNotNone(match,name);return match.group(1)
        self.assertIn('type: boolean',reusable);self.assertIn('default: false',reusable)
        self.assertIn("!inputs.release_candidate && startsWith(github.ref, 'refs/heads/codex/')",job(reusable,'build'))
        release=job(reusable,'release-profile');host=job(caller,'input-host-candidate')
        prefix='refs/heads/codex/network-batch/with-emulators-input-host-'
        self.assertIn("inputs.release_candidate && startsWith(github.ref, '"+prefix+"')",release)
        self.assertIn("startsWith(github.ref, '"+prefix+"')",host);self.assertIn('release_candidate: true',host)
        self.assertNotIn('needs:',host);self.assertNotIn('needs:',release)
        for name in ('android-pairing','flutter-source','apps'):
            self.assertNotIn('input-host-candidate',job(caller,name))
        self.assertIn("refs/heads/codex/network-batch/with-emulators-input-'",job(caller,'input-fixture'))
        self.assertIn('cargo fetch --locked',release);self.assertIn('echo "$RUNNER_TEMP/input-host-zig" >> "$GITHUB_PATH"',release)
        self.assertIn('path: ${{ runner.temp }}/input-host-evidence/summary.json',release)
        self.assertNotIn('path: ${{ runner.temp }}/input-host-candidate',release)
        for branch,request,expected in [('with-emulators-input-recheck-cb0fd1c',False,False),('with-emulators-input-host-example',True,True),('with-emulators-input-example',True,False),('with-emulators-input-host-example',False,False)]:
            ref='refs/heads/codex/network-batch/'+branch
            self.assertEqual(request and ref.startswith(prefix),expected)


if __name__=='__main__':unittest.main()
