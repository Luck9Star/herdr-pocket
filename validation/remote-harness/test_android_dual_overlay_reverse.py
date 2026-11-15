"""Pure state-machine checks: no real adb, emulator or network mutation."""
import subprocess
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import android_dual_overlay_reverse as bridge


class FakeAdb:
    def __init__(self, initial=None, fail_at=None, uncertain=False):
        self.map=dict(initial or {});self.calls=[];self.fail_at=fail_at;self.uncertain=uncertain;self.adds=0
    def text(self,*args):
        assert args==('reverse','--list')
        return '\n'.join(f'{bridge.SERIAL} tcp:{device} tcp:{host}' for device,host in self.map.items())
    def adb(self,*args,**kwargs):
        self.calls.append(args)
        if args[:2]==('reverse','--no-rebind'):
            self.adds+=1; device=int(args[2][4:]);host=int(args[3][4:])
            if self.adds==self.fail_at:
                if self.uncertain:self.map[device]=host
                raise bridge.ReverseError('adb_operation_failed')
            if device in self.map: raise bridge.ReverseError('collision')
            self.map[device]=host
        elif args[:2]==('reverse','--remove'):
            del self.map[int(args[2][4:])]
        else: raise AssertionError(args)
        return b''


class ReverseTests(unittest.TestCase):
    def setUp(self):
        self.relay=SimpleNamespace(config={'control':10101,'derp':10102,'easytier':10103,'sshPorts':[10201,10202]},
                                   ports={'control':20101,'derp':20102,'easytier':20103})
    def run_with(self,fake):
        return patch.multiple(bridge,_adb=fake.adb,_text=fake.text)
    def test_only_single_owned_api35_avd_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            avd=Path(temp)/'owned-avd';avd.mkdir()
            env={'GITHUB_ACTIONS':'true','GITHUB_REF':'refs/heads/codex/acceptance/test',
                 'ANDROID_SERIAL':bridge.SERIAL,'RUNNER_TEMP':temp,'ANDROID_AVD_HOME':str(avd)}
            def text(*args):
                return {('shell','getprop','ro.kernel.qemu'):'1',('shell','getprop','ro.build.version.sdk'):'35',
                        ('shell','getprop','ro.product.cpu.abi'):'x86_64',('shell','am','get-current-user'):'0',
                        ('shell','getprop','sys.boot_completed'):'1'}[args]
            devices=subprocess.CompletedProcess([],0,b'List of devices attached\nemulator-5554\tdevice\n',b'')
            with patch.dict(os.environ,env),patch.object(bridge,'_text',side_effect=text),patch.object(bridge.subprocess,'run',return_value=devices):
                bridge.assert_owned_avd()
            devices.stdout += b'other-device\tdevice\n'
            with patch.dict(os.environ,env),patch.object(bridge.subprocess,'run',return_value=devices):
                with self.assertRaisesRegex(bridge.ReverseError,'owned_avd_required'):bridge.assert_owned_avd()
            with patch.dict(os.environ,{**env,'ANDROID_SERIAL':'real-phone'}),patch.object(bridge.subprocess,'run') as run:
                with self.assertRaisesRegex(bridge.ReverseError,'owned_avd_required'):bridge.assert_owned_avd()
                run.assert_not_called()

    def test_three_exact_mappings_and_preserve_existing(self):
        fake=FakeAdb({10999:20999})
        with self.run_with(fake):
            with bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None) as mappings:
                self.assertEqual(fake.map,{10999:20999,10101:20101,10102:20102,10103:20103})
            self.assertTrue(mappings.cleanup_confirmed)
        self.assertEqual(fake.map,{10999:20999})
        self.assertEqual([call[1] for call in fake.calls],['--no-rebind']*3+['--remove']*3)
    def test_collision_and_ssh_alias_never_write(self):
        fake=FakeAdb({10102:20999})
        with self.run_with(fake),self.assertRaisesRegex(bridge.ReverseError,'reverse_collision'):
            bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None).__enter__()
        self.assertEqual(fake.calls,[])
        self.relay.config['sshPorts']=[10101,10202]
        with self.run_with(FakeAdb()),self.assertRaisesRegex(bridge.ReverseError,'ssh_reverse_forbidden'):
            bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None).__enter__()
    def test_partial_failure_rolls_back_only_successful_mappings(self):
        fake=FakeAdb({10999:20999},fail_at=2)
        with self.run_with(fake),self.assertRaisesRegex(bridge.ReverseError,'adb_operation_failed'):
            bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None).__enter__()
        self.assertEqual(fake.map,{10999:20999})
        self.assertEqual(fake.calls[-1],('reverse','--remove','tcp:10101'))
    def test_ambiguous_failed_install_is_never_deleted_or_claimed_clean(self):
        fake=FakeAdb(fail_at=2,uncertain=True)
        with self.run_with(fake),self.assertRaisesRegex(bridge.ReverseError,'adb_operation_failed') as caught:
            bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None).__enter__()
        self.assertEqual(caught.exception.cleanup_code,'reverse_cleanup_unconfirmed')
        self.assertEqual(fake.map,{10102:20102})
        self.assertNotIn(('reverse','--remove','tcp:10102'),fake.calls)
    def test_changed_mapping_is_not_removed(self):
        fake=FakeAdb()
        with self.run_with(fake):
            mappings=bridge.OwnedReverseMappings(self.relay,_device_check=lambda:None).__enter__()
            fake.map[10101]=29999
            with self.assertRaisesRegex(bridge.ReverseError,'reverse_cleanup_unconfirmed'): mappings.close()
        self.assertEqual(fake.map,{10101:29999})
    def test_aosp_reverse_tag_is_accepted_without_exporting_ports(self):
        bridge.REVERSE_LIST_DIAGNOSTICS.clear()
        with patch.object(bridge,'_text',return_value='(reverse) tcp:10101 tcp:20101'):
            self.assertEqual(bridge._mapping_list(),{10101:20101})
        self.assertEqual(bridge.REVERSE_LIST_DIAGNOSTICS[-1],{'lineCount':1,'valid':True,'tags':['reverse']})
        self.assertNotIn('10101',str(bridge.REVERSE_LIST_DIAGNOSTICS))

    def test_malformed_reverse_list_fails_closed(self):
        for value in ('other tcp:1 tcp:2','host tcp:70000 tcp:2','host localabstract:x tcp:2','bad'):
            with self.subTest(value=value),patch.object(bridge,'_text',return_value=value):
                with self.assertRaises(bridge.ReverseError):bridge._mapping_list()

if __name__=='__main__':unittest.main()
