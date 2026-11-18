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
REVIEW={'role':'ts','requestId':PUBLIC['request_id'],'deviceFingerprint':FP,'hostFingerprint':FP}
RESPONSE={'version':2,'type':'pairing-binding-response','account':'fixture','host_key':FP,
          'fingerprint':REVIEW['deviceFingerprint'],'request_id':PUBLIC['request_id'],'status':'authorized',
          'authorization_added':True,'issued_at':101,'expires_at':600}

class Browser:
    def __init__(self,delays=None,never=None,wrong_target=None,click_failure=None,
                 future_reads=0,preview_misses=0,expired=False,change_after_preview=False,replace_after_preview=False):
        self.delays=delays or {};self.never=never;self.wrong_target=wrong_target;self.click_failure=click_failure
        self.calls=[];self.probes=[];self.reads={};self.polls={};self.functions=[]
        self.future_reads=future_reads;self.preview_misses=preview_misses;self.expired=expired
        self.change_after_preview=change_after_preview;self.replace_after_preview=replace_after_preview
        self.previews=0;self.activation_polls=[]
    def evaluate(self,expression):
        self.probes.append(expression)
        if expression.startswith('(function dashboardAddEntry()'):
            return '#host-open-remote' if ('click','#host-return-home') in self.calls else '#host-empty-add'
        spec=json.loads(re.search(r'const spec=(.*?),\$=id=>',expression).group(1))
        step=spec['step'];self.polls[step]=self.polls.get(step,0)+1
        if step=='response_material':
            future=self.polls[step]<=self.future_reads
            facts={key:True for key in dual.PAIR_RESPONSE_FACTS}
            facts.update(sourceChecked=False,busy=False,responseWithinDeviceTime=not future,productValid=not future,
                         responseUnexpired=not self.expired,exactInput=not (self.change_after_preview and self.previews>0),
                         previewVisible=self.previews>self.preview_misses,fiveLinesMatched=self.previews>self.preview_misses,
                         productShowsInvalid=0<self.previews<=self.preview_misses)
            facts['ready']=not future and not self.expired and facts['exactInput']
            return facts
        async_ready=step!=self.never and self.polls[step]>self.delays.get(step,0)
        target=step!=self.wrong_target
        return dict(present=True,visible=True,enabled=True,foreground=True,targetMatched=target,
                    checked=False,centerHit=True,asyncReady=async_ready,ready=async_ready and (not spec['target'] or target))
    def call(self,method,args):
        if method=='Runtime.evaluate':return {'result':{'objectId':'owned-preview-node'}}
        if method=='Runtime.callFunctionOn':
            self.functions.append(args['functionDeclaration'])
            return {'result':{'value':not (self.replace_after_preview and self.previews>0)}}
        if method=='Runtime.releaseObject':return {}
        if method=='Input.dispatchKeyEvent':
            if args['type']=='keyDown':
                self.previews+=1;self.calls.append(('enter','#pair-preview'));self.activation_polls.append(self.polls['response_material'])
            return {}
        raise AssertionError(method)
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
        self.assertEqual(b.calls[:2],[('click','#host-empty-add'),('click','#add-herdr')])
        self.assertNotIn(('click','#host-open-remote'),b.calls)
        last=report['pairingAttempts'][0]
        self.assertEqual((last['step'],last['action'],last['control']),('returned','read','host_open_remote'))
        for selector in ('#pair-target-review','#pair-create','#pair-source-review','#pair-accept','#host-save'):
            self.assertEqual(b.calls.count(('click',selector)),1)
        self.assertEqual(b.calls.count(('enter','#pair-preview')),1)
        self.assertFalse(report['pairingAttempts'][0]['sawFutureIssuance'])
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
        run=subprocess.run(['node','-e',script],input=json.dumps(b.probes+['('+f+')' for f in b.functions]),text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertGreater(int(run.stdout),20)

    def test_device_future_window_is_read_only_and_preview_waits_for_two_valid_readbacks(self):
        b=Browser(future_reads=3);calls,report,error=self.run_pair(b)
        self.assertIsNone(error);self.assertEqual(calls,['review_pairing','approve_pairing'])
        self.assertEqual(b.previews,1);self.assertGreater(b.activation_polls[0],3)
        self.assertTrue(report['pairingAttempts'][0]['responseFacts']['productValid'])
        self.assertTrue(report['pairingAttempts'][0]['sawFutureIssuance'])
    def test_expired_response_fails_immediately_without_preview_accept_or_approval_replay(self):
        b=Browser(expired=True);calls,report,error=self.run_pair(b)
        self.assertEqual(error,'dual_pair_response_invalid');self.assertEqual(b.previews,0)
        self.assertEqual(calls.count('approve_pairing'),1);self.assertNotIn(('click','#pair-accept'),b.calls)
        self.assertFalse(report['pairingAttempts'][0]['responseFacts']['responseUnexpired'])
    def test_one_read_only_reinspection_never_reapproves_recreates_accepts_twice_or_retargets(self):
        b=Browser(preview_misses=1);calls,report,error=self.run_pair(b)
        self.assertIsNone(error);self.assertEqual(b.previews,2);self.assertEqual(calls.count('approve_pairing'),1)
        self.assertEqual(b.calls.count(('click','#pair-create')),1);self.assertEqual(b.calls.count(('click','#pair-accept')),1)
        b=Browser(preview_misses=2);calls,report,error=self.run_pair(b)
        self.assertEqual(error,'dual_pair_preview_unpublished');self.assertEqual(b.previews,2)
        self.assertNotIn(('click','#pair-accept'),b.calls)
        for options in ({'change_after_preview':True},{'replace_after_preview':True}):
            b=Browser(preview_misses=1,**options);calls,report,error=self.run_pair(b)
            self.assertIsNotNone(error);self.assertEqual(b.previews,1);self.assertNotIn(('click','#pair-accept'),b.calls)

    @unittest.skipUnless(shutil.which('node'),'Node unavailable')
    def test_real_product_validator_and_read_only_device_clock_boundary(self):
        fields={'remote-'+field:str(PROFILE[key]) for field,key in
                (('host','host'),('port','port'),('user','username'),('session','session'),('herdr','herdrPath'),
                 ('socket','socketPath'),('pin','expectedHostKey'),('profile-provider','provider'))}
        cases=[]
        def case(name,now,request=PUBLIC,response=RESPONSE):
            expression=dual.pairing_response_probe(json.dumps(request),json.dumps(response),'fixture',FP,FP,fields)
            cases.append({'name':name,'now':now,'expression':expression})
        case('future_one_second',100);case('same_receipt_valid_after_one_second',101);case('same_receipt_expired',600)
        case('fresh',100,response={**RESPONSE,'issued_at':100})
        for key,value in (('version',1),('type','other'),('request_id','b'*32),('account','other'),
                          ('host_key','SHA256:other'),('fingerprint','SHA256:other'),('status','revoked'),('authorization_added',1)):
            case('wrong_'+key,101,response={**RESPONSE,key:value})
        case('expiry_ordering',201,response={**RESPONSE,'issued_at':200,'expires_at':701})
        case('over_ttl',101,response={**RESPONSE,'issued_at':0,'expires_at':601})
        case('request_wrong_version',101,request={**PUBLIC,'version':1})
        script=r"""const cases=JSON.parse(require('fs').readFileSync(0,'utf8')),result={};
        for(const sample of cases){
          const spec=JSON.parse(sample.expression.match(/const spec=(.*?),\$=id=>/s)[1]),nodes=new Map(),req=JSON.parse(spec.request);
          const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',hidden:false,disabled:false,checked:false,readOnly:true,
            dataset:{},getClientRects(){return this.hidden?[]:[1]},matches(){return this.disabled}});return nodes.get(id);};
          for(const [id,value]of Object.entries(spec.fields))$(id).value=value;
          $('pair-request').value=spec.request;$('pair-response').value=spec.response;$('pair-device').value=req.device;
          $('pair-mode').checked=true;$('pair-status').textContent='等待主机响应 · 设备指纹 '+spec.deviceFingerprint+' · 授权未知';
          $('pair-status').dataset.createPhase='ready';$('pair-request-summary').textContent='仍待主机操作者确认';$('pair-preview').textContent='查看响应内容';
          const document={hidden:false,getElementById:$},getComputedStyle=()=>({visibility:'visible'}),Date={now:()=>sample.now*1000};
          result[sample.name]=new Function('document','getComputedStyle','Date','return '+sample.expression)(document,getComputedStyle,Date);
        }console.log(JSON.stringify(result));"""
        run=subprocess.run(['node','-e',script],input=json.dumps(cases),text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);facts=json.loads(run.stdout)
        self.assertFalse(facts['future_one_second']['productValid']);self.assertFalse(facts['future_one_second']['responseWithinDeviceTime'])
        self.assertTrue(facts['same_receipt_valid_after_one_second']['ready']);self.assertTrue(facts['fresh']['ready'])
        self.assertFalse(facts['same_receipt_expired']['responseUnexpired'])
        for name,value in facts.items():
            self.assertTrue(all(type(flag) is bool for flag in value.values()))
            if name not in ('fresh','same_receipt_valid_after_one_second'):self.assertFalse(value['ready'],name)
        self.assertFalse(facts['expiry_ordering']['expiryOrdering']);self.assertFalse(facts['over_ttl']['withinTtl'])

if __name__=='__main__':unittest.main()
