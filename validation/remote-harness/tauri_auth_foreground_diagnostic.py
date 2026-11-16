"""Bounded component/resource facts only; never exports raw Android dumps or text."""
import re

PACKAGE = r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*'
CLASS = r'[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*'


def component(value):
    if not isinstance(value, str) or len(value) > 256: return None
    match = re.fullmatch('(' + PACKAGE + r')/(\.?' + CLASS + ')', value)
    if not match: return None
    package, activity = match.groups()
    activity = package + activity if activity.startswith('.') else activity
    result = package + '/' + activity
    return result if len(result) <= 256 else None


def system_packages(raw):
    return {line[8:] for line in raw.splitlines()
            if line.startswith('package:') and re.fullmatch(PACKAGE, line[8:]) and len(line[8:]) <= 128}


def window_component(raw):
    values = {component(value) for value in re.findall(
        r'mCurrentFocus\s*=\s*Window\{[^\r\n]*?\bu0\s+([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)(?=[}\s])', raw)}
    values.discard(None)
    return next(iter(values)) if len(values) == 1 else None


def summarize(activity, before, after, nodes, systems, owned, port):
    trusted = systems | owned
    def approved(value):
        value = component(value)
        return value if value and value.split('/')[0] in trusted else None
    activity, before, after = map(approved, (activity, before, after))
    root = nodes[0].get('package', '') if nodes else ''
    root = root if root in trusted and re.fullmatch(PACKAGE, root) and len(root) <= 128 else None
    scoped = [node for node in nodes if root and node.get('package') == root]
    resource_ids = set()
    for node in scoped:
        value = node.get('resource-id', '')
        match = re.fullmatch('(' + PACKAGE + r'):id/([A-Za-z_][A-Za-z0-9_.]*)', value)
        if match and match.group(1) in systems and len(value) <= 160:
            resource_ids.add(value)
    valid_port = type(port) is int and 1 <= port <= 65535
    token = r'(?<![0-9.])127\.0\.0\.1:' + str(port) + r'(?![0-9])'
    seen = valid_port and any(re.search(token, node.get(key, ''))
                            for node in scoped for key in ('text', 'content-desc'))
    return {
        'scope': 'owned-app-or-verified-system-component-and-system-resource-ids-only',
        'activityComponent': activity, 'windowComponentBeforeTree': before, 'windowComponentAfterTree': after,
        'activityMatchesWindowBefore': bool(activity and activity == before),
        'windowStableAcrossTree': bool(before and before == after),
        'rootPackage': root,
        'rootMatchesActivity': bool(root and activity and root == activity.split('/')[0]),
        'rootMatchesWindowAfter': bool(root and after and root == after.split('/')[0]),
        'systemResourceIds': sorted(resource_ids)[:32], 'systemResourceIdsTruncated': len(resource_ids) > 32,
        'loopbackHostPortSeen': bool(seen),
    }


def capture(adb, read_nodes, read_activity, owned, port):
    def sample(read, default):
        try: return read(), True
        except Exception: return default, False
    systems, systems_ok = sample(lambda: system_packages(adb('shell', 'pm', 'list', 'packages', '-s', timeout=10)), set())
    activity, activity_ok = sample(read_activity, None)
    before, before_ok = sample(lambda: window_component(adb('shell', 'dumpsys', 'window', timeout=10)), None)
    nodes, nodes_ok = sample(read_nodes, [])
    after, after_ok = sample(lambda: window_component(adb('shell', 'dumpsys', 'window', timeout=10)), None)
    result = summarize(activity, before, after, nodes, systems, set(owned), port)
    result['readsAvailable'] = {'systemPackages': systems_ok, 'activity': activity_ok, 'windowBeforeTree': before_ok,
                                'nativeTree': nodes_ok, 'windowAfterTree': after_ok}
    return result
