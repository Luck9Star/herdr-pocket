"""Synthetic replay of pinned API35 dump structure; no device or raw user dumps.

Structure source: AOSP android-15.0.0_r1 InputMethodService.dump,
EditorInfo.dump and DisplayContent.dump. This is not a sample from run 42374975205.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
import flutter_android_gui as shared

stub = types.ModuleType('paired_gui')
stub.GuiFailure = type('GuiFailure', (Exception,), {})
stub.wait_for = lambda check, code, **_: check() or (_ for _ in ()).throw(stub.GuiFailure(code))
previous = sys.modules.get('paired_gui')
sys.modules['paired_gui'] = stub
try:
    spec = importlib.util.spec_from_file_location('ime_android_gui', Path(__file__).with_name('android_gui.py'))
    android = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(android)
finally:
    if previous is None:sys.modules.pop('paired_gui', None)
    else:sys.modules['paired_gui'] = previous


def dumps(*, package=android.PACKAGE, visible=True, focus=None, editor=None):
    state = str(visible).lower()
    editor = f'\n    inputType=0x1 imeOptions=0x0\n    packageName={package} autofillId=null fieldId=0\n    hintText=PRIVATE packageName=other.app' if editor is None else editor
    method = ('Current Input Method Manager state:\n  mStartInputHistory: PRIVATE\n'
        'Input method service state for synthetic-ime:\n'
        f'  mWindowVisible={state} mDecorViewVisible={state}\n'
        f'  mInputEditorInfo:{editor}\n'
        f'  mShowInputRequested={state}\n  mIsInputViewShown={state}\n'
        '  subclass diagnostic: PRIVATE packageName=other.app\n')
    focus = f'Window{{abc u0 {package}/.MainActivity}}' if focus is None else focus
    windows = ('WINDOW MANAGER DISPLAY CONTENTS\n  Display: mDisplayId=0\n'
        f'    mCurrentFocus={focus}\n'
        f'    InsetsSource id=3 type=ime frame=[0,900][500,1000] visible={state} flags= sideHint=BOTTOM\n')
    return method, windows


class ImeReplayTests(unittest.TestCase):
    def test_only_current_editor_field_proves_ownership_for_both_apps(self):
        for package in (android.PACKAGE, shared.PACKAGE):
            result = shared.parse_system_ime(*dumps(package=package), package)
            self.assertTrue(result['visible'])
            self.assertEqual(result['diagnostic']['editorPackageCount'], 1)
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertNotIn(package, json.dumps(result))

    def test_foreign_or_unproven_targets_abort_without_retry(self):
        raw, window = dumps()
        cases = [
            (raw.replace('packageName='+android.PACKAGE, 'packageName=other.app'), window, 'editor_foreign'),
            (raw.replace('packageName='+android.PACKAGE, 'packageName='+android.PACKAGE+'-other'), window, 'editor_foreign'),
            (raw, window.replace('u0 ', 'u10 '), 'focus_foreign'),
            (raw, window.replace(android.PACKAGE, 'other.app'), 'focus_foreign'),
            (raw, window.replace('/.MainActivity', '/???'), 'focus_format_unproven'),
            (raw, window+window, 'display_ambiguous_or_nondefault'),
            (raw, window.replace('mDisplayId=0', 'mDisplayId=1'), 'display_ambiguous_or_nondefault'),
            (raw, window.replace('  Display: mDisplayId=0\n',''), 'display_ambiguous_or_nondefault'),
            (raw, window+'  mCurrentFocus=null\n', 'focus_count'),
            (raw.replace('  mShowInputRequested', '    packageName=other.app\n  mShowInputRequested'), window, 'editor_owner_ambiguous'),
        ]
        for method, display, reason in cases:
            with self.subTest(reason=reason):
                read = Mock(return_value=(method, display))
                with patch.object(shared.time, 'sleep') as sleep:
                    with self.assertRaises(shared.SystemImeFailure) as failure:
                        shared.wait_system_ime(read, android.PACKAGE, True)
                self.assertEqual(failure.exception.diagnostic['reason'], reason)
                self.assertFalse(failure.exception.retryable)
                self.assertEqual(read.call_count, 1); sleep.assert_not_called()

    def test_null_focus_waits_passively_and_resets_two_owned_samples(self):
        read = Mock(side_effect=[dumps(focus='null'), dumps(), dumps(focus='null'), dumps(), dumps()])
        with patch.object(shared.time, 'sleep'):
            result = shared.wait_system_ime(read, android.PACKAGE, True)
        self.assertEqual(read.call_count, 5)
        self.assertEqual(result['stableSamples'], 2)
        self.assertEqual(result['diagnostic']['attempts'], 5)

    def test_null_editor_is_never_visible_proof_and_timeout_retains_reason(self):
        for sample, reason in ((dumps(focus='null'), 'focus_null'), (dumps(editor=' null'), 'visible_editor_missing')):
            with patch.object(shared.time, 'monotonic', side_effect=[0, 0, 13]), patch.object(shared.time, 'sleep'):
                with self.assertRaisesRegex(shared.SystemImeFailure, '^android_system_ime_show_unconfirmed$') as failure:
                    shared.wait_system_ime(lambda: sample, android.PACKAGE, True)
            self.assertEqual(failure.exception.diagnostic['reason'], reason)
            self.assertTrue(failure.exception.diagnostic['timedOut'])

    def test_actual_visibility_transition_needs_two_stable_samples(self):
        method, window = dumps()
        transition = (method.replace('mDecorViewVisible=true', 'mDecorViewVisible=false'), window)
        read = Mock(side_effect=[transition, dumps(), dumps(visible=False), dumps(), dumps()])
        with patch.object(shared.time, 'sleep'):
            result = shared.wait_system_ime(read, android.PACKAGE, True)
        self.assertEqual(result['diagnostic']['attempts'], 5)

    def test_tauri_wrapper_preserves_only_classified_diagnostic(self):
        error = shared.SystemImeFailure('android_system_ime_target_mismatch', {'reason':'focus_foreign'})
        with patch.object(android, 'wait_system_ime', side_effect=error):
            with self.assertRaises(android.GuiFailure) as failure:android.system_keyboard(True)
        self.assertEqual(failure.exception.system_ime_diagnostic, {'reason':'focus_foreign'})


class ProgressTests(unittest.TestCase):
    def test_normal_stock_entry_failure_keeps_prior_evidence_and_cleanup(self):
        view=Mock()
        view.evaluate.side_effect=lambda expression: 'fresh' if 'dataset.dashboardPhase' in expression else (3 if 'Frames' in expression else True)
        view.read.side_effect=lambda selector,*_: {'#pair-request':'synthetic request',
            '#pair-status':'授权响应已审查','#remote-panes button':'p · synthetic-terminal'}[selector]
        approval=Mock();approval.approve.return_value=b'synthetic response'
        def adb(*parts,**_):
            return {('devices',):'List of devices attached\nemulator-5554\tdevice',
                ('shell','getprop','ro.kernel.qemu'):'1',('shell','getprop','ro.build.version.sdk'):'35',
                ('shell','am','get-current-user'):'0',('shell','pidof',android.PACKAGE):'42',
                ('shell','cat','/proc/net/unix'):'@webview_devtools_remote_42',
                ('shell','settings','get','secure','show_ime_with_hard_keyboard'):'1',
                ('forward','tcp:0','localabstract:webview_devtools_remote_42'):'12345'}.get(parts,'')
        def font(browser,receiver,rendered):
            self.assertIs(browser,view);self.assertIs(receiver,approval)
            self.assertEqual(rendered('full'),3);self.assertEqual(rendered('delta'),3)
            return {'rowCount':8,'markerPositionStatus':'verified'}
        failure=android.GuiFailure('android_system_ime_target_mismatch')
        failure.system_ime_diagnostic={'reason':'focus_foreign','focusOwner':'foreign','attempts':1}
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();output=base/'evidence';output.mkdir()
            apk=base/'synthetic.apk';apk.write_bytes(b'fixture')
            args=types.SimpleNamespace(android_guarded_input=False,input_fixture=None,tauri_app=apk,output=output)
            config={'host':'127.0.0.1','port':2222,'username':'synthetic','session':'synthetic',
                'herdrPath':'/fixture/herdr','socketPath':'/fixture/socket','expectedHostKey':'synthetic','paneId':'p'}
            with patch.dict(os.environ,{'RUNNER_TEMP':str(base),'GITHUB_ACTIONS':'true','ANDROID_SERIAL':android.SERIAL}), \
                    patch.object(android,'adb',side_effect=adb) as command, \
                    patch.object(android,'AndroidWebView',return_value=view), \
                    patch.object(android,'exercise_font_diagnostics',side_effect=font), \
                    patch.object(android,'system_keyboard',side_effect=failure):
                with self.assertRaisesRegex(android.GuiFailure,'^android_system_ime_target_mismatch$'):
                    android.run_android(args,None,None,config,approval)
            report=json.loads((output/'tauri-android-progress.json').read_text())
            self.assertEqual(report['stage'],'keyboard_observe_hidden')
            self.assertEqual(report['status'],'failed')
            self.assertEqual(report['errorCode'],'android_system_ime_target_mismatch')
            for key in ('authorizationReviewed','paneChosen','fullRendered','deltaRendered','fontDiagnosticsCompleted'):
                self.assertTrue(report['completed'][key])
            self.assertFalse(report['completed']['stoppedStale'])
            self.assertEqual(report['fullRenderAcknowledgements'],3)
            self.assertEqual(report['deltaRenderAcknowledgements'],3)
            self.assertEqual(report['inputReceiptCount'],0)
            self.assertEqual(set(report['cleanup'].values()),{'confirmed'})
            command.assert_any_call('uninstall',android.PACKAGE,timeout=60)
            command.assert_any_call('reverse','--remove','tcp:2222')
            view.close.assert_called_once();view.direct_key.assert_not_called();view.receipt.assert_not_called()

    def test_failure_retains_completed_stages_and_discards_unknown_content(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {'RUNNER_TEMP':temporary}):
            output=Path(temporary).resolve()/'evidence';output.mkdir()
            progress=android.AndroidProgress(types.SimpleNamespace(output=output))
            for stage in ('fullRendered','deltaRendered','fontDiagnosticsCompleted'):progress.mark(stage)
            progress.phase('keyboard_direct_reopened')
            failure=android.GuiFailure('android_system_ime_target_mismatch')
            failure.system_ime_diagnostic={'reason':'focus_foreign','focusOwner':'foreign','attempts':1,
                'rawDump':'PRIVATE','window':'PRIVATE','editorPackageCount':1000,'unknown':'PRIVATE'}
            progress.fail(failure)
            progress.data['cleanup']['application']='confirmed'
            progress.finish(False);progress.close()
            raw=(output/'tauri-android-progress.json').read_text()
            result=json.loads(raw)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['stage'],'keyboard_direct_reopened')
            self.assertTrue(all(result['completed'][key] for key in ('fullRendered','deltaRendered','fontDiagnosticsCompleted')))
            self.assertEqual(result['systemImeFailure'], {'reason':'focus_foreign','focusOwner':'foreign','attempts':1})
            self.assertNotIn('PRIVATE',raw);self.assertLess(len(raw),16384)
            self.assertEqual((output/'tauri-android-progress.json').stat().st_mode & 0o777,0o600)
            with self.assertRaises(android.GuiFailure):android.AndroidProgress(types.SimpleNamespace(output=output))
            self.assertEqual((output/'tauri-android-progress.json').read_text(),raw)

    def test_output_must_be_owned_runner_subdirectory(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as outside, patch.dict(os.environ, {'RUNNER_TEMP':temporary}):
            link=Path(temporary)/'linked';link.symlink_to(outside,target_is_directory=True)
            for output in (temporary,outside,link,Path(temporary)/'missing'):
                with self.subTest(output=output),self.assertRaises(android.GuiFailure):
                    android.AndroidProgress(types.SimpleNamespace(output=output))

    def test_malformed_or_unknown_diagnostic_never_echoes(self):
        for reason in ('PRIVATE',[],{},None):
            self.assertEqual(shared.public_ime_diagnostic({'reason':reason,'raw':'PRIVATE'}),{})
        progress=android.AndroidProgress(types.SimpleNamespace())
        progress.fail(android.GuiFailure('android_private_untrusted_value'))
        self.assertEqual(progress.data['errorCode'],'android_driver_failure')

    def test_keyboard_failure_preserves_exact_phase_without_back_or_input(self):
        progress=android.AndroidProgress(types.SimpleNamespace())
        browser=Mock();browser.read.return_value='synthetic-target'
        with patch.object(android,'system_keyboard',side_effect=android.GuiFailure('android_system_ime_target_mismatch')),patch.object(android,'adb') as adb:
            with self.assertRaises(android.GuiFailure):android.exercise_keyboard(browser,Mock(),'draft',progress)
        self.assertEqual(progress.data['stage'],'keyboard_draft_shown')
        self.assertEqual(progress.data['systemImeChecks'],[])
        adb.assert_not_called();browser.direct_key.assert_not_called()


if __name__ == '__main__':unittest.main()
