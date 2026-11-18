#!/usr/bin/env python3
"""Publish numeric host/owned-emulator diagnostics without raw system logs."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def read_number(path):
    try:
        value = Path(path).read_text().strip()
        return int(value) if value.isdigit() else None
    except OSError:
        return None


def memory_events(path):
    try:
        lines = Path(path).read_text().splitlines()
        values = dict(line.split() for line in lines)
        return {key: int(values[key]) for key in ('low', 'high', 'max', 'oom', 'oom_kill')
                if key in values and values[key].isdigit()}
    except (OSError, ValueError):
        return None


def process_state(pid):
    try:
        # /proc comm may contain spaces and parentheses; state follows the
        # final ')'. Do not publish the process name or any other proc data.
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].strip().split()[0]
        return state if state in ('R', 'S', 'D', 'Z', 'T', 'I') else 'other'
    except (OSError, IndexError):
        return 'absent-or-unavailable'


def oom_diagnostic(pid):
    try:
        result = subprocess.run(['dmesg'], capture_output=True, timeout=5, check=False)
        if result.returncode or len(result.stdout) > 16 * 1024 * 1024:
            return {'available': False}
        lines = result.stdout.decode('utf-8', errors='replace').splitlines()
        events = [line for line in lines if 'Out of memory' in line or 'Killed process' in line or 'oom-kill:' in line]
        matches = sum(bool(re.search(r'(?<![0-9])' + re.escape(str(pid)) + r'(?![0-9])', line)) for line in events)
        return {'available': True, 'oomLineCount': len(events), 'ownedPidMentionCount': matches}
    except (OSError, subprocess.TimeoutExpired):
        return {'available': False}


def current_cgroup():
    root = Path('/sys/fs/cgroup')
    try:
        for line in Path('/proc/self/cgroup').read_text().splitlines():
            hierarchy, _, raw = line.split(':', 2)
            if hierarchy == '0' and raw.startswith('/'):
                parts = Path(raw).parts
                if '..' not in parts:
                    candidate = root.joinpath(*parts[1:])
                    if (candidate / 'memory.events').is_file():
                        return candidate, True
    except (OSError, ValueError):
        pass
    return root, False


def snapshot(pid, temp):
    stats = os.statvfs(temp)
    cgroup, scoped = current_cgroup()
    return {
        'schemaVersion': 1,
        'ownedProcessState': process_state(pid),
        'cgroupScopedToRunner': scoped,
        'cgroupMemoryCurrentBytes': read_number(cgroup / 'memory.current'),
        'cgroupMemoryMaxBytes': read_number(cgroup / 'memory.max'),
        'cgroupMemoryEvents': memory_events(cgroup / 'memory.events'),
        'temporaryFreeBytes': stats.f_bavail * stats.f_frsize,
        'oomLog': oom_diagnostic(pid),
    }


if __name__ == '__main__':
    print(json.dumps(snapshot(int(sys.argv[1]), sys.argv[2]), sort_keys=True))
