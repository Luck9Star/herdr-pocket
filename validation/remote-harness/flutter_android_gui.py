"""Production Flutter UI + native Android signer on one disposable cloud AVD.

The exchange is app-private public data via adb run-as, not a signer/frame API.
No HTTP service, system authorization files, real devices or raw logs in reports.
"""
import hashlib
import base64
import binascii
import json
import os
from pathlib import Path
import re
import subprocess
import time
from guarded_input import EvidenceError, mobile_receipts, mobile_tui_evidence, validate_mode
from mobile_blocked_result import checked_receipt, checked_targets

PACKAGE = 'dev.herdr.herdr_flutter_probe'
SERIAL = 'emulator-5554'
TARGET_FIELDS = {'schemaVersion', 'host', 'port', 'username', 'expectedHostKey',
                 'socketPath', 'herdrPath', 'session', 'paneId', 'reviewConfirmed'}
BOOL_FIELDS = ('productionMain', 'defaultHostCatalog', 'uninjectedNativeDeviceKeys',
    'profilePreviewShown', 'profileFieldsMatched', 'profileFingerprintMatched',
    'profileTargetUnreviewed', 'profileNoCreationIntent',
    'publicRequestShown', 'pendingRequestReopened', 'originalDeviceKeyRevalidated',
    'authorizationReviewed', 'pairedStateVisible', 'paneChosen', 'fullRendered',
    'deltaRendered', 'stoppedStale', 'observeMode', 'directModeDisabled',
    'draftModeDisabled', 'localIdentityDeleted')
STAGES = {'target_invalid', 'catalog_intent_failed', 'device_create_failed', 'handle_save_failed',
          'profile_enter', 'profile_preview', 'profile_fill',
          'signer_create', 'signer_public', 'signer_sign', 'signer_delete', 'signer_read_deleted',
          'public_key_failed', 'profile_save_failed', 'create_not_available', 'host_board',
          'board_search_text', 'board_search_state', 'board_search_count', 'board_search_history', 'board_search_clear',
          'board_search_clear_reset_visible', 'board_search_clear_reset_tap',
          'public_request', 'restore_pending', 'host_authorization',
          'target_finish_edit', 'target_review_ready', 'target_review_unchecked', 'target_create_unavailable',
          'target_create_ready', 'target_create_one_tap', 'target_request_wait',
          'response_review', 'ssh_and_dashboard', 'observe_frames', 'observe_canvas_select', 'observe_canvas_render', 'stop',
          'device_impact_enter', 'device_impact_scope', 'device_impact_reread', 'device_remove_blocked',
          'observe_canvas_open', 'observe_canvas_option', 'observe_canvas_verify',
          'host_task_summary_authoritative', 'host_task_summary_stale', 'local_font_diagnostic',
          'delete_local_identity', 'complete', 'guarded_direct', 'guarded_hidden_draft',
          'guarded_reconnect', 'guarded_draft_review', 'fixture_validation', 'viewport_pan', 'viewport_restored',
          'response_enter', 'response_preview', 'response_source_confirm', 'response_accept',
          'response_authorized', 'response_open_remote', 'response_remote_identity',
          'response_finish_edit', 'response_rejected', 'response_save_unconfirmed',
          'response_review_invalidated',
          'guarded_direct_available', 'guarded_direct_select', 'guarded_direct_focus',
          'guarded_direct_commit', 'guarded_direct_ack', 'guarded_direct_receipt',
          'guarded_clipboard_fixture', 'guarded_paste_cancel_review', 'guarded_paste_cancel_preserved',
          'guarded_paste_reopen_review', 'guarded_paste_local_append'}
STOCK_CASE = 'android-native-pairing-observe'
GUARDED_CASE = 'android-native-pairing-guarded-input'
CLIPBOARD_FIELDS = ('syntheticClipboardSet', 'pasteReviewCancelled', 'pasteCancelPreservedDraft',
                    'pasteReviewReopened', 'pasteAppendedLocally', 'pasteTargetVerified',
                    'pasteReceiptUnchanged', 'pasteKeptFixedSize')
CLIPBOARD_COUNTS = {'clipboardFixtureBytes': 3, 'pasteOriginalDraftBytes': 6, 'pasteMergedDraftBytes': 9}
CLIPBOARD_CHECKPOINTS = ('paste-cancel-preserved', 'paste-local-append')
KEYBOARD_CHECKPOINTS = ('keyboard-direct-shown', 'keyboard-direct-hidden',
    'keyboard-direct-reopened', 'keyboard-draft-shown', 'keyboard-draft-back-request',
    'keyboard-draft-back-hidden', 'keyboard-draft-back-reopened', 'keyboard-draft-hidden')
KEYBOARD_OBSERVE_CHECKPOINT = 'keyboard-observe-hidden'
TUI_CHECKPOINT = 'tui-start'
TUI_RESUME_STAGES = frozenset({'tui_find_board','tui_return_tab','tui_find_resume','tui_resume_full'})
BOARD_SEARCH_STAGES = frozenset({'board_search_text','board_search_state','board_search_count',
                                 'board_search_history','board_search_clear',
                                 'board_search_clear_reset_visible','board_search_clear_reset_tap'})
DEVICE_IMPACT_STAGES = frozenset({'device_impact_enter','device_impact_scope','device_impact_reread',
                                  'device_remove_blocked'})
STAGES.update(TUI_RESUME_STAGES)
STAGES.update({'blocked_history', 'blocked_list', 'blocked_target_open', 'blocked_identity_review',
               'blocked_ssh_review', 'blocked_observe', 'blocked_marker', 'blocked_return'})
STAGES.update({'tui_start','tui_resume_full','tui_initial','tui_select_next','tui_focus_detail',
    'tui_erase_character','tui_focus_list','tui_insert_row','tui_delete_row','tui_open_help',
    'tui_close_help','tui_refresh','tui_finish'})
STAGES.update(label.replace('-', '_') for label in (*KEYBOARD_CHECKPOINTS, KEYBOARD_OBSERVE_CHECKPOINT))
GUARDED_FIELDS = ('guardedInput', 'directInputAccepted', 'draftInputAccepted', 'hiddenTabStopped',
                  'hiddenTabManualRecovery', 'unsentDraftRestored', 'postStopInputDisabled') + CLIPBOARD_FIELDS
PUBLIC_LIMITS = {'request.json': 2048, 'result.json': 8192, 'signer.json': 1024, 'stage': 40,
                 'failure.json': 1024, 'checkpoint.json': 128}
SIGNER_CHALLENGE = b'herdr-pocket-android-signer-probe-v1'
REQUEST_FIELDS = {'version', 'type', 'request_id', 'account', 'host_key',
                  'issued_at', 'expires_at', 'device', 'public_key'}


class DeviceFailure(ValueError):
    """Only static phase codes may leave this module."""


# Static, non-sensitive codes only; unknown errors are deliberately collapsed.
_PRIMARY_FAILURE_CODES = frozenset({
    'android_blocked_target_evidence_invalid',
    'android_system_back_requires_visible_owned_ime',
    'android_tui_requires_guarded_input',
    'android_system_ime_evidence_unavailable',
    'android_system_ime_expected_state_invalid',
    'android_system_ime_fixture_configuration_failed',
    'android_system_ime_hide_unconfirmed',
    'android_system_ime_show_unconfirmed',
    'android_system_ime_target_mismatch',
    'flutter_android_adb_failed',
    'flutter_android_adb_output_limit',
    'flutter_android_adb_unavailable',
    'flutter_android_avd_api_or_user_mismatch',
    'flutter_android_ci_emulator_only',
    'flutter_android_cleanup_failed',
    'flutter_android_clipboard_checkpoint_order_invalid',
    'flutter_android_clipboard_checkpoints_missing',
    'flutter_android_clipboard_counter_invalid',
    'flutter_android_delta_not_observed',
    'flutter_android_existing_or_non_emulator_device',
    'flutter_android_failure_metadata_invalid',
    'flutter_android_font_measurement_invalid',
    'flutter_android_theme_measurement_invalid',
    'flutter_android_observer_canvas_unconfirmed',
    'flutter_android_forward_list_invalid',
    'flutter_android_gradle_changed',
    'flutter_android_guarded_byte_counts_invalid',
    'flutter_android_invalid_public_target',
    'flutter_android_keyboard_insets_mismatch',
    'flutter_android_not_isolated_fixture',
    'flutter_android_output_not_isolated',
    'flutter_android_package_already_present',
    'flutter_android_package_install_timeout',
    'flutter_android_preparation_missing',
    'flutter_android_preparation_not_verified',
    'flutter_android_production_source_proof_missing',
    'flutter_android_production_sources_changed',
    'flutter_android_public_exchange_oversize',
    'flutter_android_public_limit_invalid',
    'flutter_android_public_path_invalid',
    'flutter_android_response_invalid',
    'flutter_android_result_boolean_invalid',
    'flutter_android_result_case_invalid',
    'flutter_android_result_counter_invalid',
    'flutter_android_result_missing',
    'flutter_android_result_sequence_invalid',
    'flutter_android_reverse_already_present',
    'flutter_android_signer_verification_failed',
    'flutter_android_stock_input_unexpected',
    'flutter_android_test_exited',
    'flutter_android_test_exited_before_install',
    'flutter_android_tool_exit_timeout',
    'flutter_android_toolchain_mismatch',
    'flutter_android_toolchain_unavailable',
    'flutter_android_unknown_forward',
    'flutter_android_viewport_recovery_invalid',
    'flutter_android_tui_unexpected',
    'flutter_android_tui_target_mismatch',
    'flutter_android_tui_start_unconfirmed',
    'flutter_android_tui_start_already_attempted',
})

