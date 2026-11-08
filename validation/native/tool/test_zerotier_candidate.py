"""Adversarial source-package tests; no external sources or nodes are required."""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import zerotier_candidate as candidate


class Sources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hp-zt-source-test-")
        self.root = Path(self.temp.name).resolve()
        self.archive = self.root / "source.tar.gz"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, entries):
        with tarfile.open(self.archive, "w:gz") as stream:
            for name, kind, value in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                    info.linkname = value
                    stream.addfile(info)
                elif kind == tarfile.REGTYPE:
                    info.size = len(value)
                    stream.addfile(info, io.BytesIO(value))
                else:
                    stream.addfile(info)

    def reject(self, entries):
        self.write(entries)
        with self.assertRaises(ValueError):
            candidate.extract(self.archive, self.root / "out", "fixed")
        self.assertFalse((self.root / "out").exists(), "validation precedes extraction")

    def test_exact_hash_required(self):
        path = self.root / "input"
        path.write_bytes(b"fixed")
        self.assertEqual(candidate.checked_cache(self.root, "input", hashlib.sha256(b"fixed").hexdigest()), path)
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            candidate.checked_cache(self.root, "input", hashlib.sha256(b"fixed").hexdigest())

    def test_cache_symlink_rejected(self):
        path = self.root / "input"
        path.write_bytes(b"fixed")
        (self.root / "alias").symlink_to(path)
        with self.assertRaises(ValueError):
            candidate.checked_cache(self.root, "alias", hashlib.sha256(b"fixed").hexdigest())

    def test_member_escape_rejected(self):
        for name in ("fixed/../escape", "/fixed/file", "fixed/./file", "fixed//file", "fixed/a\\b", "different/file"):
            with self.subTest(name=name):
                self.reject([(name, tarfile.REGTYPE, b"x")])

    def test_duplicate_member_rejected(self):
        self.reject([("fixed/file", tarfile.REGTYPE, b"a"), ("fixed/file", tarfile.REGTYPE, b"b")])

    def test_file_as_directory_rejected_in_both_orders(self):
        entries = [("fixed/a", tarfile.REGTYPE, b"a"), ("fixed/a/b", tarfile.REGTYPE, b"b")]
        for items in (entries, entries[::-1]):
            self.reject(items)

    def test_hard_links_and_devices_rejected(self):
        for kind in (tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            self.reject([("fixed/file", kind, "fixed/target")])

    def test_escaping_dangling_and_chained_symlinks_rejected(self):
        for target in ("../../escape", "/etc/passwd", "missing", "other", "..\\escape"):
            with self.subTest(target=target):
                self.reject([("fixed/data", tarfile.REGTYPE, b"safe"),
                             ("fixed/link", tarfile.SYMTYPE, target),
                             ("fixed/other", tarfile.SYMTYPE, "data")])

    def test_internal_link_materialized_without_following_filesystem(self):
        self.write([("fixed/dir/link", tarfile.SYMTYPE, "../data"), ("fixed/data", tarfile.REGTYPE, b"fixed")])
        links = candidate.extract(self.archive, self.root / "out", "fixed")
        path = self.root / "out/dir/link"
        self.assertEqual(path.read_bytes(), b"fixed")
        self.assertFalse(path.is_symlink())
        self.assertEqual(links[0]["target"], "../data")

    def test_symlink_cannot_be_member_parent(self):
        self.reject([("fixed/data", tarfile.REGTYPE, b"fixed"),
                     ("fixed/link", tarfile.SYMTYPE, "data"),
                     ("fixed/link/escape", tarfile.REGTYPE, b"unsafe")])

    def test_expansion_limit_includes_materialized_links(self):
        self.write([("fixed/data", tarfile.REGTYPE, b"four"), ("fixed/link", tarfile.SYMTYPE, "data")])
        with patch.object(candidate, "MAX_EXPANDED_BYTES", 7), self.assertRaises(ValueError):
            candidate.extract(self.archive, self.root / "out", "fixed")

    def test_member_limit(self):
        self.write([("fixed/a", tarfile.REGTYPE, b"a"), ("fixed/b", tarfile.REGTYPE, b"b")])
        with patch.object(candidate, "MAX_MEMBERS", 1), self.assertRaises(ValueError):
            candidate.extract(self.archive, self.root / "out", "fixed")

    def test_existing_source_never_overwritten(self):
        self.write([("fixed/file", tarfile.REGTYPE, b"new")])
        output = self.root / "out"
        output.mkdir()
        (output / "file").write_bytes(b"previous")
        with self.assertRaises(FileExistsError):
            candidate.extract(self.archive, output, "fixed")
        self.assertEqual((output / "file").read_bytes(), b"previous")

    def test_inventory_detects_extra_missing_changed(self):
        tree = self.root / "tree"
        tree.mkdir()
        path = tree / "a"
        path.write_bytes(b"one")
        before = candidate.inventory(tree)
        path.write_bytes(b"two")
        self.assertNotEqual(before, candidate.inventory(tree))
        path.unlink()
        self.assertNotEqual(before, candidate.inventory(tree))
        path.write_bytes(b"one")
        (tree / "extra").write_bytes(b"extra")
        self.assertNotEqual(before, candidate.inventory(tree))

    def test_reference_lock_hash_checked_before_parsing(self):
        path = self.root / "sources.lock"
        path.write_bytes(b"arbitrary shell cannot be evaluated")
        with self.assertRaisesRegex(ValueError, "blob mismatch"):
            candidate.verify_lock(path, {"reference": {"lockGitBlob": "0" * 40}})

    def test_candidate_manifest_inputs_and_hashes_valid(self):
        manifest = candidate.candidate_inputs()
        self.assertEqual(len(manifest["patches"]), 4)
        self.assertEqual(Path(manifest["patches"][-1]["path"]).name, "0008-streams-and-hp-boundary.patch")
        self.assertEqual(manifest["patches"][-1]["sha256"], "9bedbe9c9631fa31144774945b17f9cf315f0baa61812114e2dd73a66d6e4bd1")


if __name__ == "__main__":
    unittest.main()
