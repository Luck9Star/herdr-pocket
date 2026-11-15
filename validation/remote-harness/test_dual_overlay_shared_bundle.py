import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dual_overlay_shared_bundle as shared


class SharedBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = 'a' * 40
        self.elf = b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 62) + b'fixture'
        self.peers = self.root / 'peers'; self.peers.mkdir()
        for name in ('peer', 'ts-fixture'):
            (self.peers / name).write_bytes(self.elf + name.encode())
        self.record = {'schemaVersion': 1, 'sourceSHA': self.source, 'platform': 'linux-x86_64',
            'toolchains': shared.TOOLCHAINS,
            'heelerCommit': '6a2817fc02aeb552df251d9478753c22fd4738bb',
            'easytierCommit': '728ba94b5029240add6204eed591f22e4e039e6b',
            'tailscaleCommit': '9a522a9786c97eb7910c01ccb7bd66557b04c910',
            'materials': shared.materials(),
            'files': {name: shared.digest(self.peers / name) for name in ('peer', 'ts-fixture')}}
        self.write_record()

    def tearDown(self):
        self.temp.cleanup()

    def write_record(self):
        (self.peers / 'peer-manifest.json').write_text(json.dumps(self.record))

    def input_fixture(self):
        fixture = self.root / 'input-fixture'; fixture.mkdir()
        binary = self.elf + b'herdr'
        (fixture / 'herdr').write_bytes(binary)
        patch_file = shared.ROOT / 'validation/herdr-input-extension/herdr-0.9.5-pocket-input.patch'
        shutil.copyfile(patch_file, fixture / patch_file.name)
        record = {'sourceSHA': self.source, 'upstreamSHA': shared.bootstrap.HERDR_COMMIT,
                  'patchSHA256': hashlib.sha256(patch_file.read_bytes()).hexdigest(),
                  'buildProfile': 'dev', 'configDirectory': 'herdr', 'scope': 'isolated validation fixture',
                  'binaryDebugAssertions': False, 'readinessAndCapabilitySmokePassed': True,
                  'binarySHA256': hashlib.sha256(binary).hexdigest()}
        (fixture / 'manifest.json').write_text(json.dumps(record))
        return fixture

    def test_same_source_assemble_and_download_integrity(self):
        fixture = self.input_fixture(); output = self.root / 'out'
        with patch.dict(os.environ, RUNNER_TEMP=str(self.root), GITHUB_SHA=self.source):
            shared.assemble(self.peers, fixture, output, self.source)
        manifest = shared.verify(output, self.source)
        self.assertEqual(set(manifest['files']), set(shared.NAMES))
        self.assertEqual(manifest['platform'], 'linux-x86_64')
        (output / 'peer').write_bytes(self.elf + b'tampered')
        with self.assertRaisesRegex(ValueError, 'bundle_digest_mismatch'):
            shared.verify(output, self.source)

    def test_consumer_uses_explicit_host_checkout_not_runner_sha(self):
        self.source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=shared.ROOT, text=True).strip()
        self.record['sourceSHA'] = self.source; self.write_record()
        fixture = self.input_fixture(); output = self.root / 'out'
        with patch.dict(os.environ, RUNNER_TEMP=str(self.root), GITHUB_SHA=self.source):
            shared.assemble(self.peers, fixture, output, self.source)
        for name in shared.NAMES:
            (output / name).chmod(0o600)
        env = dict(os.environ, GITHUB_SHA='b' * 40)
        command = [sys.executable, str(shared.HARNESS / 'dual_overlay_shared_bundle.py'),
                   'verify', '--bundle', str(output), '--source-sha', self.source, '--restore-executable']
        result = subprocess.run(command, cwd=shared.ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue(all((output / name).stat().st_mode & 0o700 == 0o700 for name in shared.NAMES))
        command[command.index(self.source)] = 'c' * 40
        self.assertNotEqual(subprocess.run(command, cwd=shared.ROOT, env=env,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode, 0)

    def test_peer_bundle_rejects_extra_file_and_symlink(self):
        (self.peers / 'credentials').write_text('fixture')
        with self.assertRaisesRegex(ValueError, 'bundle_inventory_invalid'):
            shared.verify_peer_bundle(self.peers, self.source)
        (self.peers / 'credentials').unlink()
        (self.peers / 'peer').unlink()
        (self.peers / 'peer').symlink_to(self.peers / 'ts-fixture')
        with self.assertRaisesRegex(ValueError, 'bundle_inventory_invalid'):
            shared.verify_peer_bundle(self.peers, self.source)

    def test_rejects_unexpected_manifest_fields(self):
        self.record['identity'] = 'must-not-be-in-bundle'
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'peer_manifest_invalid'):
            shared.verify_peer_bundle(self.peers, self.source)

    def test_rejects_changed_source_material_and_wrong_commit(self):
        with self.assertRaisesRegex(ValueError, 'peer_manifest_invalid'):
            shared.verify_peer_bundle(self.peers, 'b' * 40)
        self.record['materials'][next(iter(self.record['materials']))] = '0' * 64
        self.write_record()
        with self.assertRaisesRegex(ValueError, 'peer_manifest_invalid'):
            shared.verify_peer_bundle(self.peers, self.source)

    def test_rejects_wrong_executable_architecture(self):
        path = self.peers / 'peer'
        path.write_bytes(b'\x7fELF\x02\x01' + bytes(10) + struct.pack('<HH', 3, 183))
        self.record['files']['peer'] = shared.digest(path); self.write_record()
        with self.assertRaisesRegex(ValueError, 'linux_x86_64_executable_required'):
            shared.verify_peer_bundle(self.peers, self.source)


if __name__ == '__main__':
    unittest.main()
