"""Extract bounded, allowlisted Go panic symbols from a private test log."""
import re

_ALLOWED_FUNCTION = re.compile(r'^(?:runtime\.|tailscale\.com/|herdr\.local/tailscale-runtime/fixture\.)[A-Za-z0-9_./*()\-]+$')
_SOURCE = re.compile(r'^\s*(/[^\s:]+\.go):(\d{1,5})(?:\s|$)')
_GOROUTINE = re.compile(r'^goroutine [0-9]+ \[running\]:$')


def sanitize_go_panic(raw):
    """Return only fixed category and first crashing goroutine's safe frame names."""
    text = raw[-1048576:].decode('utf-8', errors='replace')
    lower = text.lower()
    if 'panic:' not in lower and 'fatal error:' not in lower:
        return {'category':'none', 'frames':[]}
    if 'invalid memory address or nil pointer dereference' in lower:
        category = 'nil_pointer'
    elif 'index out of range' in lower:
        category = 'index_out_of_range'
    elif 'concurrent map' in lower:
        category = 'concurrent_map'
    else:
        category = 'other'
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _GOROUTINE.fullmatch(line)), None)
    if start is None:
        return {'category':category, 'frames':[]}
    frames = []
    for index in range(start + 1, len(lines) - 1):
        if lines[index].startswith('goroutine ') or not lines[index].strip():
            break
        function = lines[index].rsplit('(', 1)[0].strip() if '(' in lines[index] else ''
        source = _SOURCE.match(lines[index + 1])
        if not source or not _ALLOWED_FUNCTION.fullmatch(function):
            continue
        path, line = source.groups()
        allowed_path = ('/src/runtime/' in path or '/upstream/tailscale/' in path or
                        re.search(r'/[^/]*candidate/fixture/', path) is not None)
        if allowed_path and '..' not in path.split('/') and 1 <= int(line) <= 10000:
            frames.append({'function':function, 'file':path.rsplit('/', 1)[-1], 'line':int(line)})
        if len(frames) == 20:
            break
    return {'category':category, 'frames':frames}
