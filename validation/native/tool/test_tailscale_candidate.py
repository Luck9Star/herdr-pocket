"""Offline provenance/ownership checks; no compiler, download or node start."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("candidate", Path(__file__).with_name("tailscale_candidate.py"))
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = self.root / "native"
        self.module = self.native / "tailscale-runtime"
        self.module.mkdir(parents=True)
        for name, text in {"go.mod": "module test\n", "go.sum": "fixed sums\n", "main.go": "package main\n"}.items():
            (self.module / name).write_text(text)
        (self.native / "patch").write_text("fixed patch")
        (self.native / "tests").write_text("fixed tests")
        self.source = {
            "goModSha256": candidate.digest(self.module / "go.mod"),
            "goSumSha256": candidate.digest(self.module / "go.sum"),
            "patch": {"path": "patch", "sha256": candidate.digest(self.native / "patch")},
            "patchTests": {"path": "tests", "sha256": candidate.digest(self.native / "tests")},
            "source": {"path": "tsnet/tsnet.go", "patchedSha256": candidate.digest(self.module / "main.go")},
        }
        self.manifest = self.native / "source.json"
        self.manifest.write_text(json.dumps(self.source))
        for name, value in [("NATIVE", self.native), ("MODULE", self.module), ("MANIFEST", self.manifest)]:
            p = patch.object(candidate, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.work = self.root / "work"
        (self.work / "upstream/tailscale/tsnet").mkdir(parents=True)
        (self.work / "candidate-source.json").write_text(json.dumps(self.source))
        (self.work / "upstream/tailscale/tsnet/tsnet.go").write_text("package main\n")
        (self.work / "upstream/tailscale/tsnet/herdr_explicit_auth_test.go").write_text("fixed tests")
        self.sync()

    def sync(self):
        with contextlib.redirect_stdout(io.StringIO()):
            candidate.sync_sources(self.work, self.source)

    def test_exact_candidate_and_fixed_locks(self):
        self.assertEqual(candidate.verify_sources(), self.source)
        candidate.verify_candidate(self.work, self.source)
        self.sync()
        self.assertEqual((self.work / "go.mod").read_text().count("replace tailscale.com"), 1)
        candidate.verify_candidate(self.work, self.source)

    def test_source_lock_drift_rejected(self):
        (self.module / "go.sum").write_text("changed")
        with self.assertRaisesRegex(ValueError, "fixed source mismatch"):
            candidate.verify_sources()

    def test_unsynced_source_rejected(self):
        (self.module / "main.go").write_text("package altered\n")
        with self.assertRaisesRegex(ValueError, "explicitly sync"):
            candidate.verify_candidate(self.work, self.source)

    def test_candidate_copy_drift_rejected(self):
        (self.work / "main.go").write_text("package altered\n")
        with self.assertRaisesRegex(ValueError, "candidate source changed"):
            candidate.verify_candidate(self.work, self.source)

    def test_local_replace_drift_rejected(self):
        (self.work / "go.mod").write_text("module malicious\n")
        with self.assertRaisesRegex(ValueError, "candidate source changed"):
            candidate.verify_candidate(self.work, self.source)

    def test_patch_test_drift_rejected(self):
        (self.work / "upstream/tailscale/tsnet/herdr_explicit_auth_test.go").write_text("bypassed")
        with self.assertRaisesRegex(ValueError, "patch tests changed"):
            candidate.verify_candidate(self.work, self.source)

    def test_unsafe_previous_inventory_rejected_before_mutation(self):
        sentinel = self.root / "keep.go"
        sentinel.write_text("protected")
        (self.work / "module-sources.json").write_text(json.dumps([{"path": "../keep.go"}]))
        with self.assertRaisesRegex(ValueError, "unsafe candidate source record"):
            self.sync()
        self.assertEqual(sentinel.read_text(), "protected")

    def test_symlink_source_rejected(self):
        (self.module / "alias.go").symlink_to(self.module / "main.go")
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            candidate.module_files()

    def test_symlink_destination_parent_rejected(self):
        (self.module / "nested").mkdir()
        (self.module / "nested/extra.go").write_text("new")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "extra.go").write_text("protected")
        (self.work / "nested").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unsafe candidate source destination"):
            self.sync()
        self.assertEqual((outside / "extra.go").read_text(), "protected")

    def test_prunes_only_recorded_sources(self):
        (self.work / "retained.log").write_text("keep")
        (self.module / "main.go").unlink()
        self.sync()
        self.assertFalse((self.work / "main.go").exists())
        self.assertEqual((self.work / "retained.log").read_text(), "keep")

    def test_artifact_source_rejected(self):
        (self.module / "libhp_tailscale.dylib").write_bytes(b"artifact")
        with self.assertRaisesRegex(ValueError, "unexpected file"):
            candidate.module_files()

    def test_prepare_never_overwrites(self):
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            candidate.prepare(self.work, self.root / "cache")

    def test_children_do_not_inherit_credentials_or_go_settings(self):
        with patch.dict(os.environ, {"TS_AUTHKEY": "synthetic", "GOPROXY": "untrusted", "HOME": "/synthetic"}), \
                patch.object(candidate.shutil, "which", return_value="/usr/local/bin/go"):
            _, env = candidate.environment(self.root / "cache")
        self.assertFalse(any(name in env for name in ["HOME", "TS_AUTHKEY", "GOENVFILE"]))
        self.assertEqual(env["GOPROXY"], "https://proxy.golang.org")
        self.assertEqual(env["GOENV"], "off")
        self.assertEqual(env["GOTOOLCHAIN"], "local")


if __name__ == "__main__":
    unittest.main()
