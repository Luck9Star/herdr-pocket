"""Check a stock phone's observation against independently known fixture IDs."""
from blocked_fixture import PANE, TERMINAL


def checked_targets(rows):
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError('android_blocked_target_evidence_invalid')
    clean = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'paneId', 'terminalId'}
                or not isinstance(row['paneId'], str) or not PANE.fullmatch(row['paneId'])
                or not isinstance(row['terminalId'], str) or not TERMINAL.fullmatch(row['terminalId'])):
            raise ValueError('android_blocked_target_evidence_invalid')
        clean.append(dict(row))
    if any(clean[0][key] == clean[1][key] for key in ('paneId', 'terminalId')):
        raise ValueError('android_blocked_target_evidence_invalid')
    return clean


def checked_receipt(raw, targets):
    target = checked_targets(targets)[1]
    facts = ('reviewRequired', 'observing', 'markerMatched', 'otherMarkerAbsent')
    if (not isinstance(raw, dict) or set(raw) != {*target, 'listedRows', *facts}
            or type(raw['listedRows']) is not int or raw['listedRows'] != 2
            or any(raw[key] != value for key, value in target.items())
            or any(raw[key] is not True for key in facts)):
        raise ValueError('android_blocked_target_evidence_invalid')
    return dict(raw)