# The public-file readers derive their failure code from the fixed public file
# vocabulary. Every one of them is a reachable, non-sensitive stage code and
# must keep its own identity: collapsing them hides the device-side reason
# (for example a read that failed because the emulator disappeared).
_PUBLIC_FILE_KINDS = ('request', 'result', 'signer', 'stage', 'failure', 'checkpoint')
_PUBLIC_FILE_CODES = frozenset(
    'flutter_android_public_' + kind + suffix
    for kind in _PUBLIC_FILE_KINDS
    for suffix in ('_invalid', '_read_failed'))

def _safe_primary_failure(exc):
    if not isinstance(exc, DeviceFailure):
        return 'flutter_android_primary_failure'
    code = str(exc)
    if code in _PRIMARY_FAILURE_CODES or code in _PUBLIC_FILE_CODES:
        return code
    for prefix in ('flutter_android_test_exited_', 'flutter_android_phase_timeout_', 'flutter_android_test_failed_'):
        if code.startswith(prefix) and code[len(prefix):] in STAGES:
            return code
    return 'flutter_android_primary_failure'

class SystemImeFailure(DeviceFailure):
    """Classified counters/enums only; never retain a dumpsys string or package."""
    def __init__(self, code, diagnostic, retryable=False):
        super().__init__(code)
        self.diagnostic = dict(diagnostic)
        self.retryable = retryable

    def public_diagnostic(self):
        return public_ime_diagnostic(self.diagnostic)


def public_ime_diagnostic(value):
    """Emit only bounded counts and known classifications from either Android driver."""
    if not isinstance(value, dict):
        return {}
    safe = {}
    counters = ('formatVersion', 'serviceCount', 'displayCount', 'focusCount',
                'editorBlockCount', 'editorPackageCount', 'imeInsetsCount', 'attempts')
    for key in counters:
        count = value.get(key)
        if type(count) is int and 0 <= count <= 100:
            safe[key] = count
    for key in ('expectedVisible', 'timedOut'):
        if type(value.get(key)) is bool:
            safe[key] = value[key]
    owners = ('unavailable', 'ambiguous', 'none', 'owned', 'foreign')
    classifications = {
        'reason': ('invalid_dump_type_or_package', 'dump_limit', 'service_count',
                   'display_ambiguous_or_nondefault', 'focus_count', 'focus_null',
                   'focus_format_unproven', 'focus_foreign', 'ime_insets_ambiguous',
                   'service_window_flags_ambiguous', 'editor_block_count', 'editor_foreign',
                   'editor_owner_ambiguous', 'visible_editor_missing', 'owned_visible',
                   'owned_hidden', 'visibility_transition', 'no_sample', 'dump_pair_invalid'),
        'focusOwner': owners,
        'editorOwner': owners,
        'imeInsetsState': ('unavailable', 'conflicting', 'visible', 'hidden'),
        'visibility': ('unavailable', 'visible', 'hidden', 'transition'),
    }
    for key, allowed in classifications.items():
        if isinstance(value.get(key), str) and value[key] in allowed:
            safe[key] = value[key]
    return safe


def parse_system_ime(raw, window_dump, package):
    """Pinned Android 15 current service/editor block plus one focused app window.

    android-15.0.0_r1 InputMethodService.dump (4464-4505) nests EditorInfo.dump
    under mInputEditorInfo; EditorInfo.dump (1243) prints packageName on its own
    indented line. Other dump/history/hint fields are not current editor owners.
    DisplayContent.dump (3636,3669) emits one display and current focus per display.
    Raw dumps may contain editor text and never leave this function.
    """
    diagnostic = {'formatVersion': 1, 'reason': 'unavailable', 'serviceCount': 0,
        'displayCount': 0, 'focusCount': 0, 'focusOwner': 'unavailable',
        'editorBlockCount': 0, 'editorPackageCount': 0, 'editorOwner': 'unavailable',
        'imeInsetsCount': 0, 'imeInsetsState': 'unavailable', 'visibility': 'unavailable'}
    def fail(reason, *, target=False, retryable=False):
        diagnostic['reason'] = reason
        raise SystemImeFailure('android_system_ime_' + ('target_mismatch' if target else 'evidence_unavailable'), diagnostic, retryable)
    if package not in (PACKAGE, 'dev.herdrpocket.tauriprobe') or not isinstance(raw, str) or not isinstance(window_dump, str):
        fail('invalid_dump_type_or_package')
    if max(len(raw.encode('utf-8')), len(window_dump.encode('utf-8'))) > 1_048_576:
        fail('dump_limit')
    count = raw.count('Input method service state for ')
    diagnostic['serviceCount'] = min(count, 9)
    if count != 1:fail('service_count')
    _, service = raw.split('Input method service state for ', 1)
    displays = re.findall(r'^\s*Display: mDisplayId=(\d+)\b', window_dump, re.M)
    diagnostic['displayCount'] = min(len(displays), 9)
    if displays != ['0']:
        fail('display_ambiguous_or_nondefault', target=True)
    windows = re.findall(r'^\s*mCurrentFocus=([^\n]*)$', window_dump, re.M)
    diagnostic['focusCount'] = min(len(windows), 9)
    if len(windows) != 1:
        diagnostic['focusOwner'] = 'ambiguous' if windows else 'unavailable'
        fail('focus_count', target=True)
    focus = windows[0].strip()
    if focus == 'null':
        diagnostic['focusOwner'] = 'none'
        fail('focus_null', target=True, retryable=True)
    owner = re.fullmatch(r'Window\{[0-9a-fA-F]+ u(\d+) ([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+\}', focus)
    if not owner:
        fail('focus_format_unproven', target=True)
    diagnostic['focusOwner'] = 'owned' if owner.group(1) == '0' and owner.group(2) == package else 'foreign'
    if diagnostic['focusOwner'] != 'owned':fail('focus_foreign', target=True)
    inset_flags = re.findall(r'^\s*InsetsSource id=[0-9a-fA-F]+ type=ime\b[^\n]*\bvisible=(true|false)\b', window_dump, re.M)
    diagnostic['imeInsetsCount'] = min(len(inset_flags), 99)
    if not inset_flags or len(set(inset_flags)) != 1:
        diagnostic['imeInsetsState'] = 'conflicting' if inset_flags else 'unavailable'
        fail('ime_insets_ambiguous')
    inset_visible = inset_flags[0] == 'true'
    diagnostic['imeInsetsState'] = 'visible' if inset_visible else 'hidden'
    values = {}
    for key in ('mWindowVisible', 'mDecorViewVisible', 'mIsInputViewShown'):
        found = re.findall(r'\b' + key + r'=(true|false)\b', service)
        if len(found) != 1:fail('service_window_flags_ambiguous')
        values[key] = found[0] == 'true'
    # Bound current EditorInfo by its indentation. No scan of arbitrary packageName
    # text in hints, history, or an IME subclass's later diagnostic sections.
    headers = list(re.finditer(r'^(?P<indent>[ \t]*)mInputEditorInfo:[ \t]*(?P<null>null)?[ \t]*$', service, re.M))
    diagnostic['editorBlockCount'] = min(len(headers), 9)
    if len(headers) != 1:fail('editor_block_count')
    header = headers[0]
    if header.group('null'):
        editors = []
        diagnostic['editorOwner'] = 'none'
    else:
        depth = len(header.group('indent'))
        block = []
        for line in service[header.end():].splitlines():
            if not line.strip():continue
            if len(line) - len(line.lstrip(' \t')) <= depth:break
            block.append(line)
        editors = re.findall(r'^\s*packageName=([^\s]+)(?:\s|$)', '\n'.join(block), re.M)
        diagnostic['editorPackageCount'] = min(len(editors), 9)
        diagnostic['editorOwner'] = ('owned' if editors == [package] else 'foreign' if len(editors) == 1 else 'ambiguous' if editors else 'unavailable')
        if editors != [package]:fail('editor_foreign' if len(editors) == 1 else 'editor_owner_ambiguous', target=True)
    visible = all(values.values()) and inset_visible
    hidden = not values['mWindowVisible'] and not values['mDecorViewVisible'] and not inset_visible
    diagnostic['visibility'] = 'visible' if visible else 'hidden' if hidden else 'transition'
    if visible and editors != [package]:fail('visible_editor_missing', target=True, retryable=True)
    diagnostic['reason'] = 'owned_visible' if visible else 'owned_hidden' if hidden else 'visibility_transition'
    return {'source': 'Android15-IME-window-and-WindowInsets', 'ownedTarget': True,
        'visible': visible, 'hidden': hidden, 'windowVisible': values['mWindowVisible'],
        'decorVisible': values['mDecorViewVisible'], 'inputViewShown': values['mIsInputViewShown'],
        'windowInsetsImeVisible': inset_visible, 'diagnostic': diagnostic}


