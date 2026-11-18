#!/usr/bin/env python3
"""Installed Tauri iOS app, native XCUITest UI, disposable loopback SSH only.

--project is the generated Apple directory (or its .xcodeproj); it is read only.
--app is a built, installable aarch64 Simulator.app, never an archive/device app.
Requires full Xcode, an iOS simulator runtime, xcodegen, paramiko, Pillow and
Tesseract/eng. GITHUB_SHA (or --source-sha) supplies the checked-out source SHA.
All driver sources, synthetic credentials, XCTest logs and results are private
temporary files. Only the fixed public manifest, safe system PNGs and unchanged
shared OCR criteria are written to --output. Nothing invokes git or cloud CI.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from terminal_screenshot_gate import ScreenshotGateError, verify_terminal_screenshot
from direct_ssh_fixture import DirectSshFixture

HERE = Path(__file__).resolve().parent
BUNDLE_ID = 'dev.herdrpocket.tauriprobe'
PNG_FILES = ('ordinary-terminal.png', 'key-change-review.png', 'key-change-terminal.png')
STAGES = ('ordinary_form', 'ordinary_probe', 'ordinary_password', 'ordinary_input',
          'ordinary_terminal', 'ordinary_disconnect_attempt', 'ordinary_disconnected',
          'key_change_form', 'key_change_probe_a', 'key_change_password_a',
          'key_change_review', 'key_change_cancelled', 'key_change_probe_b',
          'key_change_password_b', 'key_change_input', 'key_change_terminal',
          'key_change_disconnect_attempt', 'key_change_disconnected', 'complete')
NATIVE_PHASES = frozenset(prefix + '_' + phase for prefix in ('ordinary', 'key_change') for phase in (
    'launch', 'open_add', 'open_ssh', 'host', 'port', 'username', 'probe', 'fingerprint',
    'password', 'connect', 'terminal_focus', 'terminal_input', 'terminal_capture', 'disconnect',
    'review_capture', 'cancel', 'cancel_check', 'reprobe', 'new_fingerprint'))
GEOMETRY_PHASES = frozenset(
    prefix + '_' + phase for prefix in ('ordinary', 'key_change')
    for phase in ('host', 'port', 'username', 'probe', 'password')
) | {'key_change_reprobe'}
GEOMETRY_REASONS = frozenset((
    'window_invalid', 'screen_invalid', 'web_ancestor_invalid', 'viewport_empty',
    'field_invalid', 'field_outside', 'field_occluded', 'field_unhittable',
    'scroll_direction_unproven', 'scroll_surface_unhittable', 'queried_unhittable',
    'bound_unhittable', 'scroll_no_progress'))
MAX_GEOMETRY_REASONS_PER_CHECKPOINT = 24
NATIVE_FAILURES = frozenset((
    'native_tree_limit', 'native_expected_text_missing', 'native_control_missing',
    'native_control_not_visible', 'native_control_disabled', 'native_unexpected_existing_input',
    'native_port_control_ambiguous', 'native_input_keyboard_missing', 'native_input_value_invalid',
    'native_review_lock_invalid', 'native_review_value_invalid', 'native_old_fingerprint_stale',
    'native_secret_exposed', 'native_geometry_ambiguous', 'native_window_missing',
    'native_webview_ambiguous', 'native_visible_frame_invalid', 'native_form_visible_in_capture',
    'native_review_clipped', 'native_review_exits_invalid', 'native_target_clipped',
    'native_terminal_frame_invalid', 'native_screen_frame_invalid', 'native_capture_geometry_changed',
    'native_app_launch_failed', 'native_credentials_visible_after_connect',
    'native_terminal_keyboard_missing', 'native_cancel_lost_old_trust',
    'native_cancel_accepted_new_trust', 'native_cancel_credentials_live', 'native_cancel_submit_live',
    'native_reprobe_old_key_stale', 'native_reprobe_secret_stale',
    'native_home_add_missing', 'native_home_not_foreground', 'native_home_alert_present',
    'native_home_webview_missing', 'native_home_known_loading_error', 'native_home_brand_missing',
    'native_home_add_role_mismatch', 'native_home_add_disabled', 'native_home_add_not_hittable_or_wrong_page',
    'native_home_add_did_not_open_page', 'native_owner_ambiguous', 'native_target_control_missing',
    'native_home_identity_unproven', 'native_home_retry_unsafe', 'native_ssh_form_unproven',
    'native_home_navigation_failed', 'native_control_owner_unproven', 'native_scroll_owner_unproven',
    'native_form_control_unproven', 'native_form_control_changed', 'native_terminal_keyboard_visible',
    'native_terminal_header_unproven'))
HOME_MEMBERS = frozenset(('brand', 'headerAdd', 'emptyAdd', 'homeHeading', 'emptyHeading',
                         'zeroHosts', 'ordinaryShortcut', 'addHeading', 'sshOption'))
HOME_ERRORS = frozenset(('connectionError', 'dnsError', 'webProcessError', 'devURL',
                        'browserPreview', 'hostStorageError', 'loading'))
HOME_ALERT_MEMBERS = frozenset(('localNetwork', 'allow', 'deny', 'ok', 'automation'))
HOME_ROLES = frozenset(('button', 'staticText', 'webView', 'textField', 'secureTextField', 'other', 'otherNative'))
FORM_CONTROL_NAMES = frozenset(('host', 'port', 'user', 'probe'))
FORM_CONTROL_ROLES = frozenset(('textField', 'textView', 'inputWrapper', 'button', 'other', 'none'))
FORM_CONTROL_REASONS = frozenset(('matched', 'missing', 'ambiguous', 'wrongRole', 'ownerUnproven'))


def public_geometry_detail(value):
    """Fixed geometry and state only; never export accessibility text or values."""
    rectangles = {'viewport', 'usable', 'owner', 'query', 'bound'}
    flags = {'queryEnabled', 'boundEnabled', 'queryHittable', 'boundHittable', 'scrollAttempted'}
    require(isinstance(value, dict) and set(value) == rectangles | flags | {'scrollDirection'},
            'tauri_ios_native_diagnostic_invalid')
    for key in rectangles:
        rect = value[key]
        require(rect is None or (isinstance(rect, list) and len(rect) == 4
                and all(type(n) is int for n in rect)
                and all(-10000 <= n <= 10000 for n in rect[:2])
                and all(0 <= n <= 10000 for n in rect[2:])),
                'tauri_ios_native_diagnostic_invalid')
    require(all(type(value[key]) is bool for key in flags)
            and type(value['scrollDirection']) is str
            and value['scrollDirection'] in ('none', 'swipe_up', 'swipe_down')
            and (not value['scrollAttempted'] or value['scrollDirection'] != 'none'),
            'tauri_ios_native_diagnostic_invalid')
    return {key: (list(value[key]) if key in rectangles and value[key] is not None else value[key])
            for key in rectangles | flags | {'scrollDirection'}}


def public_capture_diagnostic(value, *, review=False):
    """Only fixed categories and bounded, text-free candidate geometry escape."""
    keys = {'anchor', 'matchCount', 'reason', 'candidates', 'truncated'}
    if review:
        keys.add('sample')
    require(isinstance(value, dict) and set(value) == keys, 'tauri_ios_capture_diagnostic_invalid')
    anchors = (('review_title', 'review_blocked', 'review_old_fingerprint', 'review_new_fingerprint',
                'review_target', 'review_recheck', 'review_cancel') if review else ('target', 'terminal', 'keyboard', 'header_brand', 'header_add', 'status_bar'))
    require((not review or (type(value['sample']) is str and value['sample'] in ('before', 'after')))
            and type(value['anchor']) is str and value['anchor'] in anchors
            and type(value['reason']) is str and value['reason'] in (
                'not_found', 'frame_invalid', 'owner_unproven', 'owner_ambiguous', 'viewport_invalid',
                'outside_safe_frame', 'geometry_ambiguous', 'keyboard_visible', 'layout_unstable')
            and type(value['matchCount']) is int and 0 <= value['matchCount'] <= 10000
            and type(value['truncated']) is bool and isinstance(value['candidates'], list)
            and len(value['candidates']) <= 8, 'tauri_ios_capture_diagnostic_invalid')
    candidates = []
    for candidate in value['candidates']:
        require(isinstance(candidate, dict) and set(candidate) == {'role', 'frame', 'ownerResolved', 'visible'}
                and type(candidate['role']) is str and candidate['role'] in HOME_ROLES
                and type(candidate['ownerResolved']) is bool and type(candidate['visible']) is bool,
                'tauri_ios_capture_diagnostic_invalid')
        frame = candidate['frame']
        require(frame is None or (isinstance(frame, list) and len(frame) == 4
                and all(type(n) is int for n in frame)
                and all(-10000 <= n <= 10000 for n in frame[:2])
                and all(0 <= n <= 10000 for n in frame[2:])), 'tauri_ios_capture_diagnostic_invalid')
        candidates.append({**candidate, 'frame': list(frame) if frame is not None else None})
    result = {'anchor': value['anchor'], 'matchCount': value['matchCount'], 'reason': value['reason'],
              'candidates': candidates, 'truncated': value['truncated']}
    if review:
        result['sample'] = value['sample']
    return result


def public_connect_diagnostic(value):
    statuses = ('unknown', 'idle', 'disconnected', 'connecting', 'connected', 'review_blocked',
                'review_required', 'authentication_failed', 'start_failed', 'connection_failed',
                'session_ended', 'ambiguous')
    require(isinstance(value, dict) and set(value) == {'attempt', 'before', 'after', 'statuses'}
            and type(value['attempt']) is str and value['attempt'] in ('ordinary', 'rotation_refused', 'rotation_approved')
            and isinstance(value['statuses'], list) and len(value['statuses']) <= 12
            and all(type(x) is str and x in statuses for x in value['statuses'])
            and len(value['statuses']) == len(set(value['statuses'])), 'tauri_ios_connect_diagnostic_invalid')
    result = {'attempt': value['attempt'], 'statuses': list(value['statuses'])}
    for key in ('before', 'after'):
        sample = value[key]
        require(isinstance(sample, dict) and set(sample) == {'status', 'keyboardVisible', 'submitFrame',
                                                              'submitEnabled', 'submitHittable'}
                and type(sample['status']) is str and sample['status'] in statuses
                and all(type(sample[k]) is bool for k in ('keyboardVisible', 'submitEnabled', 'submitHittable')),
                'tauri_ios_connect_diagnostic_invalid')
        frame = sample['submitFrame']
        require(frame is None or (isinstance(frame, list) and len(frame) == 4
                and all(type(n) is int for n in frame)
                and all(-10000 <= n <= 10000 for n in frame[:2])
                and all(0 <= n <= 10000 for n in frame[2:])), 'tauri_ios_connect_diagnostic_invalid')
        result[key] = {**sample, 'submitFrame': list(frame) if frame is not None else None}
    return result


def public_home_diagnostic(value):
    """Only fixed members, finite roles, bounded counts and booleans may escape."""
    counts = {'webViewCount', 'windowCount', 'appAlertCount', 'systemAlertCount',
              'inputCount', 'unknownVisibleTextCount'}
    booleans = {'appForeground', 'alertSnapshotFailed', 'knownEmptyHome'}
    keys = counts | booleans | {'members', 'knownErrors', 'alertMembers'}
    require(isinstance(value, dict) and set(value) == keys, 'tauri_ios_home_diagnostic_invalid')
    require(all(type(value[k]) is int and 0 <= value[k] <= 10000 for k in counts)
            and all(type(value[k]) is bool for k in booleans), 'tauri_ios_home_diagnostic_invalid')
    for key, members in (('knownErrors', HOME_ERRORS), ('alertMembers', HOME_ALERT_MEMBERS)):
        require(isinstance(value[key], dict) and set(value[key]) == members
                and all(type(v) is bool for v in value[key].values()), 'tauri_ios_home_diagnostic_invalid')
    require(isinstance(value['members'], dict) and set(value['members']) == HOME_MEMBERS,
            'tauri_ios_home_diagnostic_invalid')
    for member in value['members'].values():
        require(isinstance(member, dict) and set(member) == {'count', 'roles'}
                and type(member['count']) is int and 0 <= member['count'] <= 10000
                and isinstance(member['roles'], list) and len(member['roles']) <= len(HOME_ROLES)
                and all(type(role) is str and role in HOME_ROLES for role in member['roles']),
                'tauri_ios_home_diagnostic_invalid')
    return json.loads(json.dumps({k: value[k] for k in keys}))


def public_form_controls(value):
    """Fixed four control names, closed role/reason enums, bounded match counts
    and the owner/reason coupling. The closed key set is the privacy boundary:
    no label, identifier, live value, URL or path can travel in this structure.

    The accepted combinations are exactly the ones the native driver can
    produce (NativeControlPolicy.formVerdict / formSelection):
      missing       -> no identity found, role 'none', no match
      ambiguous     -> several candidates, role 'none', at least one match
      wrongRole     -> one identity that is not an editable target
      ownerUnproven -> the target was found but its window could not be proven
      matched       -> the target was found and its owner was proven
    Partial evidence is kept: a page that resolves three of four controls
    must not lose the three."""
    require(isinstance(value, dict) and set(value) == FORM_CONTROL_NAMES,
            'tauri_ios_navigation_diagnostic_invalid')
    for item in value.values():
        require(isinstance(item, dict) and set(item) == {'role', 'matches', 'owner', 'reason'},
                'tauri_ios_navigation_diagnostic_invalid')
        role, reason = item['role'], item['reason']
        # Enum members are checked as strings first: a list or dict must fail
        # with the fixed diagnostic code, never with a TypeError.
        require(type(role) is str and role in FORM_CONTROL_ROLES
                and type(reason) is str and reason in FORM_CONTROL_REASONS
                and type(item['matches']) is int and 0 <= item['matches'] <= 10000
                and type(item['owner']) is bool,
                'tauri_ios_navigation_diagnostic_invalid')
        # Only a matched control carries a proven owner.
        require(item['owner'] is (reason == 'matched'),
                'tauri_ios_navigation_diagnostic_invalid')
        if reason == 'missing':
            require(role == 'none' and item['matches'] == 0,
                    'tauri_ios_navigation_diagnostic_invalid')
        elif reason == 'ambiguous':
            require(role == 'none' and item['matches'] >= 1,
                    'tauri_ios_navigation_diagnostic_invalid')
        elif reason in ('matched', 'ownerUnproven'):
            # A found target always carries a concrete role; 'other' and 'none'
            # are only reported for identities that were not eligible.
            require(role in ('textField', 'textView', 'inputWrapper', 'button')
                    and item['matches'] >= 1,
                    'tauri_ios_navigation_diagnostic_invalid')
        else:
            require(role != 'none' and item['matches'] >= 1,
                    'tauri_ios_navigation_diagnostic_invalid')
    return json.loads(json.dumps(value))


def public_navigation_state(value):
    flags = {'appForeground', 'noAlerts', 'noKnownErrors', 'emptyHomeIdentity', 'formByStructure',
             'sshTitleSeen', 'addTitleSeen', 'credentialsEmpty'}
    counts = {'inputCount', 'windowCount', 'webViewCount'}
    base_keys = flags | counts | {'page'}
    require(isinstance(value, dict) and base_keys <= set(value)
            and set(value) <= base_keys | {'formOwnerResolved', 'formControls'}
            and value['page'] in ('emptyHome', 'addChoice', 'sshForm', 'unexpected')
            and all(type(value[k]) is bool for k in flags)
            and all(type(value[k]) is int and 0 <= value[k] <= 10000 for k in counts),
            'tauri_ios_navigation_diagnostic_invalid')
    if value['page'] == 'emptyHome':
        require(value['emptyHomeIdentity'] and value['inputCount'] == 0 and value['credentialsEmpty'],
                'tauri_ios_home_retry_unsafe')
    if value['page'] == 'sshForm':
        require(value['formByStructure'] and value.get('formOwnerResolved') is True,
                'tauri_ios_ssh_form_owner_unproven')
    if 'formOwnerResolved' in value:
        require(type(value['formOwnerResolved']) is bool
                and (value['page'] != 'sshForm' or value['formOwnerResolved']),
                'tauri_ios_ssh_form_owner_unproven')
    if 'formControls' in value:
        controls = public_form_controls(value['formControls'])
        if value['page'] == 'sshForm':
            # The proven form needs all four controls matched with an owner and
            # the exact role each control must carry: host and user on a real
            # editable control, port on an editable control or on the wrapper
            # that owns one, and the probe on a real button.
            require(value['formByStructure']
                    and all(item['reason'] == 'matched' and item['owner']
                            for item in controls.values())
                    and controls['host']['role'] in ('textField', 'textView')
                    and controls['user']['role'] in ('textField', 'textView')
                    and controls['port']['role'] in ('textField', 'textView', 'inputWrapper')
                    and controls['probe']['role'] == 'button',
                    'tauri_ios_ssh_form_owner_unproven')
        # Any other page keeps the partial result as it is: three resolved
        # controls and one failed identity, or four controls that each have an
        # owner but no common window, are exactly the evidence that explains
        # why the form was not proven.
        value = {**value, 'formControls': controls}
    return dict(value)


def public_navigation_geometry(value):
    flags = {'enabled', 'hittable', 'ownerResolved', 'centerVisible', 'fullyVisible'}
    frames = {'frame', 'visibleFrame', 'screenFrame'}
    require(isinstance(value, dict) and set(value) == flags | frames | {'role', 'statusBarFrames'}
            and value['role'] in HOME_ROLES and all(type(value[k]) is bool for k in flags),
            'tauri_ios_navigation_diagnostic_invalid')
    def rectangle(rect):
        return (isinstance(rect, list) and len(rect) == 4 and
                all(type(n) in (int, float) and math.isfinite(n) and abs(n) <= 20000 for n in rect)
                and rect[2] >= 0 and rect[3] >= 0)
    require(all(rectangle(value[k]) for k in frames) and isinstance(value['statusBarFrames'], list)
            and len(value['statusBarFrames']) <= 8 and all(rectangle(r) for r in value['statusBarFrames']),
            'tauri_ios_navigation_diagnostic_invalid')
    return json.loads(json.dumps(value))


class SingleCommandFixture(DirectSshFixture):
    """Observe real server recv bytes without retaining or changing their content.

    The wrapper instruments only the owned SSH server's accepted channel. The
    product's Rust/IPC/terminal are untouched; each read reaches the original
    Paramiko channel and the existing fixture protocol consumes those same bytes.
    A digest over all received chunks distinguishes extra leading newlines or
    repeated commands from exactly one marker line, even at equal byte counts.
    """
    def _handle(self, transport):
        expected = {hashlib.sha256((self.marker + ending).encode()).digest()
                    for ending in ('\r', '\n', '\r\n')}
        digest = hashlib.sha256()
        original_accept = transport.accept
        owner = self
        self._connection_record(transport, 'singleMarkerLineExact', False)

        class ObservedChannel:
            def __init__(self, channel):
                self.channel = channel

            def __getattr__(self, name):
                return getattr(self.channel, name)

            def recv(self, size):
                data = self.channel.recv(size)
                digest.update(data)
                owner._connection_record(transport, 'singleMarkerLineExact', digest.digest() in expected)
                return data

        def accept(timeout=None):
            channel = original_accept(timeout)
            return ObservedChannel(channel) if channel is not None else None

        transport.accept = accept
        try:
            super()._handle(transport)
        finally:
            transport.accept = original_accept


class Failure(RuntimeError):
    """Only fixed codes constructed by this module cross the public boundary."""


def require(condition, code):
    if not condition:
        raise Failure(code)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def command(args, *, log=None, timeout=180, cwd=None):
    try:
        result = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE if log is None else log,
                                stderr=subprocess.PIPE if log is None else subprocess.STDOUT,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise Failure('tauri_ios_command_unavailable_or_timeout') from None
    require(result.returncode == 0, 'tauri_ios_command_failed')
    return result.stdout if log is None else b''


def build_diagnostics(log_path, private, *, phase):
    """Reduce private diagnostics to fixed categories and owned file locations.

    Never return message text, unknown paths, source excerpts, serialized test
    configuration or an xcresult. Even a diagnostic that quotes a credential
    can contribute only a category, an allowlisted basename and numeric bounds.
    """
    owned = {str((Path(private) / relative).resolve()): Path(relative).name
             for relative in ('UITests/Driver.swift', 'Host/Host.swift')}
    records = []
    def category(message):
        lower = message.lower()
        if 'main actor' in lower or 'actor-isolated' in lower or 'actor isolated' in lower:
            return 'swift_actor_isolation'
        if 'throw' in lower and ('try' in lower or 'autoclosure' in lower):
            return 'swift_throwing_expression'
        if 'main' in lower and ('attribute' in lower or 'entry point' in lower or 'static' in lower):
            return 'swift_entry_point'
        if 'cannot find' in lower or 'no member' in lower or 'unavailable' in lower:
            return 'swift_name_lookup'
        if 'cannot convert' in lower or 'type of expression' in lower or 'ambiguous' in lower:
            return 'swift_type_mismatch'
        return 'swift_compile_error'
    def add(value):
        if value not in records and len(records) < 12:
            records.append(value)
    try:
        with Path(log_path).open('rb') as source:
            for raw in source:
                # A bounded line is inspected privately, never echoed or retained.
                line = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', raw[:8192].decode('utf-8', errors='replace')).strip()
                match = re.match(r'(.+\.swift):([0-9]{1,6}):(?:([0-9]{1,5}):)?\s*(?:fatal )?error:\s*(.*)', line)
                if match:
                    value = {'classification': category(match[4])}
                    path = Path(match[1])
                    resolved = str((path if path.is_absolute() else Path(private) / path).resolve())
                    if resolved in owned and 1 <= int(match[2]) <= 100000:
                        value.update(file=owned[resolved], line=int(match[2]))
                        if match[3] is not None and 1 <= int(match[3]) <= 10000:
                            value['column'] = int(match[3])
                    add(value)
                elif 'error:' in line.lower() or 'error' in line.lower() and phase == 'xcodegen_generate':
                    lower = line.lower()
                    if phase == 'xcodegen_generate':
                        code = 'xcodegen_invalid_spec'
                    elif 'destination' in lower:
                        code = 'xcode_destination_unavailable'
                    elif 'sdk' in lower:
                        code = 'xcode_sdk_unavailable'
                    elif 'scheme' in lower:
                        code = 'xcode_scheme_invalid'
                    elif 'sign' in lower or 'provision' in lower:
                        code = 'xcode_signing_error'
                    elif 'link' in lower or 'undefined symbol' in lower:
                        code = 'xcode_linker_error'
                    else:
                        code = 'xcode_build_error'
                    add({'classification': code})
    except OSError:
        pass
    return records or [{'classification': 'xcodegen_generation_failed' if phase == 'xcodegen_generate'
                        else 'xcode_build_failed'}]


def runtime_diagnostics(log_path, private):
    """Inspect a private XCTest log; export only fixed codes and owned locations."""
    owned = {str((Path(private) / relative).resolve()): Path(relative).name
             for relative in ('UITests/Driver.swift', 'Host/Host.swift')}
    records = []
    patterns = (
        ('xctest_ambiguous_match', r'multiple matching elements found|ambiguous match'),
        ('xctest_element_absent_or_query_unresolved',
         r'failed to get matching snapshots?:\s*no matches found|failed to resolve query|no matches found for'),
        ('xctest_timeout', r'timed out waiting|exceeded timeout|asynchronous wait failed'),
        ('xctest_native_assertion', r'\bxctassert\w*\b.*\bfailed\b|\bxctfail\b'),
        ('xctest_actor_isolation', r'incorrect actor executor assumption|main actor isolation violation'),
        ('xctest_process_failure', r'failed to launch (?:the )?app|lost connection to the test process|'
         r'early unexpected exit|test runner exited with (?:code|signal)'),
    )
    try:
        with Path(log_path).open('rb') as source:
            for raw in source:
                line = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', raw[:8192].decode('utf-8', errors='replace')).strip()
                # Ordinary application output is not evidence of an XCTest failure.
                match = re.match(r'(.+\.swift):([0-9]{1,6}):(?:[0-9]{1,5}:)?\s*error:\s*(.*)', line)
                failure = match[3] if match else line
                if match is None and not re.search(r'\berror:|\*\* TEST (?:EXECUTE )?FAILED \*\*|'
                                                   r'test runner exited with|early unexpected exit|'
                                                   r'lost connection to the test process|'
                                                   r'incorrect actor executor assumption', line, re.I):
                    continue
                for code, pattern in patterns:
                    if not re.search(pattern, failure, re.I):
                        continue
                    value = {'classification': code}
                    if match and 1 <= int(match[2]) <= 100000:
                        path = Path(match[1])
                        try:
                            resolved = str((path if path.is_absolute() else Path(private) / path).resolve())
                        except (OSError, ValueError):
                            resolved = None
                        if resolved in owned:
                            value.update(file=owned[resolved], line=int(match[2]))
                    if value not in records and len(records) < 12:
                        records.append(value)
                    break
    except OSError:
        pass
    return records or [{'classification': 'xctest_failed'}]


def build_driver(private, build, result, *, deadline=None):
    """Separate generator and compiler failures; both logs remain private."""
    phases = (
        ('xcodegen_generate', ['xcodegen', 'generate', '--spec', 'project.json'], 180,
         'tauri_ios_xcodegen_failed'),
        ('xctest_build', [*build, 'build-for-testing'], 600, 'tauri_ios_xctest_build_failed'))
    for phase, arguments, timeout, failure in phases:
        result['stage'] = phase
        path = Path(private) / (phase + '-private.log')
        try:
            with path.open('wb') as log:
                remaining = timeout if deadline is None else min(timeout, deadline - time.monotonic())
                require(remaining > 0, 'tauri_ios_batch_deadline')
                command(arguments, cwd=private, log=log, timeout=remaining)
        except Failure:
            result['buildDiagnostics'] = build_diagnostics(path, private, phase=phase)
            raise Failure(failure) from None


def toolchain_evidence():
    text = command(['xcodebuild', '-version'], timeout=30).decode('ascii', errors='replace')
    version = re.fullmatch(r'Xcode ([0-9]+(?:\.[0-9]+){0,2})\s+Build version ([A-Za-z0-9]{3,20})\s*', text)
    sdk = command(['xcodebuild', '-version', '-sdk', 'iphonesimulator', 'SDKVersion'], timeout=30).decode('ascii', errors='replace').strip()
    require(version is not None and re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,2}', sdk),
            'tauri_ios_toolchain_metadata_invalid')
    return {'xcodeVersion': version[1], 'xcodeBuild': version[2], 'simulatorSDKVersion': sdk}


def validate_inputs(project, app, source_sha):
    require(bool(re.fullmatch(r'[0-9a-fA-F]{40}', source_sha or '')), 'tauri_ios_source_sha_invalid')
    project, app = Path(project).resolve(), Path(app).resolve()
    projects = [project] if project.suffix == '.xcodeproj' else list(project.glob('*.xcodeproj'))
    require(len(projects) == 1 and (projects[0] / 'project.pbxproj').is_file(),
            'tauri_ios_generated_project_missing')
    require(app.is_dir() and app.suffix == '.app', 'tauri_ios_simulator_app_missing')
    try:
        info = plistlib.loads((app / 'Info.plist').read_bytes())
        executable = app / info['CFBundleExecutable']
        require(info.get('CFBundleIdentifier') == BUNDLE_ID, 'tauri_ios_bundle_identity_invalid')
        require(info.get('CFBundleSupportedPlatforms') == ['iPhoneSimulator']
                and executable.is_file(), 'tauri_ios_app_is_not_simulator')
    except (OSError, KeyError, ValueError, plistlib.InvalidFileException):
        raise Failure('tauri_ios_app_metadata_invalid') from None
    # Read-only provenance: bind the exact generated project and installed binary.
    return {'bundleIdentifier': BUNDLE_ID,
            'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'projectSha256': hashlib.sha256((projects[0] / 'project.pbxproj').read_bytes()).hexdigest()}


def select_simulator(runtimes, device_types):
    choices = [r for r in runtimes if r.get('isAvailable') is True
               and r.get('identifier', '').startswith('com.apple.CoreSimulator.SimRuntime.iOS-')]
    require(bool(choices), 'tauri_ios_runtime_missing')
    runtime = max(choices, key=lambda r: tuple(int(n) for n in r.get('version', '0').split('.')))
    phones = [d for d in device_types if 'iPhone' in d.get('name', '') and 'Pro Max' in d.get('name', '')]
    require(bool(phones), 'tauri_ios_device_type_missing')
    components = [int(n) for n in runtime.get('version', '0').split('.')]
    version = sum(n << shift for n, shift in zip((components + [0, 0])[:3], (16, 8, 0)))
    compatible = [d for d in phones if int(d.get('minRuntimeVersion', 0)) <= version
                  and int(d.get('maxRuntimeVersion', 0xFFFFFFFF)) >= version]
    require(bool(compatible), 'tauri_ios_compatible_device_missing')
    device = max(compatible, key=lambda d: tuple(int(n) for n in re.findall(r'\d+', d['name'])))
    return runtime['identifier'], device['identifier']


def simulator_evidence(runtime, device_type):
    require(re.fullmatch(r'com\.apple\.CoreSimulator\.SimRuntime\.iOS-[0-9]+(?:-[0-9]+){0,2}', runtime)
            and re.fullmatch(r'com\.apple\.CoreSimulator\.SimDeviceType\.iPhone-[A-Za-z0-9-]{1,64}', device_type),
            'tauri_ios_simulator_metadata_invalid')
    return {'deviceType': device_type, 'runtime': runtime}


def measured_bounds(payload, image_size):
    def numbers(name, length):
        value = payload.get(name)
        require(isinstance(value, list) and len(value) == length
                and all(type(n) in (float, int) and math.isfinite(n) for n in value),
                'tauri_ios_native_geometry_invalid')
        return value
    screen = numbers('screenSize', 2)
    require(all(n > 0 for n in screen), 'tauri_ios_native_geometry_invalid')
    sx, sy = image_size[0] / screen[0], image_size[1] / screen[1]
    require(1 <= sx <= 4 and abs(sx - sy) < .001, 'tauri_ios_native_scale_invalid')
    safe = numbers('safeFrame', 4)
    def inside(rect, outer):
        x, y, w, h = rect
        a, b, c, d = outer
        return w > 0 and h > 0 and x >= a and y >= b and x + w <= a + c and y + h <= b + d
    require(inside(safe, [0, 0, *screen]), 'tauri_ios_native_visible_frame_invalid')
    ownership = {}
    if 'nativeOwner' in payload:
        owner = payload['nativeOwner']
        require(isinstance(owner, dict) and set(owner) == {'windowFrame', 'webFrames', 'webWrapperCount', 'uniqueWebBoundsCount'}
                and isinstance(owner['webFrames'], list) and 1 <= len(owner['webFrames']) <= 16
                and type(owner['webWrapperCount']) is int and owner['webWrapperCount'] == len(owner['webFrames'])
                and type(owner['uniqueWebBoundsCount']) is int, 'tauri_ios_native_owner_invalid')
        frames = [owner['windowFrame'], *owner['webFrames']]
        require(all(isinstance(r, list) and len(r) == 4
                    and all(type(n) in (float, int) and math.isfinite(n) for n in r)
                    and inside(safe, r) for r in frames), 'tauri_ios_native_owner_invalid')
        require(owner['uniqueWebBoundsCount'] == len({tuple(r) for r in owner['webFrames']}),
                'tauri_ios_native_owner_invalid')
        ownership['nativeOwner'] = json.loads(json.dumps(owner))
    def pixels(rect):
        # Round inward: only actual, measured terminal pixels reach OCR.
        x, y, w, h = rect
        left, top = math.ceil(x * sx), math.ceil(y * sy)
        return [left, top, math.floor((x + w) * sx) - left, math.floor((y + h) * sy) - top]
    if 'reviewFrames' in payload:
        frames = payload['reviewFrames']
        require(isinstance(frames, list) and len(frames) == 7, 'tauri_ios_review_geometry_invalid')
        for frame in frames:
            require(isinstance(frame, list) and len(frame) == 4
                    and all(type(n) in (float, int) and math.isfinite(n) for n in frame)
                    and inside(frame, safe), 'tauri_ios_review_geometry_invalid')
        return {'reviewBounds': [pixels(f) for f in frames], 'nativeScale': sx, **ownership}
    header = payload.get('headerBounds')
    if header is not None:
        require(isinstance(header, dict) and set(header) == {'brandFrame', 'addFrame', 'statusBarFrames', 'sameOwner'}
                and header['sameOwner'] is True and isinstance(header['statusBarFrames'], list)
                and 1 <= len(header['statusBarFrames']) <= 4, 'tauri_ios_capture_header_invalid')
        frames = [header['brandFrame'], header['addFrame'], *header['statusBarFrames']]
        require(all(isinstance(f, list) and len(f) == 4 and
                    all(type(n) in (float, int) and math.isfinite(n) for n in f) and
                    inside(f, [0, 0, *screen]) for f in frames), 'tauri_ios_capture_header_invalid')
        brand, add, *bars = frames
        require(inside(brand, safe) and inside(add, safe) and
                len({tuple(f) for f in bars}) == len(bars) and
                all(bar[1] + bar[3] <= min(brand[1], add[1]) for bar in bars),
                'tauri_ios_capture_header_invalid')
        ownership['headerBounds'] = json.loads(json.dumps(header))
    terminal, target = numbers('terminalFrame', 4), numbers('targetFrame', 4)
    require(inside(terminal, safe) and inside(target, safe), 'tauri_ios_terminal_or_target_clipped')
    tx, ty, tw, th = terminal
    x, y, w, h = target
    require(tx + tw <= x or x + w <= tx or ty + th <= y or y + h <= ty,
            'tauri_ios_terminal_target_overlap')
    source = payload.get('boundSource', 'native_region')
    require(source in ('native_region', 'terminal_control_bounds'), 'tauri_ios_capture_bounds_source_invalid')
    if source == 'terminal_control_bounds':
        controls = payload.get('controlBounds')
        require(isinstance(controls, dict) and set(controls) == {'dismissFrame', 'helperFrames', 'sameOwner'}
                and controls['sameOwner'] is True and isinstance(controls['helperFrames'], list)
                and len(controls['helperFrames']) == 4, 'tauri_ios_capture_controls_invalid')
        frames = [controls['dismissFrame'], *controls['helperFrames']]
        require(all(isinstance(f, list) and len(f) == 4 and
                    all(type(n) in (float, int) and math.isfinite(n) for n in f) and inside(f, safe)
                    for f in frames), 'tauri_ios_capture_controls_invalid')
        dismiss, *helpers = frames
        require(all(a[0] + a[2] <= b[0] for a, b in zip(helpers, helpers[1:]))
                and max(f[1] for f in helpers) < min(f[1] + f[3] for f in helpers)
                and all(abs(f[1]-helpers[0][1]) <= 1 and abs(f[1]+f[3]-helpers[0][1]-helpers[0][3]) <= 1 for f in helpers)
                and dismiss[1] + dismiss[3] < min(f[1] for f in helpers), 'tauri_ios_capture_controls_invalid')
        expected = [safe[0], dismiss[1] + dismiss[3], safe[2],
                    min(f[1] for f in helpers) - dismiss[1] - dismiss[3]]
        require(all(abs(a-b) <= .01 for a,b in zip(terminal, expected)), 'tauri_ios_capture_controls_invalid')
    else:
        require('controlBounds' not in payload, 'tauri_ios_capture_controls_invalid')
    bounds = pixels(terminal)
    require(bounds[2] > 0 and bounds[3] > 0, 'tauri_ios_native_geometry_invalid')
    result = {'terminalBounds': bounds, 'targetBounds': pixels(target), 'nativeScale': sx, **ownership}
    if 'boundSource' in payload:
        result['boundSource'] = source
    if source == 'terminal_control_bounds':
        result['controlBounds'] = json.loads(json.dumps(controls))
    return result


def terminal_background_bounds(image, candidate, scale):
    """Select one bounded xterm background region from the original PNG or fail closed."""
    x, y, width, height = candidate
    require(width >= 100 * scale and height >= 40 * scale, 'tauri_ios_terminal_background_invalid')
    rgb = image.convert('RGB').crop((x, y, x + width, y + height))
    pixels = rgb.load()
    def background(pixel):
        return all(abs(a-b) <= 6 for a,b in zip(pixel, (11, 15, 23)))
    def runs(flags):
        found, start = [], None
        for i, yes in enumerate([*flags, False]):
            if yes and start is None: start = i
            elif not yes and start is not None:
                found.append((start, i)); start = None
        return found
    rows = [sum(background(pixels[col, row]) for col in range(width)) >= width * .45
            for row in range(height)]
    bands = [(a,b) for a,b in runs(rows) if b-a >= 35 * scale]
    require(len(bands) == 1, 'tauri_ios_terminal_background_invalid')
    top, bottom = bands[0]
    cols = [sum(background(pixels[col, row]) for row in range(top, bottom)) >= (bottom-top) * .75
            for col in range(width)]
    regions = [(a,b) for a,b in runs(cols) if b-a >= max(80 * scale, width * .4)]
    require(len(regions) == 1, 'tauri_ios_terminal_background_invalid')
    left, right = regions[0]
    # Background touching the broad control-derived band is not bounded visual proof.
    require(left > 0 and right < width and bottom < height, 'tauri_ios_terminal_background_invalid')
    if top == 0:
        top += math.ceil(scale)
    require(bottom > top, 'tauri_ios_terminal_background_invalid')
    return [x + left, y + top, right - left, bottom - top]


def failure_peer_snapshot(fixture):
    """Bounded observed fixture facts, without names, data, or exception text."""
    facts = fixture.snapshot()
    require(isinstance(facts, dict) and type(facts.get('connections')) is int
            and 0 <= facts['connections'] <= 10000 and type(facts.get('connectionsClosed')) is bool
            and isinstance(facts.get('connectionEvents'), list), 'tauri_ios_failure_peer_snapshot_invalid')
    counts = ('id', 'authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes',
              'handshakeMs', 'firstAuthMs', 'closedMs')
    flags = ('handshakeCompleted', 'authAccepted', 'markerReceived', 'sessionClosed', 'closed', 'singleMarkerLineExact')
    enums = {'hostKey': ('A', 'B'), 'phase': ('handshake', 'await_channel', 'await_shell', 'shell'),
             'closeReason': ('transport_closed', 'fixture_stopped', 'batch_deadline', 'peer_eof', 'socket_error',
                             'ssh_error', 'preauth_peer_reset', 'preauth_peer_abort', 'preauth_peer_broken_pipe',
                             'session_socket_error', 'authentication_socket_error'),
             'socketErrorKind': ('connection_reset', 'connection_aborted', 'broken_pipe', 'other')}
    events = []
    for event in facts['connectionEvents'][:16]:
        require(isinstance(event, dict), 'tauri_ios_failure_peer_snapshot_invalid')
        public = {}
        for key in counts:
            if type(event.get(key)) is int and 0 <= event[key] <= 1000000000:
                public[key] = event[key]
        for key in flags:
            if type(event.get(key)) is bool:
                public[key] = event[key]
        for key, allowed in enums.items():
            if type(event.get(key)) is str and event[key] in allowed:
                public[key] = event[key]
        events.append(public)
    return {'connections': facts['connections'], 'connectionsClosed': facts['connectionsClosed'],
            'events': events, 'truncated': len(facts['connectionEvents']) > 16}


def wait_peer(fixture, predicate, code, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        facts = fixture.snapshot()
        if predicate(facts):
            return facts
        time.sleep(.02)
    raise Failure(code)


def ordinary_evidence(fixture, *, closed):
    facts = fixture.snapshot()
    events = facts['connectionEvents']
    require(facts['connections'] == 2 and len(events) == 2, 'tauri_ios_ordinary_connection_count_invalid')
    probe, session = events
    counters = ('authAttempts', 'authSuccesses', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')
    require(probe['hostKey'] == 'A' and probe['closed'] is True
            and all(probe[k] == 0 for k in counters), 'tauri_ios_ordinary_probe_not_empty')
    require(session['hostKey'] == 'A' and session['authSuccesses'] == 1 and session['authAttempts'] == 1
            and session['ptyRequests'] == 1 and session['shellRequests'] == 1
            and session['markerReceived'] is True and session['outputBytes'] > 0
            and session.get('singleMarkerLineExact') is True
            and session['inputBytes'] in (len(fixture.marker) + 1, len(fixture.marker) + 2),
            'tauri_ios_ordinary_session_incomplete')
    require(session['sessionClosed'] is closed and session['closed'] is closed,
            'tauri_ios_ordinary_close_order_invalid')
    return facts


def rotation_session_evidence(fixture, *, closed):
    facts = fixture.snapshot()
    require(facts['connections'] == 4 and len(facts['connectionEvents']) == 4,
            'tauri_ios_rotation_connection_count_invalid')
    event = facts['connectionEvents'][-1]
    require(event['hostKey'] == 'B' and event['authAttempts'] == 1 and event['authSuccesses'] == 1
            and event['ptyRequests'] == 1 and event['shellRequests'] == 1
            and event['markerReceived'] is True and event['outputBytes'] > 0
            and event.get('singleMarkerLineExact') is True
            and event['inputBytes'] in (len(fixture.marker) + 1, len(fixture.marker) + 2),
            'tauri_ios_rotation_single_command_or_auth_invalid')
    require(event['closed'] is closed and event['sessionClosed'] is closed
            and facts['connectionsClosed'] is closed, 'tauri_ios_rotation_close_order_invalid')
    return facts


class Checkpoints:
    def __init__(self, ordinary, rotation, output, result):
        self.ordinary, self.rotation, self.output, self.result = ordinary, rotation, Path(output), result
        self.index, self.failure = 0, None
        self.disconnects = set()
        self.started_cases = set()
        self.secret = secrets.token_hex(32)

    def finalize_cases(self):
        for name in self.started_cases:
            case = self.result['cases'][name]
            if case.get('status') != 'passed':
                case['status'] = 'failed'

    def capture(self, stage, payload, fixture):
        review = stage == 'key_change_review'
        case = self.result['cases']['keyChange' if stage.startswith('key_change') else 'ordinary']
        require(payload.get('identityVerified') is True and payload.get('noCredentialsVisible') is True,
                'tauri_ios_capture_identity_unverified')
        require('nativeOwner' in payload, 'tauri_ios_native_owner_missing')
        if not review:
            require('headerBounds' in payload and payload['headerBounds'] is not None,
                    'tauri_ios_capture_header_invalid')
        try:
            from PIL import Image
            data = base64.b64decode(payload.get('pngBase64', ''), validate=True)
            require(data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) <= 8_000_000,
                    'tauri_ios_capture_png_invalid')
            with Image.open(io.BytesIO(data)) as image:
                require(image.format == 'PNG' and image.width * image.height <= 16_000_000,
                        'tauri_ios_capture_png_invalid')
                image.load()
                geometry = measured_bounds(payload, image.size)
                if geometry.get('boundSource') == 'terminal_control_bounds':
                    candidate = geometry['terminalBounds']
                    geometry['terminalBounds'] = terminal_background_bounds(image, candidate, geometry['nativeScale'])
                    geometry['candidateTerminalBounds'] = candidate
        except (ValueError, OSError):
            raise Failure('tauri_ios_capture_png_invalid') from None
        name = ('key-change-review.png' if review else
                'key-change-terminal.png' if stage.startswith('key_change') else 'ordinary-terminal.png')
        require(not (self.output / name).exists(), 'tauri_ios_capture_replay_rejected')
        (self.output / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        self.result['artifacts'][name] = digest
        reference = {'imageFile': name, 'imageSha256': digest, **geometry,
                     'targetVisible': True, 'expectedTarget': f'{fixture.username}@127.0.0.1:{fixture.port}',
                     'systemCapture': 'XCUIScreen.main', 'noCredentialsVisible': True}
        if review:
            reference['purpose'] = 'S10 design review after refusal and before cancellation; no terminal OCR'
            case['reviewScreenshot'] = reference
            return
        criteria_name = name.replace('.png', '-ocr.json')
        case['terminalScreenshot'] = reference
        try:
            criteria = verify_terminal_screenshot(data, expected_token=fixture.screen_token,
                                                  bounds=geometry['terminalBounds'])
        except ScreenshotGateError as error:
            if error.evidence:
                write_json(self.output / criteria_name, error.evidence)
                case['terminalScreenshot'].update(error.evidence)
                case['terminalScreenshot'].update(criteriaFile=criteria_name,
                    criteriaSha256=hashlib.sha256((self.output / criteria_name).read_bytes()).hexdigest())
            raise Failure('tauri_ios_terminal_ocr_failed') from None
        require(criteria['imageSha256'] == digest, 'tauri_ios_capture_hash_mismatch')
        # Preserve shared gate schema verbatim in its standalone criteria file.
        write_json(self.output / criteria_name, criteria)
        case['terminalScreenshot'].update(criteria)
        case['terminalScreenshot']['criteriaFile'] = criteria_name
        case['terminalScreenshot']['criteriaSha256'] = hashlib.sha256((self.output / criteria_name).read_bytes()).hexdigest()

    def accept(self, payload):
        stage = payload.get('stage')
        if stage in ('native_home', 'native_home_entry', 'native_navigation', 'native_navigation_arrival'):
            phase = payload.get('nativeCheckpoint')
            require(self.failure is None and phase in ('ordinary_open_add', 'key_change_open_add', 'ordinary_open_ssh', 'key_change_open_ssh'),
                    'tauri_ios_home_diagnostic_phase_invalid')
            key = 'ordinary' if phase.startswith('ordinary_') else 'keyChange'
            next_stage = 'ordinary_probe' if key == 'ordinary' else 'key_change_probe_a'
            require(self.index == STAGES.index(next_stage), 'tauri_ios_home_diagnostic_phase_invalid')
            fixture = self.ordinary if key == 'ordinary' else self.rotation
            require(fixture is None or fixture.snapshot()['connections'] == 0, 'tauri_ios_navigation_after_ssh')
            if stage == 'native_home':
                self.result.setdefault('homeDiagnostics', {})[key] = public_home_diagnostic(payload.get('home'))
            elif stage == 'native_navigation_arrival':
                current = public_navigation_state(payload.get('state'))
                geometry = public_navigation_geometry(payload.get('geometry'))
                trace = self.result.get('navigationTrace', {}).get(key, [])
                require(phase.endswith('_open_ssh') and payload.get('source') == 'currentFormObservation'
                        and payload.get('performed') is False and trace
                        and trace[-1]['performed'] and trace[-1]['after']['page'] in ('addChoice', 'sshForm')
                        and current['page'] == 'sshForm' and current.get('formOwnerResolved') is True
                        and current['appForeground'] and current['noAlerts'] and current['noKnownErrors']
                        and current['credentialsEmpty'] and current['windowCount'] >= 1
                        and geometry['ownerResolved'], 'tauri_ios_ssh_form_unproven')
                arrivals = self.result.setdefault('navigationArrivals', {})
                require(key not in arrivals, 'tauri_ios_navigation_replay_rejected')
                arrivals[key] = {'source': 'currentFormObservation', 'performed': False,
                                 'state': current, 'geometry': geometry}
            elif stage == 'native_navigation':
                members = ('headerAdd', 'emptyAdd', 'ordinaryShortcut', 'sshChoice')
                require(payload.get('member') in members and payload.get('selection') in
                        ('buttonRole', 'uniqueIdentifier', 'uniqueLabel') and payload.get('method') == 'elementCenter'
                        and type(payload.get('performed')) is bool and payload.get('outcome') in
                        ('blocked', 'noProgress', 'addChoice', 'sshForm', 'unexpected'),
                        'tauri_ios_navigation_diagnostic_invalid')
                before = public_navigation_state(payload.get('before'))
                after = public_navigation_state(payload.get('after'))
                geometry = public_navigation_geometry(payload.get('geometry'))
                require(type(payload.get('targetPresentAfter')) is bool
                        and type(payload.get('elapsedMs')) is int and 0 <= payload['elapsedMs'] <= 60000,
                        'tauri_ios_navigation_diagnostic_invalid')
                after_geometry = public_navigation_geometry(payload.get('afterGeometry')) if payload['targetPresentAfter'] else None
                require(payload['targetPresentAfter'] or payload.get('afterGeometry') is None,
                        'tauri_ios_navigation_diagnostic_invalid')
                require(before['appForeground'] and before['noAlerts'] and before['noKnownErrors']
                        and before['credentialsEmpty'] and before['windowCount'] >= 1,
                        'tauri_ios_home_retry_unsafe')
                trace = self.result.setdefault('navigationTrace', {}).setdefault(key, [])
                require(len(trace) < 4 and payload['member'] not in [r['member'] for r in trace],
                        'tauri_ios_navigation_replay_rejected')
                expected = 'addChoice' if payload['member'] == 'sshChoice' else 'emptyHome'
                require(before['page'] == expected, 'tauri_ios_home_retry_unsafe')
                if trace:
                    require(trace[-1]['after']['page'] == expected and
                            trace[-1]['geometry']['screenFrame'] == geometry['screenFrame'],
                            'tauri_ios_home_retry_unsafe')
                if payload['performed']:
                    require(all(geometry[k] for k in ('enabled', 'hittable', 'ownerResolved', 'centerVisible')),
                            'tauri_ios_navigation_unsafe_center')
                    x, y, w, h = geometry['frame']; a, b, c, d = geometry['visibleFrame']
                    require(w > 0 and h > 0 and a <= x + w / 2 <= a + c and b <= y + h / 2 <= b + d,
                            'tauri_ios_navigation_unsafe_center')
                else:
                    require(payload['outcome'] == 'blocked', 'tauri_ios_navigation_diagnostic_invalid')
                expected_outcome = {'emptyHome': 'noProgress', 'addChoice': 'addChoice',
                                    'sshForm': 'sshForm', 'unexpected': 'unexpected'}[after['page']]
                require(not payload['performed'] or payload['outcome'] == expected_outcome,
                        'tauri_ios_navigation_diagnostic_invalid')
                trace.append({'member': payload['member'], 'selection': payload['selection'],
                    'method': 'elementCenter', 'performed': payload['performed'], 'geometry': geometry,
                    'targetPresentAfter': payload['targetPresentAfter'], 'afterGeometry': after_geometry,
                    'elapsedMs': payload['elapsedMs'],
                    'before': before, 'after': after, 'outcome': payload['outcome']})
            else:
                require(payload.get('member') in ('headerAdd', 'emptyAdd', 'ordinaryShortcut')
                        and payload.get('selection') in ('buttonRole', 'uniqueIdentifier', 'uniqueLabel')
                        and payload.get('role') in HOME_ROLES and payload.get('enteredSSHForm') is True
                        and type(payload.get('enteredAddPage')) is bool
                        and payload.get('route') in ('viaAdd', 'directSSH'), 'tauri_ios_home_entry_invalid')
                trace = self.result.get('navigationTrace', {}).get(key, [])
                arrival = self.result.get('navigationArrivals', {}).get(key)
                final_state = arrival['state'] if arrival else (trace[-1]['after'] if trace else {})
                require(final_state.get('page') == 'sshForm' and
                        final_state['credentialsEmpty'] and final_state['formByStructure']
                        and final_state['appForeground'] and final_state['noAlerts']
                        and final_state['noKnownErrors'] and final_state['windowCount'] >= 1,
                        'tauri_ios_ssh_form_unproven')
                require((payload['route'] == 'viaAdd') == payload['enteredAddPage'], 'tauri_ios_home_entry_invalid')
                self.result.setdefault('homeEntry', {})[key] = {k: payload[k] for k in
                    ('member', 'selection', 'role', 'enteredAddPage', 'enteredSSHForm', 'route')}
            return
        if stage == 'native_connect_diagnostic':
            phase = payload.get('nativeCheckpoint')
            detail = public_connect_diagnostic(payload.get('detail'))
            attempt = detail['attempt']
            expected = {'ordinary': ('ordinary_connect', 'ordinary_input'),
                        'rotation_refused': ('key_change_connect', 'key_change_review'),
                        'rotation_approved': ('key_change_connect', 'key_change_input')}
            require(self.failure is None and phase == expected[attempt][0]
                    and self.index == STAGES.index(expected[attempt][1])
                    and attempt not in self.result.get('connectDiagnostics', {}),
                    'tauri_ios_connect_diagnostic_invalid')
            fixture = self.ordinary if attempt == 'ordinary' else self.rotation
            if fixture is not None:
                try:
                    detail['peerAtDiagnostic'] = failure_peer_snapshot(fixture)
                except Exception:
                    pass
            self.result.setdefault('connectDiagnostics', {})[attempt] = detail
            return
        if stage == 'native_capture_diagnostic':
            phase = payload.get('nativeCheckpoint')
            require(self.failure is None and phase in ('ordinary_terminal_capture', 'key_change_terminal_capture',
                                                       'key_change_review_capture'),
                    'tauri_ios_capture_diagnostic_invalid')
            detail = public_capture_diagnostic(payload.get('detail'), review=phase == 'key_change_review_capture')
            trace = self.result.get('captureDiagnostics', {}).get(phase, [])
            require(len(trace) < 4, 'tauri_ios_capture_diagnostic_invalid')
            self.result.setdefault('captureDiagnostics', {}).setdefault(phase, []).append(detail)
            return
        if stage in ('native_progress', 'native_failure'):
            phase = payload.get('nativeCheckpoint')
            require(self.failure is None and phase in NATIVE_PHASES, 'tauri_ios_native_diagnostic_invalid')
            detail = None
            if 'geometryDetail' in payload:
                require(stage == 'native_progress' and phase in ('ordinary_password', 'key_change_password')
                        and 'geometryReason' in payload, 'tauri_ios_native_diagnostic_invalid')
                detail = public_geometry_detail(payload['geometryDetail'])
                require(len(self.result.get('geometryFailureDetails', {}).get(phase, [])) < 2,
                        'tauri_ios_native_diagnostic_invalid')
            if 'geometryReason' in payload:
                reason = payload['geometryReason']
                require(stage == 'native_progress' and phase in GEOMETRY_PHASES
                        and type(reason) is str and reason in GEOMETRY_REASONS,
                        'tauri_ios_native_diagnostic_invalid')
                trace = self.result.get('geometryReasonTrace', {}).get(phase, [])
                require(len(trace) < MAX_GEOMETRY_REASONS_PER_CHECKPOINT,
                        'tauri_ios_native_diagnostic_invalid')
                self.result.setdefault('geometryReasonTrace', {}).setdefault(phase, []).append(reason)
                if detail is not None:
                    self.result.setdefault('geometryFailureDetails', {}).setdefault(phase, []).append(
                        {'reason': reason, **detail})
            self.result['nativeCheckpoint'] = phase
            if 'nativePortType' in payload:
                require(phase.endswith('_port') and payload['nativePortType'] in ('textField', 'stepperTextField', 'other'),
                        'tauri_ios_native_diagnostic_invalid')
                self.result['nativePortType'] = payload['nativePortType']
            if 'nativeInputRole' in payload:
                require(phase.rsplit('_', 1)[-1] in ('host', 'port', 'username', 'password')
                        and payload['nativeInputRole'] in HOME_ROLES, 'tauri_ios_native_diagnostic_invalid')
                self.result.setdefault('nativeInputRoles', {})[phase] = payload['nativeInputRole']
            if stage == 'native_failure':
                code = payload.get('nativeFailureCode')
                require(code in NATIVE_FAILURES, 'tauri_ios_native_diagnostic_invalid')
                self.result['nativeFailureCode'] = code
                self.failure = 'tauri_ios_native_check_failed'
            return
        require(self.failure is None and self.index < len(STAGES) and stage == STAGES[self.index],
                'tauri_ios_checkpoint_order_invalid')
        self.result['stage'] = stage
        if stage in ('ordinary_form', 'key_change_form'):
            self.started_cases.add('ordinary' if stage == 'ordinary_form' else 'keyChange')
        ordinary, rotation = self.ordinary, self.rotation
        fixture = rotation if stage.startswith('key_change') else ordinary
        if stage == 'ordinary_probe':
            require(ordinary.wait_for_connections_closed(1, timeout=30), 'tauri_ios_probe_not_closed')
            events = ordinary.snapshot()['connectionEvents']
            require(len(events) == 1 and events[0]['hostKey'] == 'A'
                    and all(events[0][k] == 0 for k in ('authAttempts', 'ptyRequests', 'shellRequests', 'inputBytes', 'outputBytes')),
                    'tauri_ios_probe_not_empty')
        if stage == 'ordinary_password':
            self.result['cases']['ordinary']['fingerprintReviewed'] = True
        if stage == 'key_change_password_b':
            self.result['cases']['keyChange']['freshFingerprintConfirmed'] = True
        if stage in ('key_change_review', 'key_change_cancelled', 'key_change_probe_b'):
            count = 3 if stage == 'key_change_probe_b' else 2
            require(rotation.wait_for_connections_closed(count, timeout=30), 'tauri_ios_rotation_not_closed')
            try:
                evidence = rotation.rotation_evidence(count)
            except ValueError:
                raise Failure('tauri_ios_rotation_evidence_invalid') from None
            if stage != 'key_change_cancelled':
                self.result['cases']['keyChange'].setdefault('rotationEvidence', []).append(evidence)
            else:
                self.result['cases']['keyChange']['cancelKeptTrust'] = True
        if stage.endswith('_input'):
            count = 4 if fixture is rotation else 2
            wait_peer(fixture, lambda f: f['connections'] == count and len(f['connectionEvents']) == count
                      and f['connectionEvents'][-1]['markerReceived'] is True,
                      'tauri_ios_peer_input_missing')
            self.result['cases']['keyChange' if fixture is rotation else 'ordinary']['terminalInputReceived'] = True
        if stage in ('ordinary_terminal', 'key_change_terminal') or stage.endswith('_disconnect_attempt'):
            if fixture is ordinary:
                ordinary_evidence(fixture, closed=False)
            else:
                rotation_session_evidence(fixture, closed=False)
        if stage in ('ordinary_terminal', 'key_change_review', 'key_change_terminal'):
            self.capture(stage, payload, fixture)
        if stage.endswith('_disconnect_attempt'):
            self.disconnects.add(stage.split('_disconnect_attempt')[0])
        if stage.endswith('_disconnected'):
            prefix = stage.split('_disconnected')[0]
            require(prefix in self.disconnects, 'tauri_ios_disconnect_not_requested')
            count = 4 if fixture is rotation else 2
            require(fixture.wait_for_connections_closed(count, timeout=30), 'tauri_ios_peer_disconnect_missing')
            case = self.result['cases']['keyChange' if fixture is rotation else 'ordinary']
            if fixture is rotation:
                try:
                    case['rotationEvidence'].append(rotation.rotation_evidence(4))
                except ValueError:
                    raise Failure('tauri_ios_rotation_evidence_invalid') from None
                case['peer'] = rotation_session_evidence(fixture, closed=True)
            else:
                case['peer'] = ordinary_evidence(fixture, closed=True)
            case.update(status='passed', disconnected=True, terminalInputReceived=True)
        self.index += 1
        self.result['lastCompletedStage'] = stage


def start_checkpoints(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if not secrets.compare_digest(self.headers.get('Authorization', ''), state.secret):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                require(0 < length <= 12_000_000, 'tauri_ios_checkpoint_payload_invalid')
                payload = json.loads(self.rfile.read(length))
                require(isinstance(payload, dict), 'tauri_ios_checkpoint_payload_invalid')
                state.accept(payload)
                ok = True
            except Failure as error:
                state.failure, ok = str(error), False
            except Exception:
                state.failure, ok = 'tauri_ios_checkpoint_invalid', False
            body = json.dumps({'ok': ok}).encode()
            self.send_response(200 if ok else 409)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def prepare_driver(private, config):
    private = Path(private)
    source = (HERE / 'tauri_ios_direct_ssh.swift').read_text()
    (private / 'UITests').mkdir(mode=0o700)
    (private / 'UITests/Driver.swift').write_text(source)
    config_path = private / 'UITests/Fixture.json'
    # This file is copied as a resource, never expanded into compiled Swift or
    # a command line. Its parent, derived data and xcresult stay under mode 700.
    with open(config_path, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as target:
        json.dump(config, target)
    # Xcode UI tests need a target application. This inert, separate test host
    # is not the tested product; the driver explicitly launches the installed app.
    (private / 'Host').mkdir()
    (private / 'Host/Host.swift').write_text('import UIKit\n@main final class Host: UIResponder, UIApplicationDelegate {}\n')
    spec = {'name': 'PocketUI', 'options': {'deploymentTarget': {'iOS': '15.0'}},
            'settings': {'base': {'CODE_SIGNING_ALLOWED': 'NO', 'SWIFT_VERSION': '5.0',
                                  'GENERATE_INFOPLIST_FILE': 'YES', 'TARGETED_DEVICE_FAMILY': '1,2'}},
            'targets': {
                'DriverHost': {'type': 'application', 'platform': 'iOS', 'sources': ['Host'],
                               'settings': {'base': {'PRODUCT_BUNDLE_IDENTIFIER': 'dev.herdrpocket.uidriver.host'}}},
                'PocketUITests': {'type': 'bundle.ui-testing', 'platform': 'iOS',
                                  'sources': ['UITests/Driver.swift', {'path': 'UITests/Fixture.json', 'buildPhase': 'resources'}],
                                  'dependencies': [{'target': 'DriverHost'}],
                                  'settings': {'base': {'TEST_TARGET_NAME': 'DriverHost',
                                                       'PRODUCT_BUNDLE_IDENTIFIER': 'dev.herdrpocket.uidriver.tests'}}}},
            'schemes': {'PocketUI': {'build': {'targets': {'DriverHost': 'all', 'PocketUITests': ['test']}},
                                     'test': {'targets': [{'name': 'PocketUITests', 'parallelizable': False}],
                                              'gatherCoverageData': False}}}}
    write_json(private / 'project.json', spec)


def run(project, app, output, *, source_sha=None, env=None):
    batch_deadline = time.monotonic() + 1800
    env = os.environ if env is None else env
    output = Path(output).resolve()
    require(not output.exists() or not any(output.iterdir()), 'tauri_ios_output_not_empty')
    output.mkdir(parents=True, exist_ok=True)
    candidate_sha = source_sha or env.get('GITHUB_SHA')
    public_sha = candidate_sha if re.fullmatch(r'[0-9a-fA-F]{40}', candidate_sha or '') else None
    result = {'schemaVersion': 1, 'status': 'failed', 'platform': 'ios-simulator', 'client': 'tauri',
              'sourceSHA': public_sha, 'scope': 'owned_loopback_ordinary_ssh',
              'stage': 'input_validation', 'artifacts': {},
              'cases': {'ordinary': {'status': 'not_run'}, 'keyChange': {'status': 'not_run'}},
              'cleanup': {'simulatorDeleted': False, 'fixturesClosed': False, 'privateFilesRemoved': False}}
    device, server, server_thread, ordinary, rotation, private, state = None, None, None, None, None, None, None
    create_attempted = False
    peer_before_cleanup = {}
    device_name = 'herdr-tauri-ssh-' + uuid.uuid4().hex
    try:
        result['application'] = validate_inputs(project, app, candidate_sha)
        require(env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_OS') == 'macOS',
                'tauri_ios_requires_macos_ci')
        require(all(shutil.which(t) for t in ('xcrun', 'xcodebuild', 'xcodegen', 'tesseract')),
                'tauri_ios_dependencies_missing')
        result['stage'] = 'simulator_selection'
        result['toolchain'] = toolchain_evidence()
        runtimes = json.loads(command(['xcrun', 'simctl', 'list', 'runtimes', '--json']))['runtimes']
        types = json.loads(command(['xcrun', 'simctl', 'list', 'devicetypes', '--json']))['devicetypes']
        runtime, kind = select_simulator(runtimes, types)
        result['simulator'] = simulator_evidence(runtime, kind)
        result['stage'] = 'simulator_create'
        create_attempted = True
        device = command(['xcrun', 'simctl', 'create', device_name, kind, runtime]).decode().strip()
        require(bool(re.fullmatch(r'[A-Fa-f0-9-]{36}', device)), 'tauri_ios_device_identifier_invalid')
        result['stage'] = 'simulator_boot'
        command(['xcrun', 'simctl', 'boot', device])
        command(['xcrun', 'simctl', 'bootstatus', device, '-b'], timeout=240)
        result['stage'] = 'app_install'
        command(['xcrun', 'simctl', 'install', device, str(Path(app).resolve())])
        result['stage'] = 'fixture_start'
        ordinary = SingleCommandFixture(screen_proof=True, channel_deadline=batch_deadline).__enter__()
        rotation = SingleCommandFixture(rotate_after_probe=True, screen_proof=True, channel_deadline=batch_deadline).__enter__()
        result['cases']['ordinary']['fingerprint'] = ordinary.fingerprint
        result['cases']['keyChange']['fingerprints'] = {'A': rotation.fingerprint, 'B': rotation.rotated_fingerprint}
        state = Checkpoints(ordinary, rotation, output, result)
        server, server_thread = start_checkpoints(state)
        private = Path(tempfile.mkdtemp(prefix='herdr-tauri-ios-private-'))
        private.chmod(0o700)
        config = {'bundleIdentifier': BUNDLE_ID,
                  'checkpointURL': f'http://127.0.0.1:{server.server_port}/checkpoint',
                  'checkpointSecret': state.secret,
                  'ordinaryPort': ordinary.port, 'ordinaryPassword': ordinary.password,
                  'ordinaryFingerprint': ordinary.fingerprint,
                  'rotationPort': rotation.port, 'rotationPassword': rotation.password,
                  'fingerprintA': rotation.fingerprint, 'fingerprintB': rotation.rotated_fingerprint}
        result['stage'] = 'driver_prepare'
        prepare_driver(private, config)
        build = ['xcodebuild', '-project', str(private / 'PocketUI.xcodeproj'), '-scheme', 'PocketUI',
                 '-configuration', 'Debug', '-sdk', 'iphonesimulator', '-destination', 'id=' + device,
                 '-derivedDataPath', str(private / 'derived'), 'CODE_SIGNING_ALLOWED=NO',
                 '-parallel-testing-enabled', 'NO', '-maximum-concurrent-test-simulator-destinations', '1']
        build_driver(private, build, result, deadline=batch_deadline)
        runtime_log = private / 'xctest-private.log'
        result['stage'] = 'xctest_launch'
        try:
            with runtime_log.open('wb') as log:
                runtime_log.chmod(0o600)
                command([*build, 'test-without-building', '-resultBundlePath', str(private / 'run.xcresult'),
                         '-only-testing:PocketUITests/TauriDirectSSHUITests/testOrdinaryAndKeyChange'],
                        log=log, timeout=max(.1, min(900, batch_deadline - time.monotonic())))
        except Failure:
            result['runtimeDiagnostics'] = runtime_diagnostics(runtime_log, private)
            raise Failure(state.failure or 'tauri_ios_xctest_failed') from None
        if state.failure is not None:
            result['runtimeDiagnostics'] = runtime_diagnostics(runtime_log, private)
            raise Failure(state.failure)
        require(state.index == len(STAGES) and state.failure is None, 'tauri_ios_checkpoints_incomplete')
        require(set(result.get('homeEntry', {})) == {'ordinary', 'keyChange'}, 'tauri_ios_home_entry_incomplete')
        require(set(result['artifacts']) == set(PNG_FILES), 'tauri_ios_artifacts_incomplete')
        result['status'] = 'passed'
    except Failure as error:
        result['error'] = str(error)
    except Exception:
        # Never serialize exception text, raw XCTest output or an accessibility tree.
        result['error'] = 'tauri_ios_driver_failed'
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
        if state is not None:
            state.finalize_cases()
            for name, fixture in (('ordinary', ordinary), ('keyChange', rotation)):
                if name in state.started_cases and fixture is not None:
                    try:
                        peer_before_cleanup[name] = failure_peer_snapshot(fixture)
                    except Exception:
                        pass
        for fixture in (ordinary, rotation):
            if fixture is not None:
                fixture.close()
        result['cleanup']['fixturesClosed'] = all(f is None or f.snapshot()['connectionsClosed']
                                                 for f in (ordinary, rotation))
        if not result['cleanup']['fixturesClosed']:
            result['status'], result['error'] = 'failed', 'tauri_ios_fixture_cleanup_failed'
        if device is not None:
            try:
                command(['xcrun', 'simctl', 'shutdown', device], timeout=60)
            except Failure:
                pass
            try:
                command(['xcrun', 'simctl', 'delete', device], timeout=60)
                result['cleanup']['simulatorDeleted'] = True
            except Failure:
                result['status'], result['error'] = 'failed', 'tauri_ios_simulator_cleanup_failed'
        elif create_attempted:
            # A timed-out create might have succeeded: recover only our unique name.
            try:
                devices = json.loads(command(['xcrun', 'simctl', 'list', 'devices', '--json'], timeout=60))['devices']
                owned = [d['udid'] for group in devices.values() for d in group if d.get('name') == device_name]
                for owned_device in owned:
                    command(['xcrun', 'simctl', 'delete', owned_device], timeout=60)
                result['cleanup']['simulatorDeleted'] = True
            except Exception:
                pass
        if private is not None:
            try:
                shutil.rmtree(private)
            except OSError:
                result['status'], result['error'] = 'failed', 'tauri_ios_private_cleanup_failed'
        result['cleanup']['privateFilesRemoved'] = private is None or not private.exists()
        if result['status'] != 'passed':
            for name, fixture in (('ordinary', ordinary), ('keyChange', rotation)):
                if name in peer_before_cleanup and fixture is not None:
                    report = {'beforeCleanup': peer_before_cleanup[name]}
                    try:
                        report['afterCleanup'] = failure_peer_snapshot(fixture)
                    except Exception:
                        pass
                    result['cases'][name]['failurePeerObservations'] = report
        write_json(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-sha', default=None)
    args = parser.parse_args()
    try:
        result = run(args.project, args.app, args.output, source_sha=args.source_sha)
    except Failure:
        print('tauri_ios_output_not_empty')
        return 1
    print('tauri_ios_' + result['status'])
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
