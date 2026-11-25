import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import tauri_windows_direct_ssh as runner
from paired_gui import GuiFailure


class WindowProof(unittest.TestCase):
    def setUp(self):
        self.gui = SimpleNamespace(
            GetForegroundWindow=lambda: 10, IsIconic=lambda _: False,
            GetClientRect=lambda _: (0, 0, 1024, 700),
            ClientToScreen=lambda _, point: point,
            GetWindowText=lambda _: 'Herdr Pocket', IsWindowVisible=lambda _: True,
            EnumWindows=lambda callback, arg: callback(10, arg),
            WindowFromPoint=lambda _: 11, GetAncestor=lambda *_: 10,
        )
        self.api = SimpleNamespace(MonitorFromWindow=lambda *_: 1,
                                   GetMonitorInfo=lambda _: {'Monitor': (0, 0, 1024, 768)})
        self.con = SimpleNamespace(MONITOR_DEFAULTTONULL=0, GA_ROOT=2)
        self.job = SimpleNamespace(JobObjectBasicProcessIdList=1,
                                   QueryInformationJobObject=lambda *_: [17])
        self.process = SimpleNamespace(GetWindowThreadProcessId=lambda _: (1, 17))
        for name, value in [('win32gui',self.gui),('win32api',self.api),('win32con',self.con),
                            ('win32job',self.job),('win32process',self.process),('check_desktop',lambda:None)]:
            patcher = patch.object(runner, name, value, create=True); patcher.start(); self.addCleanup(patcher.stop)

    def capture(self):
        return runner.framebuffer('job',10,17,[1024,700],[[10,10,300,120],[1,1,20,20]])

    def test_owned_foreground_original_client_pixels(self):
        self.assertEqual(self.capture(),(0,0,1024,700))

    def test_other_owner_and_wrong_viewport_fail_closed(self):
        self.process.GetWindowThreadProcessId=lambda _: (1,18)
        with self.assertRaises(GuiFailure): self.capture()
        self.process.GetWindowThreadProcessId=lambda _: (1,17)
        with self.assertRaises(GuiFailure): runner.framebuffer('job',10,17,[1023,700],[[1,1,20,20]])

    def test_foreground_occlusion_and_bounds_are_required(self):
        self.gui.GetForegroundWindow=lambda: 20
        with self.assertRaises(GuiFailure): self.capture()
        self.gui.GetForegroundWindow=lambda: 10
        self.gui.GetAncestor=lambda *_: 20
        with self.assertRaises(GuiFailure): self.capture()
        self.gui.GetAncestor=lambda *_: 10
        with self.assertRaises(GuiFailure): runner.framebuffer('job',10,17,[1024,700],[[1000,1,30,30]])

    def test_caption_candidate_requires_hit_owner_and_caption_semantics(self):
        self.gui.GetWindowRect=lambda _: (0,0,1024,730)
        self.gui.ClientToScreen=lambda _, point:(point[0],point[1]+30)
        with patch.object(runner,'caption_hit',return_value=True):
            self.assertEqual(runner.caption_point('job',10,17),(512,15))
        with patch.object(runner,'caption_hit',return_value=False):
            with self.assertRaises(GuiFailure):runner.caption_point('job',10,17)
        self.gui.GetAncestor=lambda *_:20
        with patch.object(runner,'caption_hit',return_value=True):
            with self.assertRaises(GuiFailure):runner.caption_point('job',10,17)
        self.gui.GetAncestor=lambda *_:10
        self.process.GetWindowThreadProcessId=lambda hwnd:(1,17 if hwnd==10 else 18)
        with patch.object(runner,'caption_hit',return_value=True):
            with self.assertRaises(GuiFailure):runner.caption_point('job',10,17)

    def test_ambiguous_window_is_not_accepted(self):
        self.gui.EnumWindows=lambda callback, arg: (callback(10,arg),callback(12,arg))
        with self.assertRaises(GuiFailure): runner.owned_window('job')


