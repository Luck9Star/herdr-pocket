"""An interactive application for a disposable xterm-256color PTY.

The report contains only this fixture's bounded, synthetic UI state.
"""
import argparse
import curses
import json
import signal
import sys
import time
from pathlib import Path


def run(screen, seconds, cancelled):
    items = ['Build', 'Review']
    selected = 0
    detail = 'xy'
    in_detail = False
    help_open = False
    refreshes = 0
    actions = []
    status = 'timeout'
    deadline = time.monotonic() + seconds
    screen.keypad(True)
    screen.timeout(100)
    while time.monotonic() < deadline and not cancelled():
        screen.erase()
        lines = ['Pocket TUI', 'F1 Help   F5 Refresh   F10 Finish'] if not help_open else [
            'Pocket TUI Help', 'F1 Return to list']
        if not help_open:
            lines.extend(('> ' if i == selected else '  ') + item for i, item in enumerate(items))
            lines.extend(['Detail: ' + detail, 'Focus: ' + ('detail' if in_detail else 'list'),
                          'Refreshes: ' + str(refreshes)])
        height, width = screen.getmaxyx()
        for y, line in enumerate(lines[:height]):
            if width > 1:
                screen.addnstr(y, 0, line, width - 1)
        screen.refresh()
        key = screen.getch()
        if key in (-1, curses.KEY_RESIZE):
            continue
        if key == curses.KEY_F10:
            actions.append('finish')
            status = 'finished'
            break
        if key == curses.KEY_F1:
            help_open = not help_open
            action = 'open-help' if help_open else 'close-help'
        elif help_open:
            action = 'unhandled'
        elif key == curses.KEY_DOWN and not in_detail:
            selected = min(selected + 1, len(items) - 1)
            action = 'select-next'
        elif key == 9:
            in_detail = True
            action = 'focus-detail'
        elif key == curses.KEY_BTAB:
            in_detail = False
            action = 'focus-list'
        elif key in (curses.KEY_BACKSPACE, 127, 8) and in_detail:
            detail = detail[:-1]
            action = 'erase-character'
        elif key == curses.KEY_IC and not in_detail and 'New' not in items:
            selected += 1
            items.insert(selected, 'New')
            action = 'insert-row'
        elif key == curses.KEY_DC and not in_detail and items[selected] == 'New':
            items.pop(selected)
            selected -= 1
            action = 'delete-row'
        elif key == curses.KEY_F5:
            refreshes += 1
            action = 'refresh'
        else:
            action = 'unhandled'
        actions.append(action)
        if len(actions) >= 64:
            status = 'action-limit'
            break
    if cancelled() and status == 'timeout':
        status = 'cancelled'
    return {'status': status, 'actions': actions, 'selected': items[selected],
            'rowCount': len(items), 'detailLength': len(detail),
            'focus': 'detail' if in_detail else 'list', 'helpOpen': help_open,
            'refreshes': refreshes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path, help='new fixture result file')
    parser.add_argument('--seconds', default=12, type=int, choices=range(1, 61), metavar='1..60')
    args = parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('a disposable PTY is required')
    stop = False

    def cancel(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    # Reserve the requested result before changing terminal modes. Refuse to
    # overwrite an existing file on a second run.
    with args.report.open('x', encoding='utf-8') as output:
        result = curses.wrapper(run, args.seconds, lambda: stop)
        json.dump(result, output, separators=(',', ':'))
        output.write('\n')
    return 0 if result['status'] == 'finished' else 1


if __name__ == '__main__':
    sys.exit(main())
