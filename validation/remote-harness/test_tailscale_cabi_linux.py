"""Offline guards for the isolated C ABI runner; no Tailscale account or network."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('tailscale_cabi_linux',HERE/'tailscale_cabi_linux.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class CabiGuards(unittest.TestCase):
    def test_ready_is_owned_loopback_ca_and_tailnet(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ca=root/'ca.pem';ca.write_text('synthetic')
            good={'event':'ready','controlUrl':'https://127.0.0.1:32123','caFile':str(ca),'peerIp':'100.64.2.3','peerPort':2222}
            self.assertEqual(runner.ready_checked(good,root)[2],'100.64.2.3')
            for change in ({'controlUrl':'https://example.com:32123'}, {'peerIp':'127.0.0.1'},
                           {'peerPort':22}, {'caFile':'/etc/hosts'}, {'controlUrl':'http://127.0.0.1:32123'}):
                with self.subTest(change=change), self.assertRaises(runner.Failure): runner.ready_checked({**good,**change},root)
    def test_control_diagnostics_allow_only_bounded_counts_and_boolean(self):
        good={'event':'diagnostics','keyRequests':1,'noiseRequests':2,'registerRequests':3,
              'mapRequests':4,'tlsHandshakeErrors':0,'authCompletions':1,'secondClientRegistered':True,
              'secret':'never-export'}
        self.assertNotIn('secret',runner.diagnostics_checked(good))
        for key in ('keyRequests','authCompletions','secondClientRegistered'):
            with self.subTest(key=key), self.assertRaises(runner.Failure): runner.diagnostics_checked({**good,key:'secret'})

    def test_partial_evidence_never_exports_untrusted_values(self):
        got=runner.partial_checked({'states':['NeedsLogin','secret-value'], 'authUrlPresent':False,
                                   'beginLoginCode':0, 'private':'secret-value', 'nodeCloseCode':'secret-value'})
        self.assertEqual(got,{'states':['NeedsLogin'],'authUrlPresent':False,'beginLoginCode':0})
        self.assertNotIn('secret-value',str(got))

    def test_auth_origin_and_complete_evidence_are_strict(self):
        self.assertTrue(runner.auth_checked('https://127.0.0.1:1234/auth/abc','https://127.0.0.1:1234'))
        for value in ('https://elsewhere:1234/auth/abc','http://127.0.0.1:1234/auth/abc','https://127.0.0.1:1234/auth#x'):
            with self.assertRaises(runner.Failure): runner.auth_checked(value,'https://127.0.0.1:1234')
        good={'event':'cabi_result','startCode':0,'preLoginNoUrl':True,'preLoginDialCode':7,'beginLoginCode':0,
              'authUrlPresent':True,'running':True,'dialCode':0,'payloadEqual':True,'streamCloseCode':0,
              'streamReleaseCode':0,'nodeCloseCode':0,'nodeReleaseCode':0,'outstandingReadBuffers':0}
        self.assertTrue(runner.report_checked(good)['payloadEqual'])
        for key in ('authUrlPresent','payloadEqual','running','nodeReleaseCode'):
            with self.subTest(key=key), self.assertRaises(runner.Failure): runner.report_checked({**good,key:None})

if __name__=='__main__': unittest.main()