class DriverBoundary(unittest.TestCase):
    def test_both_driver_listeners_must_be_loopback_and_job_owned(self):
        rows={10:[(True,21)],11:[(True,22)]}
        self.assertTrue(runner.listeners_owned((10,11),{21,22},rows.get))
        for bad in ([],[(False,22)],[(True,99)],[(True,22),(True,23)]):
            rows[11]=bad
            self.assertFalse(runner.listeners_owned((10,11),{21,22},rows.get))

    def test_w3c_session_uses_original_application(self):
        driver=runner.WindowsDriver(); calls=[]
        def call(method,path,data=None):
            calls.append((method,path,data))
            return {'ready':True} if path == '/status' else {'sessionId':'fixture'}
        driver.call=call
        from pathlib import Path
        driver.start(Path('/tmp/fixture.exe'))
        self.assertEqual(driver.session,'/session/fixture')
        self.assertEqual(calls[1][2]['capabilities']['alwaysMatch']['tauri:options']['application'],str(Path('/tmp/fixture.exe').resolve()))

    def test_single_terminal_command_is_a_single_action(self):
        driver=runner.WindowsDriver();driver.session='/session/fixture'; calls=[]
        driver.call=lambda method,path,data=None: calls.append((method,path,data))
        driver.send_test_line()
        self.assertEqual(len(calls),1)
        actions=calls[0][2]['actions'][0]['actions']
        self.assertEqual(''.join(row['value'] for row in actions if row['type']=='keyDown'),'hp-check\ue007')

class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.current = False; self.cursor = (0,0); self.clicks = 0; self.request = 0
        self.gui=SimpleNamespace(ShowWindow=lambda *_:None,GetForegroundWindow=lambda:10 if self.current else 20,
                                 IsIconic=lambda _:False)
        self.api=SimpleNamespace(SetCursorPos=self.move,GetCursorPos=lambda:self.cursor)
        self.con=SimpleNamespace(SW_MAXIMIZE=3)
        for name,value in [('win32gui',self.gui),('win32api',self.api),('win32con',self.con),
            ('check_desktop',lambda:None),('owned_window',lambda _: (10,17)),
            ('caption_point',lambda *_:(300,10)),('mouse_capture_free',lambda:True),
            ('request_foreground',self.foreground_request),('click_once',self.click)]:
            patcher=patch.object(runner,name,value,create=True);patcher.start();self.addCleanup(patcher.stop)
        self.clock=0.0
        def now(): self.clock+=.6;return self.clock
        for patcher in (patch.object(runner.time,'monotonic',side_effect=now),patch.object(runner.time,'sleep')):
            patcher.start();self.addCleanup(patcher.stop)
    def move(self,point): self.cursor=point
    def foreground_request(self,_): self.request+=1;return False
    def click(self): self.clicks+=1;self.current=True;return True

    def test_standard_foreground_then_verified_caption_click_once(self):
        report={};runner.activate_owned_window('job',10,17,report)
        self.assertEqual(report['windowActivation'],'caption_click')
        self.assertEqual(self.request,1);self.assertEqual(self.clicks,1)

    def test_normal_activation_does_not_send_mouse(self):
        def request(_): self.current=True;return True
        with patch.object(runner,'request_foreground',request):
            report={};runner.activate_owned_window('job',10,17,report)
        self.assertEqual(report['windowActivation'],'set_foreground');self.assertEqual(self.clicks,0)

    def test_unowned_or_unverified_caption_never_clicked(self):
        with patch.object(runner,'caption_point',side_effect=GuiFailure('windows_tauri_caption_unavailable')):
            with self.assertRaises(GuiFailure):runner.activate_owned_window('job',10,17,{})
        self.assertEqual(self.clicks,0)
        with patch.object(runner,'mouse_capture_free',return_value=False):
            with self.assertRaises(GuiFailure):runner.activate_owned_window('job',10,17,{})
        self.assertEqual(self.clicks,0)

    def test_focus_guard_blocks_all_webdriver_user_input(self):
        driver=runner.WindowsDriver()
        driver.focus_guard=lambda: (_ for _ in ()).throw(GuiFailure('windows_tauri_window_not_foreground'))
        with patch.object(runner.WebDriver,'call',return_value={}) as transport:
            for suffix in ('/click','/clear','/value','/actions'):
                with self.assertRaises(GuiFailure):driver.call('POST','/session/a'+suffix,{})
            self.assertEqual(transport.call_count,0)
            driver.call('GET','/status');self.assertEqual(transport.call_count,1)