def wait_system_ime(read_dump, package, visible, timeout=12):
    if type(visible) is not bool:
        raise DeviceFailure('android_system_ime_expected_state_invalid')
    deadline = time.monotonic() + timeout
    stable = 0; attempts = 0; last = {'formatVersion': 1, 'reason': 'no_sample'}
    while time.monotonic() < deadline and attempts < 100:
        attempts += 1
        dumps = read_dump()
        if not isinstance(dumps, tuple) or len(dumps) != 2:
            raise SystemImeFailure('android_system_ime_evidence_unavailable', {'formatVersion': 1, 'reason': 'dump_pair_invalid', 'attempts': attempts})
        try:
            sample = parse_system_ime(*dumps, package)
        except SystemImeFailure as error:
            error.diagnostic.update(attempts=attempts, expectedVisible=visible)
            if not error.retryable:raise
            # A null focus/absent editor is never accepted. Only passive reads may
            # wait for an actual owned target; foreign/ambiguous owners abort now.
            stable = 0; last = error.diagnostic
        else:
            last = sample['diagnostic']
            stable = stable + 1 if sample['visible' if visible else 'hidden'] else 0
            if stable >= 2:
                return {**sample, 'stableSamples': stable, 'diagnostic': {**last, 'attempts': attempts, 'expectedVisible': visible}}
        time.sleep(0.15)
    raise SystemImeFailure('android_system_ime_' + ('show' if visible else 'hide') + '_unconfirmed',
                           {**last, 'attempts': attempts, 'expectedVisible': visible, 'timedOut': True})


def safe_tui_resume(value):
    """No terminal strings, host identity, path or arbitrary keys may leave the AVD."""
    integer_bounds = {'schemaVersion': (1,2), 'actionsCompleted': (0,3),
        'boardCount': (0,2), 'tabCount': (0,2), 'resumeCount': (0,2), 'viewCount': (0,2),
        'sequence': (-1,9_007_199_254_740_991), 'cols': (0,512), 'rows': (0,512),
        'bufferRows': (0,512), 'directCount': (0,2), 'rowsChecked': (0,24),
        'rowMatchMask': (0,0xffffff), 'firstMismatchRow': (-1,23), 'titleRowMask': (0,0xffffff)}
    booleans = {'terminalReplaced','sequencePresent','cursorKeysMode','directEnabled','tailRowsBlank'}
    invalid = 'flutter_android_failure_metadata_invalid'
    extra_bools = {'pageBusy','pagePaused','pageLive','evidenceFull'}
    enums = {'boardFreshness': {'none','stale','refreshing','fresh','unavailable'},
             'adapterPhase': {'unknown','idle','paused','resuming','snapshot','opening','awaiting_full','streaming','retiring','failed'},
             'adapterError': {'none','other','timeout','channel_cleanup_timeout','channel_identity','channel_capacity',
                 'watch_failed','watch_retry_exhausted','resume_target_changed','observe_ended',
                 'invalid_first_frame','invalid_frame','invalid_response','sequence_gap','cancelled'},
             'adapterRetireMiss': {'none','input','observation','snapshot','watch',
                 'input+observation','input+snapshot','input+watch','observation+snapshot','observation+watch',
                 'snapshot+watch','input+observation+snapshot','input+observation+watch','input+snapshot+watch',
                 'observation+snapshot+watch','input+observation+snapshot+watch'}}
    if not isinstance(value,dict) or type(value.get('schemaVersion')) is not int:
        raise DeviceFailure(invalid)
    if value['schemaVersion'] == 2:
        integer_bounds['pageCount'] = (0,2)
        booleans |= extra_bools
    elif value['schemaVersion'] != 1:
        raise DeviceFailure(invalid)
    if set(value) != set(integer_bounds) | booleans | (set(enums) if value['schemaVersion'] == 2 else set()):
        raise DeviceFailure(invalid)
    if value['schemaVersion'] == 2 and any(type(value[k]) is not str or value[k] not in allowed for k,allowed in enums.items()):
        raise DeviceFailure(invalid)
    for key,(low,high) in integer_bounds.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise DeviceFailure(invalid)
    if any(type(value[key]) is not bool for key in booleans):
        raise DeviceFailure(invalid)
    if value['schemaVersion'] == 2 and value['pageCount'] != 1 and (
            any(value[k] for k in extra_bools) or value['boardFreshness'] != 'none' or
            value['adapterPhase'] != 'unknown' or value['adapterError'] != 'none' or
            value['adapterRetireMiss'] != 'none'):
        raise DeviceFailure(invalid)
    if value['sequencePresent'] != (value['sequence'] >= 0) or value['rowsChecked'] not in (0,24):
        raise DeviceFailure(invalid)
    if value['viewCount'] != 1 and (value['terminalReplaced'] or value['cols'] or value['rows'] or
            value['bufferRows'] or value['cursorKeysMode'] or value['rowsChecked']):
        raise DeviceFailure(invalid)
    if value['directCount'] != 1 and value['directEnabled']:
        raise DeviceFailure(invalid)
    if value['rowsChecked'] == 0:
        if value['rowMatchMask'] or value['titleRowMask'] or value['firstMismatchRow'] != -1 or value['tailRowsBlank']:
            raise DeviceFailure(invalid)
    else:
        first = next((row for row in range(24) if not value['rowMatchMask'] & (1 << row)), -1)
        if ((value['cols'],value['rows'],value['bufferRows']) != (80,24,24) or
                value['firstMismatchRow'] != first or
                value['tailRowsBlank'] != ((value['rowMatchMask'] & 0xffff80) == 0xffff80) or
                bool(value['titleRowMask'] & 1) != bool(value['rowMatchMask'] & 1) or
                value['titleRowMask'] & value['rowMatchMask'] & 0xfffffe):
            raise DeviceFailure(invalid)
    return {key:value[key] for key in (*integer_bounds,*sorted(booleans),*(enums if value['schemaVersion'] == 2 else ()))}


def safe_board_search(value, failure=False):
    """Board search stays on the device: no host identity, terminal text or arbitrary keys may leave the AVD."""
    invalid = 'flutter_android_board_search_invalid'
    keys = ('textMatched','dualConditionCount','totalHosts','currentCount','historyCount','historyRows',
            'historyDistinguished','clearedKeptState','resetRestoredList','nativeCallsAdded')
    integer_bounds = {'textMatched': (0,64), 'dualConditionCount': (0,64), 'totalHosts': (0,64),
        'currentCount': (0,64), 'historyCount': (0,64), 'historyRows': (0,64), 'nativeCallsAdded': (0,64)}
    booleans = ('historyDistinguished','clearedKeptState','resetRestoredList')
    if not isinstance(value, dict) or set(value) != set(keys):
        raise DeviceFailure(invalid)
    for key,(low,high) in integer_bounds.items():
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise DeviceFailure(invalid)
    if any(type(value[key]) is not bool for key in booleans):
        raise DeviceFailure(invalid)
    # The text match and both conditions select the same saved host, the task state
    # survives clearing the text, the reset restores the list and no native call is added.
    if (value['nativeCallsAdded'] != 0 or value['historyDistinguished'] is not True or
            (not failure and (value['clearedKeptState'] is not True or value['resetRestoredList'] is not True)) or
            value['textMatched'] < 1 or value['dualConditionCount'] < 1 or value['historyRows'] < 1 or
            value['historyCount'] < 1 or value['dualConditionCount'] > value['totalHosts']):
        raise DeviceFailure(invalid)
    return {key: value[key] for key in keys}

