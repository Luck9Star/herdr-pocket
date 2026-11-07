"""Shared fixture contract for the reviewed Android input case."""
import re
from paired_tui import ACTIONS, STEPS


ANDROID_ROUTES = ('flutter-android', 'tauri-android')
DIRECT = b'k'
DRAFT = 'Pocket测'.encode('utf-8')
TUI_SCREEN_CHECKS = ('initial', *ACTIONS[:-1])
TUI_KEY_LENGTHS = tuple(size for _, size, _ in STEPS)


class EvidenceError(ValueError):
    """Only static failure codes may leave the isolated fixture."""


def validate_mode(route, has_fixture, android_guarded, android_tui=False):
    if android_tui and not android_guarded:
        raise EvidenceError('android_tui_requires_guarded_input')
    if android_guarded and (route not in ANDROID_ROUTES or not has_fixture):
        raise EvidenceError('android_guarded_input_requires_mobile_fixture')
    if has_fixture and route in ANDROID_ROUTES and not android_guarded:
        raise EvidenceError('android_stock_case_requires_stock_server')
    if has_fixture and not route:
        raise EvidenceError('input_fixture_requires_gui')


def expected_bytes(route, has_fixture):
    if not has_fixture:
        return b''
    return DIRECT + DRAFT if route in ANDROID_ROUTES else DRAFT


def checked_receipts(raw, sizes, pane, terminal, seen):
    if not isinstance(raw, list) or len(raw) != len(sizes):
        raise EvidenceError('guarded_receipt_count_invalid')
    clean = []
    for receipt, size in zip(raw, sizes):
        if not isinstance(receipt, dict) or set(receipt) != {'requestId', 'paneId', 'terminalId', 'acceptedBytes'}:
            raise EvidenceError('guarded_receipt_fields_invalid')
        identifier = receipt['requestId']
        if (not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier)
                or identifier in seen):
            raise EvidenceError('guarded_receipt_request_invalid')
        seen.add(identifier)
        if type(receipt['acceptedBytes']) is not int or receipt['acceptedBytes'] != size:
            raise EvidenceError('guarded_receipt_size_invalid')
        pane_id, terminal_id = receipt['paneId'], receipt['terminalId']
        if (not isinstance(pane_id, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', pane_id)
                or not isinstance(terminal_id, str) or not re.fullmatch(r'term_[0-9a-f]{1,123}', terminal_id)):
            raise EvidenceError('guarded_receipt_target_invalid')
        if pane is None:
            pane = pane_id
        if terminal is None:
            terminal = terminal_id
        if (pane_id, terminal_id) != (pane, terminal):
            raise EvidenceError('guarded_receipt_target_mismatch')
        clean.append(dict(receipt))
    return clean


def mobile_receipts(raw, pane=None, terminal=None):
    return checked_receipts(raw, (len(DIRECT), len(DRAFT)), pane, terminal, set())


def mobile_tui_evidence(raw, prior_receipts, pane=None, terminal=None):
    """Require ten distinct GUI actions on the same target as both earlier writes."""
    prior = mobile_receipts(prior_receipts, pane, terminal)
    if not isinstance(raw, dict) or set(raw) != {'receipts', 'screenChecks', 'observedInitialFull'}:
        raise EvidenceError('mobile_tui_evidence_fields_invalid')
    if raw['observedInitialFull'] is not True or raw['screenChecks'] != list(TUI_SCREEN_CHECKS):
        raise EvidenceError('mobile_tui_screen_checks_invalid')
    receipts = checked_receipts(raw['receipts'], TUI_KEY_LENGTHS, prior[0]['paneId'],
                                prior[0]['terminalId'], {r['requestId'] for r in prior})
    return {'receipts': receipts, 'screenChecks': list(TUI_SCREEN_CHECKS), 'observedInitialFull': True}
