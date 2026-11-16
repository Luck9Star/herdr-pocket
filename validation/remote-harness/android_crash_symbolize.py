"""Symbolize Android tombstone frames against the probe's own libraries.

The output is bounded on purpose: module basename, Go function name and the
pc offset. Absolute addresses, full paths and raw tombstone text never
leave this module.
"""
import re
import subprocess
from pathlib import Path

# Frame lines look like:
#   #00 pc 000000000004a1b0  /data/app/.../lib/x86_64/libhp_tailscale.so (BuildId: ...)
#   #01 pc 000000000004a1b0  /apex/.../libc.so (BuildId: ...)
FRAME = re.compile(rb'#(\d+)\s+pc\s+([0-9a-f]+)\s+(\S+lib[\w.\-]*\.so)')

# Only the probe's own application libraries are symbolized. System frames
# are reported by basename only.
OWN_PREFIXES = ('libhp_tailscale.so', 'libherdr_flutter_network_runtime.so',
                'libabi_shim.so', 'libheeler_easytier.so')


def extract_frames(text):
    """Return bounded frame records from one crash record.

    Each record is {'module': basename, 'pc': hex offset string}. Absolute
    addresses are already file offsets in the tombstone, so they are kept
    only as the relative pc value.
    """
    frames = []
    seen = set()
    for match in FRAME.finditer(text):
        module = match.group(3).decode('ascii', 'replace')
        basename = module.rsplit('/', 1)[-1]
        pc = match.group(2).decode('ascii')
        key = (basename, pc)
        if key in seen:
            continue
        seen.add(key)
        frames.append({'module': basename, 'pc': pc})
        if len(frames) >= 24:
            break
    return frames


def symbolize(frames, library_dir):
    """Resolve frames of the probe's own libraries to function names.

    Uses addr2line on the shipped library, so the names come from the exact
    binary that crashed. Frames of other modules keep only their basename.
    """
    resolved = []
    for frame in frames:
        entry = {'module': frame['module']}
        library = None
        if frame['module'] in OWN_PREFIXES:
            candidate = Path(library_dir) / frame['module']
            if candidate.is_file():
                library = candidate
        if library is not None:
            try:
                result = subprocess.run(
                    ['addr2line', '-f', '-C', '-e', str(library), '0x' + frame['pc']],
                    capture_output=True, text=True, timeout=30)
                names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                if names:
                    entry['function'] = names[0][:160]
                    if len(names) > 1 and names[1] != '??':
                        entry['source'] = names[1].rsplit('/', 1)[-1][:160]
            except (OSError, subprocess.SubprocessError):
                pass
        resolved.append(entry)
    return resolved


def bounded_report(frames, library_dir, limit=12):
    """Bounded, redacted frame report: module basename plus function name."""
    resolved = symbolize(frames, library_dir)
    report = []
    for entry in resolved:
        if entry['module'] not in OWN_PREFIXES:
            continue
        item = {'module': entry['module']}
        if 'function' in entry:
            item['function'] = entry['function']
        if 'source' in entry:
            item['source'] = entry['source']
        report.append(item)
        if len(report) >= limit:
            break
    return report
