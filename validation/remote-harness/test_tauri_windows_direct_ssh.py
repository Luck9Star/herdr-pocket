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

    def test_ambiguous_window_is_not_accepted(self):
        self.gui.EnumWindows=lambda callback, arg: (callback(10,arg),callback(12,arg))
        with self.assertRaises(GuiFailure): runner.owned_window('job')


class DriverBoundary(unittest.TestCase):
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

class ReceiptGate(unittest.TestCase):
    def fixture(self):
        import hashlib
        images={name:name.encode() for name in ('ordinary-terminal.png','ordinary-disconnect.png','ordinary-home.png')}
        report={'fingerprintReviewed':True,'returnedHome':True,'credentialFieldsCleared':True,'peer':{},
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
