"""Public, fixed attestation contract for one owned paired terminal fixture."""
import json

# (visible auxiliary button, accepted UTF-8 bytes, independent application effect)
STEPS = (('down', 3, 'select-next'), ('tab', 1, 'focus-detail'),
         ('backspace', 1, 'erase-character'), ('shift-tab', 3, 'focus-list'),
         ('insert', 4, 'insert-row'), ('delete', 4, 'delete-row'), ('f1', 3, 'open-help'),
         ('f1', 3, 'close-help'), ('f5', 5, 'refresh'), ('f10', 5, 'finish'))
ACTIONS = tuple(action for _, _, action in STEPS)
EXPECTED = {'status': 'finished', 'actions': list(ACTIONS), 'selected': 'Review',
            'rowCount': 2, 'detailLength': 1, 'focus': 'list', 'helpOpen': False,
            'refreshes': 1}


def validate_report(raw):
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError('paired_tui_report_invalid') from None
    if not isinstance(report, dict) or set(report) != set(EXPECTED):
        raise ValueError('paired_tui_report_invalid')
    for key, value in EXPECTED.items():
        if type(report[key]) is not type(value) or report[key] != value:
            raise ValueError('paired_tui_report_invalid')
    return {'applicationStateMatched': True, 'actionCount': len(ACTIONS)}
