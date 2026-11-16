"""Owned pairing UI: delayed read-only readiness never replays a write."""
import base64
import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import tauri_android_dual_overlay as dual

BLOB=b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+bytes([7])*32
FP='SHA256:'+base64.b64encode(hashlib.sha256(BLOB).digest()).decode().rstrip('=')
PROFILE={'version':1,'type':'herdr-connection-profile','host':'192.0.2.1','port':22,
         'username':'fixture','provider':'tailscale','session':'fixture','socketPath':'/tmp/herdr/sessions/fixture/herdr.sock',
         'herdrPath':'/tmp/herdr','expectedHostKey':'ssh-ed25519 '+base64.b64encode(BLOB).decode()}
PUBLIC={'version':2,'type':'pairing-public-key-request','account':'fixture','host_key':FP,
        'request_id':'a'*32,'device':'Pocket test','public_key':PROFILE['expectedHostKey'],'issued_at':100,'expires_at':700}
REVIEW={'role':'ts','requestId':PUBLIC['request_id'],'deviceFingerprint':'SHA256:owned-device','hostFingerprint':FP}
RESPONSE={'version':2,'type':'pairing-binding-response','account':'fixture','host_key':FP,
          'fingerprint':REVIEW['deviceFingerprint'],'request_id':PUBLIC['request_id'],'status':'authorized',
          'authorization_added':True,'issued_at':101,'expires_at':600}

class Browser:
    def __init__(self,delays=None,never=None,wrong_target=None,click_failure=None):
        self.delays=delays or {};self.never=never;self.wrong_target=wrong_target;self.click_failure=click_failure
        self.calls=[];self.probes=[];self.reads={};self.polls={}
    def evaluate(self,expression):
        self.probes.append(expression)
        spec=json.loads(re.search(r'const spec=(.*?),\$=id=>',expression).group(1))
        step=spec['step'];self.polls[step]=self.polls.get(step,0)+1
        async_ready=step!=self.never and self.polls[step]>self.delays.get(step,0)
        target=step!=self.wrong_target
        return dict(present=True,visible=True,enabled=True,foreground=True,targetMatched=target,
                    checked=False,centerHit=True,asyncReady=async_ready,ready=async_ready and (not spec['target'] or target))
    def click(self,selector):
        self.calls.append(('click',selector))
        if selector==self.click_failure:raise dual.GuiFailure('android_control_missing_'+selector.lstrip('#'))
    def fill(self,selector,value):self.calls.append(('fill',selector));self.reads[selector]=value
    def read(self,selector,prop='textContent'):
        return {'#pair-request':json.dumps(PUBLIC),'#pair-device':'Pocket test'}.get(selector,self.reads.get(selector))

def bounded(probe,code,**_):
    for _ in range(6):
        value=probe()
        if value:return value
    raise dual.GuiFailure(code)

class PairingReadinessTests(unittest.TestCase):
    def run_pair(self,browser,review=None,response=None):
        calls=[];report={}
        def host(_,message,event):
            calls.append(message['op'])
            return (review or REVIEW) if event=='pairing_review' else {'role':'ts','response':json.dumps(response or RESPONSE)}
        with patch.object(dual,'wait_for',side_effect=bounded),patch.object(dual,'host_request',side_effect=host),patch.object(dual,'host_card',return_value='#owned-card'):
            try:dual.pair_host(browser,object(),'ts',PROFILE,report)
            except dual.GuiFailure as error:return calls,report,str(error)
        return calls,report,None
    def test_late_controls_and_postconditions_dispatch_each_review_and_write_once(self):
        b=Browser(delays={step:3 for step in ('new_form','profile_ready','target_checked','request_ready',
                                            'response_reviewed','source_checked','accepted','saved','returned')})
        calls,report,error=self.run_pair(b)
        self.assertIsNone(error);self.assertEqual(calls,['review_pairing','approve_pairing'])
        for selector in ('#pair-target-review','#pair-create','#pair-preview','#pair-source-review','#pair-accept','#host-save'):
            self.assertEqual(b.calls.count(('click',selector)),1)
        self.assertEqual(report['pairingAttempts'][0]['state'],'complete')
        for forbidden in ('SHA256:','fixture','request_id','response','192.0.2.1','ssh-ed25519'):
            # Only fixed stage names may mention response; actual response bytes never appear.
            if forbidden!='response':self.assertNotIn(forbidden,json.dumps(report))
        self.expressions=b.probes
    def test_request_visible_but_busy_timeout_never_approves_or_recreates(self):
        b=Browser(never='request_ready');calls,report,error=self.run_pair(b)
        self.assertEqual(error,'dual_pair_step_timeout');self.assertEqual(calls,[])
        self.assertEqual(b.calls.count(('click','#pair-create')),1)
        self.assertNotIn(('fill','#pair-response'),b.calls)
        self.assertEqual(report['pairingAttempts'][0]['step'],'request_ready')
    def test_wrong_target_and_role_remain_negative_controls(self):
        for step in ('target_ready','target_checked','request_reviewed','response_reviewed','source_checked'):
            with self.subTest(step=step):
                b=Browser(wrong_target=step);calls,report,error=self.run_pair(b)
                self.assertIsNotNone(error);self.assertNotIn(('click','#pair-accept'),b.calls)
                self.assertFalse(report['pairingAttempts'][0]['facts']['targetMatched'])
        b=Browser();calls,_,error=self.run_pair(b,review={**REVIEW,'role':'et'})
        self.assertEqual(error,'dual_pair_review_mismatch');self.assertEqual(calls,['review_pairing'])
        b=Browser();calls,_,error=self.run_pair(b,response={**RESPONSE,'account':'other'})
        self.assertEqual(error,'dual_pair_review_mismatch');self.assertNotIn(('fill','#pair-response'),b.calls)
    def test_unknown_accept_and_missing_control_are_not_replayed(self):
        b=Browser(never='accepted');calls,report,error=self.run_pair(b)
        self.assertIsNotNone(error);self.assertEqual(b.calls.count(('click','#pair-accept')),1)
        self.assertNotIn(('click','#host-save'),b.calls)
        b=Browser(click_failure='#pair-create');calls,report,error=self.run_pair(b)
        self.assertEqual(calls,[]);self.assertEqual(b.calls.count(('click','#pair-create')),1)
        self.assertEqual({k:report['pairingAttempts'][0][k] for k in ('role','step','action','control','state')},
                         {'role':'ts','step':'create','action':'click','control':'pair_create','state':'failed'})
    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_every_generated_probe_compiles_in_real_javascript_engine(self):
        b=Browser();self.assertIsNone(self.run_pair(b)[2])
        script="const expressions=JSON.parse(require('fs').readFileSync(0,'utf8'));for(const expression of expressions)new Function('return '+expression);console.log(expressions.length);"
        run=subprocess.run(['node','-e',script],input=json.dumps(b.probes),text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertGreater(int(run.stdout),20)

if __name__=='__main__':unittest.main()