class CleanupDiagnostics(unittest.TestCase):
    @staticmethod
    def sharing_violation():
        error=PermissionError('secret path must never be emitted')
        error.winerror=32
        return error

    def test_primary_failure_survives_temporary_cleanup_failure(self):
        report={'failurePhase':'driver_listeners'}; original=GuiFailure('windows_tauri_driver_listener_unowned')
        with patch.object(runner.tempfile,'mkdtemp',return_value='/tmp/fake-owned'), \
             patch.object(runner.shutil,'rmtree',side_effect=self.sharing_violation()) as remove, \
             patch.object(runner.time,'sleep'):
            with self.assertRaises(GuiFailure) as failure:
                with runner.private_temporary_directory('/tmp',report): raise original
        self.assertIs(failure.exception,original);self.assertEqual(remove.call_count,5)
        self.assertEqual(report['primaryFailure'],{'phase':'driver_listeners','code':'windows_tauri_driver_listener_unowned'})
        self.assertEqual(report['temporaryCleanupFailure']['phase'],'temp_cleanup')
        self.assertNotIn('secret path',str(report))

    def test_sharing_violation_retries_only_cleanup_and_only_bounded(self):
        report={}; error=self.sharing_violation()
        with patch.object(runner.tempfile,'mkdtemp',return_value='/tmp/fake-owned'), \
             patch.object(runner.shutil,'rmtree',side_effect=[error,None]) as remove, \
             patch.object(runner.time,'sleep'):
            with runner.private_temporary_directory('/tmp',report): pass
        self.assertEqual(remove.call_count,2);self.assertEqual(report,{})
        failure=PermissionError('not public');failure.winerror=5
        with patch.object(runner.tempfile,'mkdtemp',return_value='/tmp/fake-owned'), \
             patch.object(runner.shutil,'rmtree',side_effect=failure) as remove, \
             patch.object(runner.time,'sleep'):
            with self.assertRaisesRegex(GuiFailure,'windows_tauri_temp_cleanup_unconfirmed'):
                with runner.private_temporary_directory('/tmp',report): pass
        self.assertEqual(remove.call_count,1)
        self.assertEqual(report['temporaryCleanupFailure']['phase'],'temp_cleanup')

    def test_diagnostics_only_emit_allowlisted_codes(self):
        report={};runner.record_failure(report,'driver_session',GuiFailure('secret password or path'))
        self.assertEqual(report['primaryFailure'],{'phase':'driver_session','code':'windows_tauri_unclassified'})
        report={};runner.record_failure(report,'driver_session',GuiFailure('secret_password'))
        self.assertEqual(report['primaryFailure']['code'],'windows_tauri_unclassified')


class ReceiptGate(unittest.TestCase):
    def fixture(self):
        import hashlib
        images={name:name.encode() for name in ('ordinary-terminal.png','ordinary-disconnect.png','ordinary-home.png')}
        report={'authentication':'password','windowActivation':'set_foreground','fingerprintReviewed':True,'returnedHome':True,'credentialFieldsCleared':True,'peer':{},
          'listener':{'ownedBeforeLaunch':True,'fixtureResourcesClosed':True,'absentFromWin32Table':True,'connectProbe':'refused'},
          'cleanup':{'ownedProcessJobEmpty':True,'peerListenerReleased':True,'fixturePasswordCleared':True,
                     'driverPortsReleased':True,'privateDirectoryRemoved':True}}
        for name,section in (('ordinary-terminal.png','terminal'),('ordinary-disconnect.png','disconnectOutcome'),('ordinary-home.png','homeOutcome')):
            report[section]={'capture':runner.CAPTURE,'imageSha256':hashlib.sha256(images[name]).hexdigest()}
        return report,images

    def test_missing_cleanup_or_changed_pixels_rejected(self):
        report,images=self.fixture()
        with patch.object(runner.linux,'session_evidence') as peer:
            runner.validate_success(report,images)
            peer.assert_called_once_with({},sent=True,closed=True)
            report['cleanup']['ownedProcessJobEmpty']=False
            with self.assertRaises(GuiFailure): runner.validate_success(report,images)
            report,images=self.fixture();images['ordinary-terminal.png']=b'changed'
            with self.assertRaises(GuiFailure): runner.validate_success(report,images)
            report,images=self.fixture();report['returnedHome']=False
            with self.assertRaises(GuiFailure): runner.validate_success(report,images)

if __name__ == '__main__': unittest.main()