def safe_device_impact(value):
    """The shared device review only reads: no identity, network join or write may be claimed."""
    invalid = 'flutter_android_device_impact_invalid'
    keys = ('statusClass','scopeListed','deviceActions','rereadCalls','reentered','writeCalls')
    if not isinstance(value, dict) or set(value) != set(keys):
        raise DeviceFailure(invalid)
    if value['statusClass'] not in ('unknown','catalog_blocked','pending'):
        raise DeviceFailure(invalid)
    if type(value['scopeListed']) is not bool or type(value['reentered']) is not bool:
        raise DeviceFailure(invalid)
    for key in ('deviceActions','rereadCalls','writeCalls'):
        if type(value[key]) is not int or not 0 <= value[key] <= 64:
            raise DeviceFailure(invalid)
    # The review may be read again and re-entered, but it must not write a device identity.
    if value['writeCalls'] != 0 or value['reentered'] is not True or value['rereadCalls'] < 1:
        raise DeviceFailure(invalid)
    if value['statusClass'] in ('unknown','catalog_blocked'):
        # Without a readable device state no identity operation may be offered.
        if value['deviceActions'] != 0 or value['scopeListed'] is not (value['statusClass'] == 'unknown'):
            raise DeviceFailure(invalid)
    return {key: value[key] for key in keys}


def safe_until_timeout(value):
    invalid = 'flutter_android_until_timeout_invalid'
    if not isinstance(value, dict):
        raise DeviceFailure(invalid)
    keys = {'key', 'buttonCount', 'imeBlockedNotice', 'inputStatus'}
    if not set(value) <= keys:
        raise DeviceFailure(invalid)
    key = value.get('key')
    if key is not None and (not isinstance(key, str) or len(key) > 64):
        raise DeviceFailure(invalid)
    for num in ('buttonCount', 'imeBlockedNotice'):
        if num in value and (type(value[num]) is not int or not 0 <= value[num] <= 16):
            raise DeviceFailure(invalid)
    status = value.get('inputStatus')
    if status is not None and (not isinstance(status, str) or len(status) > 200):
        raise DeviceFailure(invalid)
    return {k: value[k] for k in keys if k in value}


def safe_test_failure(value):
    kinds = {'TestFailure', 'StateError', 'TypeError', 'RemoteFailure', 'FormatException',
             'TimeoutException', 'FlutterError', 'other'}
    base = {'stage', 'errorClass', 'line'}
    evidence = {'tuiResume', 'boardSearch', 'deviceImpact', 'untilTimeout'}
    keys = set(value) if isinstance(value, dict) else set()
    if (not isinstance(value, dict) or not base <= keys or not keys <= base | evidence or
            not isinstance(value['stage'], str) or not isinstance(value['errorClass'], str) or
            value['stage'] not in STAGES or value['errorClass'] not in kinds or
            type(value['line']) is not int or not 0 <= value['line'] <= 10000):
        raise DeviceFailure('flutter_android_failure_metadata_invalid')
    clean = {key: value[key] for key in ('stage', 'errorClass', 'line')}
    if 'tuiResume' in value:
        if value['stage'] not in TUI_RESUME_STAGES:
            raise DeviceFailure('flutter_android_failure_metadata_invalid')
        clean['tuiResume'] = safe_tui_resume(value['tuiResume'])
    if 'boardSearch' in value:
        if value['stage'] not in BOARD_SEARCH_STAGES:
            raise DeviceFailure('flutter_android_failure_metadata_invalid')
        clean['boardSearch'] = safe_board_search(value['boardSearch'], failure=True)
    if 'deviceImpact' in value:
        if value['stage'] not in DEVICE_IMPACT_STAGES:
            raise DeviceFailure('flutter_android_failure_metadata_invalid')
        clean['deviceImpact'] = safe_device_impact(value['deviceImpact'])
    if 'untilTimeout' in value:
        clean['untilTimeout'] = safe_until_timeout(value['untilTimeout'])
    return clean

def public_host_fingerprint(key):
    """Compute OpenSSH SHA256 over a canonical Ed25519 public key blob."""
    try:
        if not isinstance(key, str) or not re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}', key):
            raise ValueError()
        encoded = key.split(' ')[1]
        blob = base64.b64decode(encoded, validate=True)
        if (base64.b64encode(blob).decode('ascii') != encoded or len(blob) != 51 or
                blob[:15] != b'\x00\x00\x00\x0bssh-ed25519' or blob[15:19] != b'\x00\x00\x00\x20'):
            raise ValueError()
        return 'SHA256:' + base64.b64encode(hashlib.sha256(blob).digest()).decode('ascii').rstrip('=')
    except (ValueError, binascii.Error):
        raise DeviceFailure('flutter_android_invalid_public_target') from None


def public_profile_json(config):
    """Make the scanner wire only from explicitly named public target fields."""
    if not isinstance(config, dict) or set(config) != TARGET_FIELDS:
        raise DeviceFailure('flutter_android_invalid_public_target')
    data = {'version': 1, 'type': 'herdr-connection-profile',
            'host': config['host'], 'port': config['port'], 'username': config['username'],
            'provider': 'direct', 'session': config['session'],
            'socketPath': config['socketPath'], 'herdrPath': config['herdrPath'],
            'expectedHostKey': config['expectedHostKey']}
    if (type(data['port']) is not int or
            any(not isinstance(data[key], str) for key in ('host', 'username', 'session',
                'socketPath', 'herdrPath', 'expectedHostKey'))):
        raise DeviceFailure('flutter_android_invalid_public_target')
    public_host_fingerprint(data['expectedHostKey'])
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    if not 1 <= len(raw.encode('utf-8')) <= 2048:
        raise DeviceFailure('flutter_android_invalid_public_target')
    return raw


def require_cloud(env, root, application, config):
    run_id, sha = env.get('GITHUB_RUN_ID', ''), env.get('GITHUB_SHA', '')
    if (env.get('GITHUB_ACTIONS') != 'true' or not re.fullmatch(r'\d+', run_id) or
            not env.get('GITHUB_REF', '').startswith('refs/heads/codex/') or
            not re.fullmatch(r'[0-9a-f]{40}', sha) or env.get('ANDROID_SERIAL') != SERIAL or
            not env.get('RUNNER_TEMP')):
        raise DeviceFailure('flutter_android_ci_emulator_only')
    root, app = Path(root).resolve(), Path(application).resolve()
    temporary = Path(env['RUNNER_TEMP']).resolve()
    if (root.parent != Path('/tmp').resolve() or not root.name.startswith('hp-mobile-' + run_id + '-') or
            app == temporary or not app.is_relative_to(temporary) or (app / '.git').exists()):
        raise DeviceFailure('flutter_android_not_isolated_fixture')
    if (not isinstance(config, dict) or set(config) != TARGET_FIELDS or config['host'] != '127.0.0.1' or
            type(config['port']) is not int or not 1024 <= config['port'] <= 65535 or
            config['session'] != 'pocket-probe' or config['schemaVersion'] != 1 or config['reviewConfirmed'] is not True or
            config['herdrPath'] != str(root / 'herdr') or
            config['socketPath'] != str(root / 'config/herdr/sessions/pocket-probe/herdr.sock')):
        raise DeviceFailure('flutter_android_invalid_public_target')
    marker = app / '.herdr-android-device-test.json'
    if marker.is_symlink() or not marker.is_file():
        raise DeviceFailure('flutter_android_preparation_missing')
    proof = json.loads(marker.read_text(encoding='utf-8'))
    if (proof.get('kind') != 'herdr-flutter-android-integration' or proof.get('sourceSHA') != sha or
            proof.get('lockVerified') is not True or proof.get('flutterVersion') != '3.47.9' or
            proof.get('flutterCommit') != 'c197ca5199e9ee5661e865596c9c07294dfab51c' or
            proof.get('integrationLockSha256') != hashlib.sha256((app / 'pubspec.lock').read_bytes()).hexdigest() or
            proof.get('integrationTestSha256') != hashlib.sha256((app / 'integration_test/android_pairing_observe_test.dart').read_bytes()).hexdigest()):
        raise DeviceFailure('flutter_android_preparation_not_verified')
    sources = proof.get('productionDartSources')
    channels = proof.get('productionAndroidChannels')
    expected_channels = {'MainActivity.kt', 'PairScanChannel.kt', 'HostCatalogFile.kt', 'InputJournalFile.kt',
                         'ConfigDocumentChannel.kt'}
    if (not isinstance(sources, dict) or not {'lib/main.dart', 'lib/device_keys.dart', 'lib/host_catalog.dart',
            'lib/pairing_page.dart', 'lib/remote_adapter.dart'}.issubset(sources) or
            not isinstance(channels, dict) or len(channels) != len(expected_channels) or
            {Path(path).name for path in channels} != expected_channels):
        raise DeviceFailure('flutter_android_production_source_proof_missing')
    for name, expected in {**sources, **channels}.items():
        if (not isinstance(name, str) or '..' in Path(name).parts or Path(name).is_absolute() or
                not (app / name).resolve().is_relative_to(app) or (app / name).is_symlink() or
                not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected) or
                hashlib.sha256((app / name).read_bytes()).hexdigest() != expected):
            raise DeviceFailure('flutter_android_production_sources_changed')
    if hashlib.sha256((app / 'android/app/build.gradle.kts').read_bytes()).hexdigest() != proof.get('gradleSha256'):
        raise DeviceFailure('flutter_android_gradle_changed')
    return app


