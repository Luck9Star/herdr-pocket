"""Read-only, bounded facts for one authorization failure; never export dumps."""
import re
from xml.etree.ElementTree import Element

PACKAGE = r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*'
CLASS = r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*'


def package(value):
    return value if isinstance(value, str) and len(value) <= 128 and re.fullmatch(PACKAGE, value) else None


def component(value):
    if not isinstance(value, str) or len(value) > 256:
        return None
    match = re.fullmatch('(' + PACKAGE + r')/(\.?' + CLASS + ')', value)
    if not match or not package(match.group(1)):
        return None
    owner, activity = match.groups()
    activity = owner + activity if activity.startswith('.') else activity
    result = owner + '/' + activity
    return result if len(result) <= 256 else None


def system_packages(raw):
    if not isinstance(raw, str):
        raise ValueError()
    return {line[8:] for line in raw.splitlines()
            if line.startswith('package:') and package(line[8:])}


def window_component(raw):
    if not isinstance(raw, str):
        raise ValueError()
    values = []
    for value in re.findall(r'^\s*mCurrentFocus\s*=\s*([^\r\n]*)', raw, re.MULTILINE):
        match = re.fullmatch(r'Window\{[0-9a-fA-F]{1,32}\s+u[0-9]{1,6}\s+(\S{1,256})\}\s*', value)
        values.append(component(match.group(1)) if match else None)
    return values[0] if values and values[0] and len(set(values)) == 1 else None


def native_nodes(value):
    if not isinstance(value, (list, tuple)) or not all(isinstance(node, (dict, Element)) for node in value):
        raise ValueError()
    return value


def process_alive(raw):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ValueError()
    raw = raw.strip()
    if not raw:
        return False
    if not re.fullmatch(r'[1-9][0-9]{0,9}(?:\s+[1-9][0-9]{0,9})*', raw):
        raise ValueError()
    return True


def summarize(activity, before, after, nodes, systems, owned, port):
    trusted = systems | owned
    def approved(value):
        value = component(value)
        return value if value and value.split('/')[0] in trusted else None
    activity, before, after = map(approved, (activity, before, after))
    root = nodes[0].get('package', '') if nodes else ''
    root = root if package(root) and root in trusted else None
    scoped = [node for node in nodes if root and node.get('package') == root]
    resource_ids = set()
    for node in scoped:
        value = node.get('resource-id', '')
        if not isinstance(value, str) or len(value) > 160:
            continue
        match = re.fullmatch('(' + PACKAGE + r'):id/([A-Za-z_][A-Za-z0-9_.]*)', value)
        if match and match.group(1) in systems:
            resource_ids.add(value)
    valid_port = type(port) is int and 1 <= port <= 65535
    token = r'(?<![A-Za-z0-9_.])127\.0\.0\.1:' + str(port) + r'(?![A-Za-z0-9_])' if valid_port else None
    seen = bool(token and any(isinstance(node.get(key), str) and re.search(token, node.get(key))
                              for node in scoped for key in ('text', 'content-desc')))
    return {
        'scope': 'owned-app-or-verified-system-component-and-system-resource-ids-only',
        'activityComponent': activity, 'windowComponentBeforeTree': before, 'windowComponentAfterTree': after,
        'activityMatchesWindowBefore': bool(activity and activity == before),
        'windowStableAcrossTree': bool(before and before == after),
        'rootPackage': root,
        'rootMatchesActivity': bool(root and activity and root == activity.split('/')[0]),
        'rootMatchesWindowAfter': bool(root and after and root == after.split('/')[0]),
        'systemResourceIds': sorted(resource_ids)[:32], 'systemResourceIdsTruncated': len(resource_ids) > 32,
        'loopbackHostPortSeen': seen,
    }


def capture(adb, read_nodes, read_activity, owned, port):
    """Return JSON-safe facts. Each failed read is unavailable; no exception text escapes.

    ``owned`` must contain only fresh packages owned by the current harness run.
    No exit reason is inferred: pidof cannot establish why an app disappeared.
    Nonzero pidof (including no matching process) is unavailable because the adb
    callback does not expose an exit status separately from transport failures.
    """
    def sample(read, default):
        try:
            return read(), True
        except Exception:
            return default, False
    valid_owned = sorted({value for value in owned if package(value)}) if isinstance(owned, (set, list, tuple, frozenset)) else []
    owned_packages = valid_owned[:8]
    systems, systems_ok = sample(lambda: system_packages(adb('shell', 'pm', 'list', 'packages', '-s', timeout=5)), set())
    activity, activity_ok = sample(read_activity, None)
    before, before_ok = sample(lambda: window_component(adb('shell', 'dumpsys', 'window', timeout=5)), None)
    nodes, nodes_ok = sample(lambda: native_nodes(read_nodes()), [])
    after, after_ok = sample(lambda: window_component(adb('shell', 'dumpsys', 'window', timeout=5)), None)
    result = summarize(activity, before, after, nodes, systems, set(owned_packages), port)
    processes, process_reads = {}, {}
    for owner in owned_packages:
        processes[owner], process_reads[owner] = sample(lambda: process_alive(adb('shell', 'pidof', owner, timeout=3)), None)
    result.update(ownedProcessAlive=processes, ownedProcessPackagesTruncated=len(valid_owned) > 8,
                  exitReason=None, exitReasonAvailable=False)
    result['readsAvailable'] = {'systemPackages': systems_ok, 'activity': activity_ok, 'windowBeforeTree': before_ok,
                              'nativeTree': nodes_ok, 'windowAfterTree': after_ok, 'ownedProcesses': process_reads}
    return result
