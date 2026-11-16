"""Produce a bounded Go traceback summary without returning captured stderr."""
import hashlib
import re

_LIMIT = 1024 * 1024
_HEADER = re.compile(r'^(panic|fatal error): (.*)$')
_GOROUTINE = re.compile(r'^goroutine [0-9]+(?: [^\[\]\r\n]+)? \[running(?:, locked to thread)?\]:$')
_SIGNAL = re.compile(r'^\[signal SIG[A-Z0-9]+: [^\]\r\n]*\]$')
_SOURCE = re.compile(r'^\s*(\S+\.go):(\d{1,7})(?:\s|$)')
# A package allowlist is essential: untrusted text must not become a symbol.
_SYMBOL = re.compile(r'^((?:[^\s(]|\([^()\s]*\))+)\(')
_SAFE_SYMBOL = re.compile(r'^[A-Za-z0-9_./*()\[\],~+\-]+$')
_SAFE_FILE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}\.go$')
_PREFIXES = ('runtime.', 'runtime/', 'internal/', 'sync.', 'sync/', 'net.', 'net/',
             'syscall.', 'os.', 'context.', 'main.', 'testing.', 'crypto/',
             'herdr.local/tailscale-runtime.',
             'tailscale.com/', 'gvisor.dev/', 'golang.org/', 'github.com/tailscale/',
             'github.com/', 'go4.org/', 'wireguard.com/')
# github.com is deliberately narrowed to known upstream namespaces.
_PREFIXES = tuple(p for p in _PREFIXES if p != 'github.com/') + (
    'github.com/google/', 'github.com/sagernet/', 'github.com/wireguard/',
    'github.com/gaissmai/', 'github.com/mdlayher/')
_KNOWN = {
    'runtime error: invalid memory address or nil pointer dereference': 'nil_pointer',
    'runtime error: integer divide by zero': 'divide_by_zero',
    'runtime error: makeslice: len out of range': 'makeslice_length',
    'runtime error: makeslice: cap out of range': 'makeslice_capacity',
    'concurrent map writes': 'concurrent_map_writes',
    'concurrent map read and map write': 'concurrent_map_read_write',
}


def _digest(value):
    return hashlib.sha256(value.encode('utf-8', 'surrogateescape')).hexdigest()


def _frame(function, path, line):
    basename = path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
    # Symbols are only exposed for known public package namespaces; never arguments.
    public = (len(function) <= 180 and _SAFE_SYMBOL.fullmatch(function)
              and function.startswith(_PREFIXES))
    filename_ok = bool(_SAFE_FILE.fullmatch(basename)) and public
    return {'function': function if public else None,
            'function_sha256': None if public else _digest(function),
            'file': basename if filename_ok else None,
            'file_sha256': None if filename_ok else _digest(basename),
            'line': int(line)}


def summarize(raw_bytes):
    """Summarize first panic and its immediately following running goroutine.

    Dynamic message digest hashes the exact bytes after the header delimiter,
    excluding the line ending. No captured text or traceback arguments are returned.
    `truncated` indicates detectable truncation, not proof of completeness.
    """
    if not isinstance(raw_bytes, bytes):
        raise TypeError('raw_bytes must be bytes')
    clipped = len(raw_bytes) > _LIMIT
    raw = raw_bytes[:_LIMIT]
    text = raw.decode('utf-8', 'surrogateescape')
    lines = text.splitlines()
    result = {'status': 'empty' if not raw else 'no_panic', 'panic': None,
              'origin': None, 'frames': [], 'truncated': clipped or bool(raw and not raw.endswith(b'\n'))}
    header_index = next((i for i, line in enumerate(lines) if _HEADER.fullmatch(line)), None)
    if header_index is None:
        return result
    match = _HEADER.fullmatch(lines[header_index])
    kind, message = match.groups()
    result['status'] = 'panic'
    result['panic'] = {'kind': kind, 'category': _KNOWN.get(message, 'other'),
                       'message_sha256': _digest(message)}
    i = header_index + 1
    # Nested panic headings may precede the same traceback. Never scan past
    # unrelated output or a different goroutine to infer a panic origin.
    while i < len(lines) and (not lines[i].strip() or _HEADER.fullmatch(lines[i]) or _SIGNAL.fullmatch(lines[i])):
        i += 1
    if i >= len(lines):
        result['truncated'] = True
        return result
    if not _GOROUTINE.fullmatch(lines[i]):
        return result
    i += 1
    while i < len(lines):
        if not lines[i].strip() or lines[i].startswith('goroutine ') or lines[i].startswith('created by '):
            break
        if lines[i].startswith('...'):
            result['truncated'] = True
            break
        symbol = _SYMBOL.match(lines[i])
        if not symbol:
            break
        if i + 1 >= len(lines):
            result['truncated'] = True
            break
        source = _SOURCE.match(lines[i + 1])
        if not source:
            break
        function = symbol.group(1)
        frame = _frame(function, source.group(1), source.group(2))
        if len(result['frames']) < 8:
            result['frames'].append(frame)
        if (result['origin'] is None and not function.startswith(('runtime.', 'runtime/'))
                and '/src/runtime/' not in source.group(1).replace('\\', '/')):
            result['origin'] = frame
        i += 2
    return result
