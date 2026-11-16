"""Classify one process's Go panic lines from `logcat -s Go:E`.

Android logcat prints the tag in an 8-column field, so the line is
`E Go      : panic: ...`, not `E Go:`. The body after the colon is the only
text classified. The result is bounded enums plus a few function symbols:
the panic class, the reason, this package's frame, the first non-runtime
frame and up to three upstream tailscale frames. Symbols are ASCII
package/function syntax only: no line numbers, addresses or arguments.
"""
import re

# threadtime: priority, tag padded to 8 columns, then the message.
GO_LINE = re.compile(rb'E Go\s+:[ \t]?(?P<body>.*)$', re.MULTILINE)
# A frame is "pkg.(*T).Method(" or "pkg.Func(": package path, optional
# receiver, optional method. A path segment may contain '-', as in
# "herdr.local/tailscale-runtime". Arguments after '(' are never captured.
FRAME = re.compile(
    rb'(?P<base>[A-Za-z_][A-Za-z0-9_-]*(?:[./][A-Za-z0-9_][A-Za-z0-9_-]*)*)'
    rb'(?:\.\(\*?(?P<recv>[A-Za-z0-9_]+)\))?'
    rb'(?:[./](?P<fn>[A-Za-z_][A-Za-z0-9_]*))?\(')
# Bounded symbol syntax: at least one '.' or '/', ASCII identifiers only.
SYMBOL = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:[./][A-Za-z0-9_][A-Za-z0-9_-]*)+')
RUNTIME_PREFIX = ('runtime.', 'runtime/')
APP_PREFIXES = ('main.', 'herdr.local/tailscale-runtime.')
UPSTREAM_PREFIX = 'tailscale.com/'
# Lines that are not frames: headers, source positions and blank lines.
NOT_FRAME = (b'goroutine ', b'panic:', b'fatal error:', b'runtime error:',
             b'throw:', b'[signal ', b'exit status', b'created by ')

# Specific reasons before the generic "runtime error:" bucket. A nil-pointer
# panic is itself a runtime error; matching the generic needle first would
# hide the actual cause.
REASONS = (
    (b'nil pointer', 'nil-pointer'),
    (b'invalid memory address', 'nil-pointer'),
    (b'index out of range', 'index-out-of-range'),
    (b'slice bounds', 'slice-bounds'),
    (b'makeslice: len out of range', 'makeslice'),
    (b'send on closed channel', 'send-on-closed-channel'),
    (b'close of closed channel', 'close-closed-channel'),
    (b'close of nil channel', 'close-nil-channel'),
    (b'concurrent map', 'concurrent-map'),
    (b'all goroutines are asleep', 'deadlock'),
    (b'unexpected signal during runtime execution', 'unexpected-signal'),
    (b'interface conversion', 'interface-conversion'),
    (b'integer divide by zero', 'divide-by-zero'),
    (b'negative shift', 'negative-shift'),
    (b'assignment to entry in nil map', 'nil-map'),
    (b'unlock of unlocked mutex', 'unlock-unlocked-mutex'),
    (b'negative WaitGroup', 'negative-waitgroup'),
    (b'runtime error:', 'runtime-error'),
)

PANIC_CLASSES = {'go-panic', 'go-fatal', 'go-throw', 'other'}
MAX_BODY = 262144
MAX_UPSTREAM = 3


def _panic_class(body):
    if body.startswith(b'panic:'):
        return 'go-panic'
    if body.startswith(b'fatal error:'):
        return 'go-fatal'
    if body.startswith(b'throw:'):
        return 'go-throw'
    return ''


def _reason(body):
    for needle, name in REASONS:
        if needle in body:
            return name
    return 'unspecified'


def _symbol(match):
    """Build one ASCII package/function symbol from a frame match."""
    base = match.group('base').decode('ascii', 'replace')
    recv = (match.group('recv') or b'').decode('ascii', 'replace')
    fn = (match.group('fn') or b'').decode('ascii', 'replace')
    parts = [base] + ([recv] if recv else []) + ([fn] if fn else [])
    symbol = '.'.join(parts)
    if not SYMBOL.fullmatch(symbol):
        return ''
    return symbol[:160]


def _frame(body):
    """Return this line's symbol, 'runtime' for a runtime frame, or ''."""
    stripped = body.lstrip(b'\t ')
    if not stripped or stripped.startswith(NOT_FRAME):
        return ''
    if b'.go:' in stripped:
        return ''
    match = FRAME.match(stripped)
    if not match:
        return ''
    symbol = _symbol(match)
    if not symbol:
        return ''
    if symbol.startswith(RUNTIME_PREFIX):
        return 'runtime'
    return symbol


def classify(text):
    """Reduce `logcat -s Go:E` text to bounded evidence."""
    if isinstance(text, str):
        raw = text.encode('utf-8', 'replace')
    else:
        raw = text or b''
    bodies = [match.group('body')[:4096] for match in GO_LINE.finditer(raw[:MAX_BODY])]
    if not bodies:
        return {'available': False}

    panic_class = ''
    header = b''
    for body in bodies:
        panic_class = _panic_class(body)
        if panic_class:
            header = body
            break

    app = ''
    first = ''
    upstream = []
    for body in bodies:
        symbol = _frame(body)
        if not symbol or symbol == 'runtime':
            continue
        if not app and symbol.startswith(APP_PREFIXES):
            app = symbol
        if not first:
            first = symbol
        if symbol.startswith(UPSTREAM_PREFIX) and symbol not in upstream:
            upstream.append(symbol)
    if not panic_class and not app and not first:
        return {'available': False}
    return {
        'available': True,
        'panicClass': panic_class or 'other',
        'reason': _reason(header) if header else 'unspecified',
        'appFunction': app or 'none',
        'firstFrame': first or 'none',
        'upstreamFrames': upstream[:MAX_UPSTREAM],
    }
