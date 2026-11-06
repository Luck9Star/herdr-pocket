#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/network-vault-jvm.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
javac -d "$tmp" "$here/NetworkSecretStoreCore.java" "$here/EasyTierConfigBuilder.java" "$here/tests/NetworkSecretStoreCoreTest.java" "$here/tests/EasyTierConfigTest.java"
java -cp "$tmp" org.herdr.network.NetworkSecretStoreCoreTest
java -cp "$tmp" org.herdr.network.EasyTierConfigTest "$tmp/synthetic.toml"
python3 - "$tmp/synthetic.toml" <<'PY'
import pathlib, sys, tomllib, uuid
cfg = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
assert set(cfg) == {'instance_id', 'dhcp', 'listeners', 'network_identity', 'peer', 'flags'}
assert uuid.UUID(cfg['instance_id']).version == 4
assert cfg['dhcp'] is True and cfg['listeners'] == [] and cfg['flags'] == {'no_tun': True}
assert cfg['network_identity'] == {'network_name': '中文"\\quoted', 'network_secret': '假密码"\\\t\n\u0085'}
assert cfg['peer'] == [{'uri': 'tcp://example.com:11010'}, {'uri': 'wss://example.org/path'}]
print('PASS: synthetic TOML independently parsed with Python tomllib')
PY