def theme_prompt_expectations():
    """Numeric expectations from the same checksum-locked shared input as both apps."""
    shared = Path(__file__).resolve().parents[1] / 'shared'
    try:
        raw = (shared / 'theme-prompt-samples-v1.json').read_bytes()
        locks = [line.split()[0] for line in (shared / 'SHA256SUMS').read_text().splitlines()
                 if line.split()[1:] == ['theme-prompt-samples-v1.json']]
        if len(raw) > 16384 or locks != [hashlib.sha256(raw).hexdigest()]:
            raise ValueError()
        fixture = json.loads(raw)
        if (set(fixture) != {'schemaVersion','id','columns','rows','samples'} or
                type(fixture['schemaVersion']) is not int or fixture['schemaVersion'] != 1 or
                fixture['id'] != 'theme-prompt-samples-v1' or
                type(fixture['columns']) is not int or fixture['columns'] != 40 or
                type(fixture['rows']) is not int or fixture['rows'] != 3 or
                not isinstance(fixture['samples'], list) or len(fixture['samples']) != 2):
            raise ValueError()
        expected = {}
        for sample in fixture['samples']:
            if (not isinstance(sample, dict) or
                    set(sample) != {'id','label','ansi','cursorColumn','cursorRow'} or
                    sample['id'] not in ('powerlevel10k','oh-my-posh') or sample['id'] in expected or
                    type(sample['cursorColumn']) is not int or not 0 <= sample['cursorColumn'] < fixture['columns'] or
                    type(sample['cursorRow']) is not int or not 0 <= sample['cursorRow'] < fixture['rows']):
                raise ValueError()
            expected[sample['id']] = {key: fixture[key] for key in ('columns','rows')}
            expected[sample['id']].update({key:sample[key] for key in ('cursorColumn','cursorRow')})
        return expected
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        raise DeviceFailure('flutter_android_theme_measurement_invalid') from None


def safe_theme_prompt_cursors(value):
    expected = theme_prompt_expectations()
    if not isinstance(value, dict) or set(value) != set(expected):
        raise DeviceFailure('flutter_android_theme_measurement_invalid')
    clean = {}
    for ident, wanted in expected.items():
        measured = value[ident]
        if (not isinstance(measured, dict) or set(measured) != set(wanted) or
                any(type(measured[key]) is not int or measured[key] != number
                    for key, number in wanted.items())):
            raise DeviceFailure('flutter_android_theme_measurement_invalid')
        clean[ident] = measured.copy()
    return clean


def safe_device_result(raw, guarded=False, tui=False):
    if tui and not guarded:
        raise DeviceFailure('android_tui_requires_guarded_input')
    case = GUARDED_CASE if guarded else STOCK_CASE
    if not isinstance(raw, dict) or raw.get('case') != case or raw.get('buildMode') != 'debug':
        raise DeviceFailure('flutter_android_result_case_invalid')
    clean = {'case': raw['case'], 'buildMode': 'debug'}
    for field in BOOL_FIELDS + (GUARDED_FIELDS if guarded else ()):
        if type(raw.get(field)) is not bool or raw[field] is not True:
            raise DeviceFailure('flutter_android_result_boolean_invalid')
        clean[field] = True
    for field in ('firstSequence', 'deltaSequence'):
        value = raw.get(field)
        if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
            raise DeviceFailure('flutter_android_result_sequence_invalid')
        clean[field] = value
    if clean['deltaSequence'] <= clean['firstSequence']:
        raise DeviceFailure('flutter_android_delta_not_observed')
    columns = raw.get('localFontMarkerColumns')
    if (not isinstance(columns, list) or len(columns) != 8 or
            any(type(col) is not int or not (col == 0 or 3 <= col <= 16) for col in columns)):
        raise DeviceFailure('flutter_android_font_measurement_invalid')
    clean['localFontMarkerColumns'] = columns.copy()
    clean['localThemePromptCursors'] = safe_theme_prompt_cursors(raw.get('localThemePromptCursors'))
    if not guarded:
        canvas = raw.get('observerCanvas')
        if (not isinstance(canvas, dict) or type(canvas.get('cols')) is not int or canvas['cols'] != 120 or
                type(canvas.get('rows')) is not int or canvas['rows'] != 40 or canvas.get('wideMarkerMatched') is not True or
                canvas.get('wideMarkerVisible') is not True or canvas.get('readingPositionRestored') is not True):
            raise DeviceFailure('flutter_android_observer_canvas_unconfirmed')
        clean['observerCanvas'] = {'cols':120, 'rows':40, 'wideMarkerMatched':True,
                                   'wideMarkerVisible':True, 'readingPositionRestored':True}
    for field, expected in (('profileCreationActionsBeforeReview', 0), ('identityCreationActions', 1), ('frameCountLowerBound', 2), ('deltaCountLowerBound', 1)):
        if type(raw.get(field)) is not int or raw[field] != expected:
            raise DeviceFailure('flutter_android_result_counter_invalid')
        clean[field] = expected
    if guarded:
        offsets = raw.get('restoredViewportLogicalPixels')
        if (not isinstance(offsets, list) or len(offsets) != 2 or
                any(type(value) is not int or not 11 <= value <= 4096 for value in offsets) or
                abs(offsets[1] - offsets[0]) > 1):
            raise DeviceFailure('flutter_android_viewport_recovery_invalid')
        clean['restoredViewportLogicalPixels'] = offsets.copy()
        for field, expected in CLIPBOARD_COUNTS.items():
            if type(raw.get(field)) is not int or raw[field] != expected:
                raise DeviceFailure('flutter_android_clipboard_counter_invalid')
            clean[field] = expected
        try:
            clean['inputReceipts'] = mobile_receipts(raw.get('inputReceipts'))
        except EvidenceError as exc:
            raise DeviceFailure(str(exc)) from None
        sizes = [receipt['acceptedBytes'] for receipt in clean['inputReceipts']]
        counts = raw.get('acceptedByteCounts')
        if counts != sizes or not all(type(count) is int for count in counts):
            raise DeviceFailure('flutter_android_guarded_byte_counts_invalid')
        clean['acceptedByteCounts'] = sizes
    elif raw.get('inputReceipts') or raw.get('guardedInput') or any(
            field in raw for field in (*CLIPBOARD_FIELDS, *CLIPBOARD_COUNTS, 'restoredViewportLogicalPixels')):
        raise DeviceFailure('flutter_android_stock_input_unexpected')
    if tui:
        try:
            clean['tui'] = mobile_tui_evidence(raw.get('tui'), clean['inputReceipts'])
        except EvidenceError as exc:
            raise DeviceFailure(str(exc)) from None
    elif 'tui' in raw:
        raise DeviceFailure('flutter_android_tui_unexpected')
    # The board search and the shared device review are optional: they are reported
    # only when the app completed that group of stages.
    if 'boardSearchEvidence' in raw:
        clean['boardSearchEvidence'] = safe_board_search(raw['boardSearchEvidence'])
    if 'deviceImpactEvidence' in raw:
        clean['deviceImpactEvidence'] = safe_device_impact(raw['deviceImpactEvidence'])
    return clean


