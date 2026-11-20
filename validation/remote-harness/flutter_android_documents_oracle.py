"""Fail-closed evidence checks for the Flutter Android documents round trip.

No device operations or persisted secrets; the future driver owns all UI actions.
"""
import json

from paired_gui import GuiFailure
from tauri_android_config_document import decrypt_archive

MAX_CATALOG = 131072
FONT = 19
CONTROL_FONT = 13


def strict_json(raw, error):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('constant')))
    except (ValueError, UnicodeError, AttributeError):
        raise GuiFailure(error) from None


def catalog(raw, font):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_CATALOG:
        raise GuiFailure('catalog_invalid')
    value = strict_json(raw, 'catalog_invalid')
    if (not isinstance(value, dict) or set(value) != {'schemaVersion', 'profiles', 'pendingCreation',
                                                       'networkProfiles', 'preferences'}
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 4
            or value['profiles'] != [] or value['networkProfiles'] != []
            or value['pendingCreation'] is not None or not isinstance(value['preferences'], dict)
            or set(value['preferences']) != {'terminalFontSize'}
            or type(value['preferences']['terminalFontSize']) is not int
            or value['preferences']['terminalFontSize'] != font):
        raise GuiFailure('catalog_mismatch')
    return raw


def archive(raw, password):
    value = strict_json(decrypt_archive(raw, password), 'archive_invalid')
    if (not isinstance(value, dict) or set(value) != {'version', 'hosts', 'networks', 'preferences'}
            or type(value['version']) is not int or value['version'] != 2
            or value['hosts'] != [] or value['networks'] != []
            or not isinstance(value['preferences'], dict) or set(value['preferences']) != {'terminalFontSize'}
            or type(value['preferences']['terminalFontSize']) is not int
            or value['preferences']['terminalFontSize'] != FONT):
        raise GuiFailure('archive_invalid')


class Ledger:
    """Bytes remain in process only; one dispatch is allowed even if its result is unknown."""
    STEPS = ('initial19', 'cancel', 'export', 'control13', 'wrong_password', 'tampered', 'preview', 'apply')

    def __init__(self):
        self.index = 0
        self.reference = None
        self.dispatched = False

    def record(self, stage, raw):
        if self.index >= len(self.STEPS) or stage != self.STEPS[self.index]:
            raise GuiFailure('checkpoint_order_invalid')
        if stage == 'apply' and not self.dispatched:
            raise GuiFailure('apply_not_dispatched')
        font = CONTROL_FONT if stage in ('control13', 'wrong_password', 'tampered', 'preview') else FONT
        catalog(raw, font)
        if stage in ('cancel', 'export', 'wrong_password', 'tampered', 'preview') and raw != self.reference:
            raise GuiFailure('catalog_changed')
        if stage == 'control13' and raw == self.reference:
            raise GuiFailure('catalog_unchanged')
        if stage == 'apply' and raw == self.reference:
            raise GuiFailure('catalog_unchanged')
        self.reference = raw
        self.index += 1

    def begin_apply(self):
        if self.index != self.STEPS.index('apply') or self.dispatched:
            raise GuiFailure('apply_dispatch_forbidden')
        self.dispatched = True
