"""Offline guards for the isolated C ABI runner; no Tailscale account or network."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
from email.message import Message
from unittest.mock import patch

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
    def test_health_probe_uses_supported_key_and_requires_exact_200_json(self):
        class Reply:
            def __init__(self,status,body,content='application/json'):
                self.status=status; self.body=body; self.headers=Message(); self.headers['Content-Type']=content
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,limit): return self.body[:limit]
        class Opener:
            def __init__(self,reply): self.reply=reply; self.request=None
            def open(self,request,timeout): self.request=request; return self.reply
        valid=json.dumps({'publicKey':'mkey:'+'a'*64,'legacyPublicKey':'mkey:'+'0'*64}).encode()
        for reply,expected in ((Reply(200,valid),True),(Reply(404,valid),False),
                               (Reply(200,b'{}'),False),(Reply(200,valid,'text/plain'),False)):
            opener=Opener(reply)
            with patch.object(runner.ssl,'create_default_context') as context,patch.object(runner.urllib.request,'build_opener',return_value=opener):
                self.assertIs(runner.control_reached('https://127.0.0.1:1234','/owned/ca'),expected)
            self.assertEqual(opener.request.full_url,'https://127.0.0.1:1234/key?v=1')
            context.assert_called_once_with(cafile='/owned/ca')

    def test_network_scope_accepts_only_isolated_dummy_and_no_routes(self):
        loop={'ifname':'lo','flags':['UP']}
        dummy={'ifname':'hp-fixture0','flags':['UP'],'linkinfo':{'info_kind':'dummy'}}
        loop_address={'ifname':'lo','addr_info':[{'family':'inet','local':'127.0.0.1','prefixlen':8}]}
        address={'ifname':'hp-fixture0','addr_info':[{'family':'inet','local':'192.0.2.1','prefixlen':32}]}
        self.assertTrue(runner.network_checked('loopback',[loop],[loop_address],[],[]))
        self.assertTrue(runner.network_checked('dummy',[loop,dummy],[loop_address,address],[],[]))
        for links,addresses,v4,v6 in (([loop,dummy],[address],[{'dst':'default'}],[]),
                                        ([loop,{'ifname':'eth0'}],[address],[],[]),
                                        ([loop,dummy],[{'ifname':'hp-fixture0','addr_info':[]}],[],[])):
            with self.assertRaises(runner.Failure): runner.network_checked('dummy',links,addresses,v4,v6)

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