def adb(*args, check=True, data=None, timeout=30):
    try:
        result = subprocess.run(['adb', '-s', SERIAL, *map(str, args)], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # A device that disappeared mid-run most often surfaces as a hung adb
        # call, not as a non-zero exit status. Classify that path too, so the
        # report still names the verb and the reason without leaking output.
        failure = DeviceFailure('flutter_android_adb_unavailable')
        failure.adb_diagnostic = {'command': _adb_command_class(args),
                                   'reason': 'timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'oserror',
                                   'timeoutSeconds': int(timeout)}
        raise failure from None
    if len(result.stdout) > 1_048_576 or len(result.stderr) > 1_048_576:
        raise DeviceFailure('flutter_android_adb_output_limit')
    if check and result.returncode:
        # Classify the failing call without ever leaving the device: only the
        # adb verb, the exit status and the output sizes may be published.
        failure = DeviceFailure('flutter_android_adb_failed')
        failure.adb_diagnostic = {'command': _adb_command_class(args),
                                   'exitCode': int(result.returncode),
                                   'stdoutBytes': len(result.stdout),
                                   'stderrBytes': len(result.stderr)}
        raise failure
    return result


def _adb_command_class(args):
    """A fixed vocabulary for the adb verb; never the argument values."""
    verbs = ('shell', 'push', 'pull', 'install', 'uninstall', 'forward', 'reverse',
             'devices', 'wait-for-device', 'exec-out', 'logcat', 'start-server', 'kill-server')
    for arg in args:
        name = str(arg)
        if name in verbs:
            return name
        if name.startswith('shell'):
            return 'shell'
    return 'other'


def text(*args, **kwargs):
    return adb(*args, **kwargs).stdout.decode('utf-8', errors='strict').strip()


def package_present():
    return 'package:' + PACKAGE in text('shell', 'pm', 'list', 'packages', PACKAGE).splitlines()


def checked_flutter_version():
    try:
        reply = subprocess.run(['flutter', '--version', '--machine'], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=30, check=False)
        if reply.returncode or len(reply.stdout) > 65536 or len(reply.stderr) > 65536:
            raise DeviceFailure('flutter_android_toolchain_unavailable')
        value = json.loads(reply.stdout.decode('utf-8'))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise DeviceFailure('flutter_android_toolchain_unavailable') from None
    expected = {'frameworkVersion': '3.47.9', 'frameworkRevision': 'c197ca5199e9ee5661e865596c9c07294dfab51c'}
    if not isinstance(value, dict) or any(value.get(name) != item for name, item in expected.items()):
        raise DeviceFailure('flutter_android_toolchain_mismatch')
    return expected


def forward_set():
    result = set()
    for line in text('forward', '--list').splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise DeviceFailure('flutter_android_forward_list_invalid')
        if fields[0] == SERIAL:
            result.add(tuple(fields))
    return result


def public_file_pending(reply, relative):
    # During Flutter's build/install the app does not exist yet; after launch
    # its atomic public file may not exist yet. Match only these exact paths
    # and known diagnostics, including legacy exec-out's status-zero stdout.
    pending = {
        ('run-as: unknown package: ' + PACKAGE).encode(),
        ('head: ' + relative + ': No such file or directory').encode(),
        ("head: '" + relative + "': No such file or directory").encode(),
        ('head: ' + relative + ': No such file or directory.').encode(),
    }
    lines = [line.strip() for line in (reply.stdout + b'\n' + reply.stderr).splitlines() if line.strip()]
    return bool(lines) and all(line in pending for line in lines)


def checked_public_payload(raw, name):
    kind = name.split('.')[0]
    invalid = 'flutter_android_public_' + kind + '_invalid'
    if not raw.strip():
        return None
    if name == 'stage':
        try:
            label = raw.decode('ascii')
        except UnicodeDecodeError:
            raise DeviceFailure(invalid) from None
        if label in STAGES:
            return raw
        if any(stage.startswith(label) for stage in STAGES):
            return None
        raise DeviceFailure(invalid)
    if not raw.lstrip().startswith(b'{'):
        raise DeviceFailure(invalid)

    def unique_fields(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise DeviceFailure(invalid)
            value[key] = item
        return value

    try:
        decoded = raw.decode('utf-8')
        value = json.loads(decoded, object_pairs_hook=unique_fields)
    except UnicodeDecodeError as error:
        if error.reason == 'unexpected end of data':
            return None
        raise DeviceFailure(invalid) from None
    except json.JSONDecodeError:
        # Nothing incomplete may reach the host approval boundary. The outer
        # phase deadline still bounds a persistently incomplete publication.
        return None
    except RecursionError:
        raise DeviceFailure(invalid) from None
    if name == 'request.json':
        if (not isinstance(value, dict) or set(value) != REQUEST_FIELDS or
                type(value['version']) is not int or value['version'] != 2 or
                value['type'] != 'pairing-public-key-request' or
                any(type(value[key]) is not int for key in ('issued_at', 'expires_at')) or
                any(not isinstance(value[key], str) or not value[key] for key in
                    REQUEST_FIELDS - {'version', 'issued_at', 'expires_at'})):
            raise DeviceFailure(invalid)
        # The production Host.review remains authoritative for public-key
        # parsing, TTL, request ID, account and host fingerprint validation.
    elif name == 'result.json':
        # Validate the wire shape here; _run separately binds it to the
        # explicitly selected stock/guarded case before accepting the result.
        safe_device_result(value, guarded=isinstance(value, dict) and value.get('case') == GUARDED_CASE,
                           tui=isinstance(value, dict) and 'tui' in value)
    elif name == 'signer.json':
        if (not isinstance(value, dict) or set(value) != {'publicKey', 'signature', 'deleteReturned', 'readRejected'} or
                not isinstance(value['publicKey'], str) or not isinstance(value['signature'], str) or
                value['deleteReturned'] is not True or value['readRejected'] is not True):
            raise DeviceFailure(invalid)
    elif name == 'failure.json':
        safe_test_failure(value)
    elif name == 'checkpoint.json':
        if not isinstance(value, dict) or value.get('checkpoint') not in (*CLIPBOARD_CHECKPOINTS, *KEYBOARD_CHECKPOINTS, KEYBOARD_OBSERVE_CHECKPOINT, TUI_CHECKPOINT):
            raise DeviceFailure(invalid)
        if value['checkpoint'] == TUI_CHECKPOINT:
            if (set(value) != {'checkpoint','terminalId'} or not isinstance(value['terminalId'],str) or
                    not re.fullmatch(r'term_[0-9a-f]{1,123}',value['terminalId'])):
                raise DeviceFailure(invalid)
            return raw
        keyboard = value['checkpoint'] not in CLIPBOARD_CHECKPOINTS
        if set(value) != ({'checkpoint', 'viewInsetBottom', 'editorFocused', 'modeReselected'} if keyboard else {'checkpoint'}):
            raise DeviceFailure(invalid)
        if keyboard and (type(value['viewInsetBottom']) is not int or not 0 <= value['viewInsetBottom'] <= 16384):
            raise DeviceFailure(invalid)
        if keyboard and any(type(value[name]) is not bool for name in ('editorFocused', 'modeReselected')):
            raise DeviceFailure(invalid)
    return raw


def read_public(relative, limit):
    if not re.fullmatch(r'cache/herdr-flutter-android-[0-9]+/(?:request\.json|result\.json|signer\.json|failure\.json|checkpoint\.json|stage)', relative):
        raise DeviceFailure('flutter_android_public_path_invalid')
    name = relative.rsplit('/', 1)[1]
    if type(limit) is not int or limit != PUBLIC_LIMITS[name]:
        raise DeviceFailure('flutter_android_public_limit_invalid')
    # shell v2 (without -x) carries remote exit status and separate stderr.
    # exec-out has neither guarantee and can present run-as/head errors as data.
    reply = adb('shell', '-T', 'run-as', PACKAGE, 'head', '-c', str(limit + 1), relative, check=False)
    if public_file_pending(reply, relative):
        return None
    if len(reply.stdout) > limit or len(reply.stderr) > limit:
        raise DeviceFailure('flutter_android_public_exchange_oversize')
    if reply.returncode or reply.stderr:
        raise DeviceFailure('flutter_android_public_' + name.split('.')[0] + '_read_failed')
    return checked_public_payload(reply.stdout, name)


def write_response(relative_directory, response):
    if (not re.fullmatch(r'cache/herdr-flutter-android-[0-9]+', relative_directory) or
            not isinstance(response, bytes) or not 1 <= len(response) <= 2048):
        raise DeviceFailure('flutter_android_response_invalid')
    # Disable PTY conversion; public JSON is stdin to tee, never interpolated
    # into executable text. tee's bounded echo stays in this private process.
    pending = relative_directory + '/response.new'
    adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=response)
    adb('shell', 'run-as', PACKAGE, 'mv', pending, relative_directory + '/response.json')


def failure_stage(relative_directory, fallback):
    phase = read_public(relative_directory + '/stage', 40)
    label = phase.decode('ascii', errors='ignore') if phase is not None else ''
    return fallback + '_' + label if label in STAGES else fallback


class ClipboardCheckpoints:
    """Host IME/receiver verification before acknowledging local-only actions.

    The default preserves the historical two-clipboard-checkpoint reader.
    New cloud runs explicitly require the additional system-keyboard evidence.
    """
    def __init__(self, relative_directory, approval, *, keyboard=False, guarded=True, ime_failure_output=None, tui=False, config=None):
        self.relative = relative_directory
        self.approval = approval
        self.completed = []
        self.expected = ((KEYBOARD_CHECKPOINTS + CLIPBOARD_CHECKPOINTS if guarded else
                          (KEYBOARD_OBSERVE_CHECKPOINT,)) if keyboard else CLIPBOARD_CHECKPOINTS)
        if tui and (not guarded or config is None):
            raise DeviceFailure('android_tui_requires_guarded_input')
        if tui:
            self.expected += (TUI_CHECKPOINT,)
        self.config = config
        self.tui_attempted = False
        self.keyboard_evidence = []
        self.ime_failure_output = ime_failure_output

    def system_ime(self, label, visible, *, after_system_back=False):
        try:
            return wait_system_ime(lambda: (text('shell', 'dumpsys', 'input_method'),
                text('shell', 'dumpsys', 'window', 'displays')), PACKAGE, visible)
        except SystemImeFailure as error:
            # Persist before unwinding the owned Flutter tool/app. The original
            # failure still propagates, including if evidence cannot be written.
            allowed_codes = {'android_system_ime_target_mismatch','android_system_ime_evidence_unavailable',
                             'android_system_ime_show_unconfirmed','android_system_ime_hide_unconfirmed'}
            report = {'schemaVersion':1,'adapter':'flutter-android','status':'failed',
                'checkpoint':label,'systemRead':'after_system_back' if after_system_back else 'requested_state',
                'systemBackSent':after_system_back,'expectedVisible':visible,
                'completedCheckpoints':self.completed.copy(),
                'errorCode':str(error) if str(error) in allowed_codes else 'android_system_ime_evidence_unavailable',
                'diagnostic':error.public_diagnostic()}
            payload = json.dumps(report,sort_keys=True,separators=(',',':'))+'\n'
            if self.ime_failure_output is not None and len(payload) <= 4096:
                try:
                    fd = os.open(self.ime_failure_output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'w',encoding='ascii') as stream:
                        stream.write(payload);stream.flush();os.fsync(stream.fileno())
                except OSError:
                    pass  # Never mask an IME failure or acknowledge its checkpoint.
            raise

    def poll(self):
        raw = read_public(self.relative + '/checkpoint.json', PUBLIC_LIMITS['checkpoint.json'])
        if raw is None:
            return
        value = json.loads(raw)
        label = value['checkpoint']
        if self.completed and label == self.completed[-1]:
            return  # The same atomic request may remain visible while Dart resumes.
        if len(self.completed) >= len(self.expected) or label != self.expected[len(self.completed)]:
            raise DeviceFailure('flutter_android_clipboard_checkpoint_order_invalid')
        system = None
        if label == TUI_CHECKPOINT:
            if self.tui_attempted:
                raise DeviceFailure('flutter_android_tui_start_already_attempted')
            # Mark before any host operation: a timeout or lost ACK never
            # authorizes a second launch, even if a caller polls again.
            self.tui_attempted = True
            from paired_gui import fixture_terminal_id
            terminal_id = fixture_terminal_id(self.config)
            if value.get('terminalId') != terminal_id:
                raise DeviceFailure('flutter_android_tui_target_mismatch')
            evidence = self.approval.start_tui(terminal_id=terminal_id)
            if evidence != {'ready':True,'sameTarget':True,'initialInputMatched':True}:
                raise DeviceFailure('flutter_android_tui_start_unconfirmed')
        elif label not in CLIPBOARD_CHECKPOINTS:
            visible = label.endswith(('-shown', '-reopened', '-request'))
            inset = value.get('viewInsetBottom')
            if type(inset) is not int or not 0 <= inset <= 16384 or (inset > 0) != visible:
                raise DeviceFailure('flutter_android_keyboard_insets_mismatch')
            system = self.system_ime(label, visible)
            system = {**system, 'checkpoint': label, 'viewInsetBottom': inset,
                'editorFocused': value['editorFocused'], 'modeReselected': value['modeReselected']}
            if label == 'keyboard-draft-back-request':
                if system.get('visible') is not True or system.get('ownedTarget') is not True:
                    raise DeviceFailure('android_system_back_requires_visible_owned_ime')
                # No repeated Back even if hiding/acknowledgement fails. The
                # first failure propagates into owned process/app cleanup.
                adb('shell', 'input', 'keyevent', 'KEYCODE_BACK')
                after = self.system_ime(label, False, after_system_back=True)
                system = {**system, 'systemBackSent': True, 'afterSystemBack': after}
        expected = b'' if label.startswith('keyboard-direct-') or label == KEYBOARD_OBSERVE_CHECKPOINT else b'k'
        if label != TUI_CHECKPOINT:
            self.approval.verify_ssh(expected)
        # Do not acknowledge verification failure, and never replay the check or
        # an unknown-result acknowledgement write. Cleanup owns the fresh app.
        response = json.dumps({'checkpoint': label}, separators=(',', ':')).encode('ascii')
        pending = self.relative + '/checkpoint-ack.new'
        adb('shell', '-T', 'run-as', PACKAGE, 'tee', pending, data=response)
        adb('shell', 'run-as', PACKAGE, 'mv', pending, self.relative + '/checkpoint-ack.json')
        self.completed.append(label)
        if system is not None:
            self.keyboard_evidence.append(system)

    def require_complete(self):
        if tuple(self.completed) != self.expected:
            raise DeviceFailure('flutter_android_clipboard_checkpoints_missing')


def wait_public(proc, relative_directory, name, limit, timeout, checkpoints=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Flutter may still be building/installing its disposable app. Never
        # run-as a package that has not appeared on this emulator yet.
        if not package_present():
            if proc.poll() is not None:
                raise DeviceFailure('flutter_android_test_exited_before_install')
            time.sleep(0.15)
            continue
        if checkpoints is not None:
            checkpoints.poll()
        result = read_public(relative_directory + '/' + name, limit)
        if result is not None:
            if checkpoints is not None:
                checkpoints.require_complete()
            return result
        if proc.poll() is not None:
            if package_present():
                raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_test_exited'))
            raise DeviceFailure('flutter_android_test_exited')
        time.sleep(0.15)
    if package_present():
        raise DeviceFailure(failure_stage(relative_directory, 'flutter_android_phase_timeout'))
    raise DeviceFailure('flutter_android_package_install_timeout')


def verify_signer(raw):
    # Public bytes are consumed only here; never persist them in the report.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.serialization import load_ssh_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        checked_public_payload(raw, 'signer.json')
        value = json.loads(raw)
        signature = base64.b64decode(value['signature'], validate=True)
        key = load_ssh_public_key(value['publicKey'].encode('ascii'))
        if not isinstance(key, Ed25519PublicKey) or len(signature) != 64:
            raise ValueError()
        key.verify(signature, SIGNER_CHALLENGE)
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error, InvalidSignature):
        raise DeviceFailure('flutter_android_signer_verification_failed') from None
    return {'stage': 'complete', 'signatureVerified': True, 'deleteReturned': True, 'readRejected': True}


def run_flutter_android(args, root, env, config, approval):
    # Import the existing process owner only in the real runner path. Guard and
    # evidence unit tests use the standard library and never touch adb/a host.
    from paired_gui import GuiFailure, owned_process
    try:
        return _run(args, Path(root), env, config, approval, owned_process)
    except DeviceFailure as failure:
        raise GuiFailure(str(failure)) from None


def _run(args, root, env, config, approval, owned_process):
    app = require_cloud(env, root, args.flutter_app, config)
    guarded = getattr(args, 'android_guarded_input', False)
    tui = getattr(args, 'android_tui', False)
    try:
        validate_mode('flutter-android', bool(args.input_fixture), guarded, tui)
    except EvidenceError as exc:
        raise DeviceFailure(str(exc)) from None
    output = Path(args.output).resolve()
    temporary = Path(env['RUNNER_TEMP']).resolve()
    if output == temporary or not output.is_relative_to(temporary) or not output.is_dir():
        raise DeviceFailure('flutter_android_output_not_isolated')
    devices = [line.split()[:2] for line in text('devices').splitlines()[1:] if line.strip()]
    if devices != [[SERIAL, 'device']]:
        raise DeviceFailure('flutter_android_existing_or_non_emulator_device')
    if (text('shell', 'getprop', 'ro.kernel.qemu') != '1' or
            text('shell', 'getprop', 'ro.build.version.sdk') != '35' or
            text('shell', 'am', 'get-current-user') != '0'):
        raise DeviceFailure('flutter_android_avd_api_or_user_mismatch')
    if package_present():
        raise DeviceFailure('flutter_android_package_already_present')
    # Only this already-verified, fresh, disposable AVD is changed. Hardware
    # keyboard emulation otherwise suppresses the real software IME window.
    adb('shell', 'settings', 'put', 'secure', 'show_ime_with_hard_keyboard', '1')
    if text('shell', 'settings', 'get', 'secure', 'show_ime_with_hard_keyboard') != '1':
        raise DeviceFailure('android_system_ime_fixture_configuration_failed')
    reverse = 'tcp:' + str(config['port'])
    if any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines()):
        raise DeviceFailure('flutter_android_reverse_already_present')
    toolchain = checked_flutter_version()
    before_forwards = forward_set()
    relative = 'cache/herdr-flutter-android-' + env['GITHUB_RUN_ID']
    defines = root / 'flutter-android-public-defines.json'
    targets = [] if guarded else checked_targets(approval.blocked_targets)
    defines.write_text(json.dumps({'HERDR_ANDROID_NATIVE_PAIRING': '1', 'HERDR_ANDROID_RUN_ID': env['GITHUB_RUN_ID'],
        'POCKET_GUARDED_INPUT': 'true' if guarded else 'false',
        'HERDR_ANDROID_GUARDED_TUI': 'true' if tui else 'false',
        'HERDR_ANDROID_API35_CLIPBOARD_FIXTURE': 'true' if guarded else 'false',
        'HERDR_ANDROID_API35_KEYBOARD_FIXTURE': 'true',
        'HERDR_ANDROID_TARGET_JSON': json.dumps(config, separators=(',', ':')),
        'HERDR_ANDROID_BLOCKED_TARGETS': json.dumps(targets, separators=(',', ':')),
        'HERDR_ANDROID_PROFILE_JSON': public_profile_json(config),
        'HERDR_ANDROID_HOST_FINGERPRINT': public_host_fingerprint(config['expectedHostKey']),
        'HERDR_ANDROID_PUBLIC_DIR': '/data/user/0/' + PACKAGE + '/' + relative}), encoding='utf-8')
    defines.chmod(0o600)
    wrapper_props = app / 'android/gradle/wrapper/gradle-wrapper.properties'
    if wrapper_props.exists():
        text_props = wrapper_props.read_text(encoding='utf-8')
        if 'networkTimeout=10000' in text_props:
            wrapper_props.write_text(text_props.replace('networkTimeout=10000', 'networkTimeout=120000'), encoding='utf-8')
        elif 'networkTimeout=' not in text_props:
            wrapper_props.write_text(text_props + '\nnetworkTimeout=120000\n', encoding='utf-8')
    command = ['flutter', 'test', '--no-pub', '--no-uninstall', '--reporter', 'expanded', '-d', SERIAL,
               '--dart-define-from-file=' + str(defines), 'integration_test/android_pairing_observe_test.dart']
    process = None
    reverse_added = False
    result = None
    signer_evidence = {'stage': 'not_completed', 'signatureVerified': False,
                       'deleteReturned': False, 'readRejected': False}
    cleanup = {'sourceSHA': env['GITHUB_SHA'], 'ownedPackageInitiallyAbsent': True,
               'ownedPackageAbsent': False, 'appProcessGone': False, 'reverseRemoved': False,
               'ownedForwardsRemoved': False, 'flutterToolStopped': False, 'rawLogsUploaded': False}
    primary_failure = None
    adb_diagnostic = None
    try:
        adb('reverse', reverse, reverse); reverse_added = True
        with owned_process(command, cwd=app, env=env, log=root / 'flutter-android-private.log') as process:
            raw_signer = wait_public(process, relative, 'signer.json', 1024, timeout=900)
            signer_evidence['stage'] = 'verification_failed'
            signer_evidence = verify_signer(raw_signer)
            request = wait_public(process, relative, 'request.json', 2048, timeout=900)
            response = approval.approve(request)
            write_response(relative, response)
            checkpoints = ClipboardCheckpoints(relative, approval, keyboard=True, guarded=guarded,
                ime_failure_output=output / 'flutter-android-system-ime-failure.json',tui=tui,config=config)
            raw = wait_public(process, relative, 'result.json', 8192, timeout=580 if tui else 400, checkpoints=checkpoints)
            if checkpoints is not None:
                checkpoints.require_complete()
            raw_result = json.loads(raw.decode('utf-8'))
            result = safe_device_result(raw_result, guarded=guarded,tui=tui)
            if guarded and 'blockedTargetEvidence' in raw_result:
                raise DeviceFailure('android_blocked_target_evidence_invalid')
            if not guarded:
                fresh_targets = approval.verify_blocked_targets()
                if fresh_targets != targets:
                    raise DeviceFailure('android_blocked_target_evidence_invalid')
                result['blockedTargetEvidence'] = checked_receipt(raw_result.get('blockedTargetEvidence'), fresh_targets)
            result['systemKeyboardEvidence'] = {'checkpoints': checkpoints.keyboard_evidence,
                'scope': 'owned API35 docked IME window and real view insets; automated commits are not IME touch/composition proof',
                'showWithHardwareKeyboard': True}
            if guarded:
                result['pasteOperationsNoExtraSshBytes'] = True
            try:
                code = process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                raise DeviceFailure('flutter_android_tool_exit_timeout') from None
            if code:
                raise DeviceFailure(failure_stage(relative, 'flutter_android_test_failed'))
    except Exception as error:
        primary_failure = _safe_primary_failure(error)
        adb_diagnostic = getattr(error, 'adb_diagnostic', None)
        raise
    finally:
        # Only fixed stage/class names and a bounded source line may leave the
        # device. Never copy exception text or the raw Flutter/SSH logs.
        failure = None
        try:
            raw_failure = read_public(relative + '/failure.json', PUBLIC_LIMITS['failure.json'])
            if raw_failure is not None:
                failure = safe_test_failure(json.loads(raw_failure))
        except (DeviceFailure, ValueError):
            pass
        report = {'sourceSHA': env['GITHUB_SHA'], 'failure': failure}
        if isinstance(adb_diagnostic, dict):
            report['adbDiagnostic'] = adb_diagnostic
        (output / 'flutter-android-test-failure.json').write_text(
            json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if signer_evidence['stage'] != 'complete':
            try:
                label = read_public(relative + '/stage', 40)
                if label is not None and label.decode('ascii') in {
                        'profile_enter', 'profile_preview', 'profile_fill',
          'signer_create', 'signer_public', 'signer_sign', 'signer_delete', 'signer_read_deleted'}:
                    signer_evidence['stage'] = label.decode('ascii')
            except DeviceFailure:
                pass
        (output / 'flutter-android-signer-probe.json').write_text(json.dumps(signer_evidence, indent=2) + '\n', encoding='utf-8')
        cleanup['flutterToolStopped'] = process is None or process.poll() is not None
        try:
            if package_present():
                adb('shell', 'am', 'force-stop', PACKAGE)
                cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
                adb('uninstall', PACKAGE, timeout=60)
            else:
                cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
            cleanup['ownedPackageAbsent'] = not package_present()
            cleanup['appProcessGone'] = not text('shell', 'pidof', PACKAGE, check=False)
        except DeviceFailure:
            pass
        try:
            for _, local, _ in forward_set() - before_forwards:
                if not re.fullmatch(r'tcp:[0-9]+', local):
                    raise DeviceFailure('flutter_android_unknown_forward')
                adb('forward', '--remove', local)
            cleanup['ownedForwardsRemoved'] = forward_set() == before_forwards
        except DeviceFailure:
            pass
        try:
            if reverse_added:
                adb('reverse', '--remove', reverse)
            cleanup['reverseRemoved'] = not any(reverse in line.split()[1:2] for line in text('reverse', '--list').splitlines())
        except DeviceFailure:
            pass
        defines.unlink(missing_ok=True)
        successful_cleanup = all(cleanup[field] is True for field in
            ('ownedPackageAbsent', 'appProcessGone', 'reverseRemoved', 'ownedForwardsRemoved', 'flutterToolStopped'))
        cleanup['status'] = 'passed' if successful_cleanup else 'failed'
        if not successful_cleanup and primary_failure is not None:
            cleanup['primaryFailure'] = primary_failure
        (output / 'flutter-android-device-cleanup.json').write_text(json.dumps(cleanup, indent=2) + '\n', encoding='utf-8')
        if not successful_cleanup:
            if primary_failure is not None:
                raise DeviceFailure(primary_failure) from None
            raise DeviceFailure('flutter_android_cleanup_failed')
    if result is None:
        raise DeviceFailure('flutter_android_result_missing')
    return {**result, 'paired': True, 'reopenedPendingRequest': True,
        'inputQueueAccepted': guarded and result['directInputAccepted'] and result['draftInputAccepted'],
        'keyStore': 'API35 emulator production AndroidKeyStore AES-wrapped seed; native software Ed25519 signing',
        'device': 'disposable API35 Android AVD', 'uiDriver': 'Flutter SDK integration_test public text/tap controls',
        'frameEvidence': 'displayed sequence advance on the same production Terminal object after initial full',
        'storageMocked': False, 'signerInjected': False, 'framesInjected': False,
        'flutterToolchain': toolchain, 'deviceApi': 35, 'deviceCleanup': cleanup}
