"""Persistence, provenance, and path isolation for dropped GUI inputs."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from svp_alignment.jobs.uploads import UploadStore
from svp_alignment.profiles.counting_stars import ROOT, SOURCE_HASHES, default_input_paths


class _NamedPath(str):
    pass


class GuiUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = ROOT / "work" / "gui-validation"
        cls.base.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="uploads-", dir=self.base)
        self.workspace = Path(self.temporary.name).resolve()
        self.assertTrue(self.workspace.is_relative_to(self.base.resolve()))
        self.project = self.workspace / "프로젝트 폴더"
        self.project.mkdir()
        self.store = UploadStore(self.project)
        self.sources = self.workspace / "원본 파일"
        self.sources.mkdir()
        self.txt = self.sources / "원본 가사.TXT"
        self.txt.write_text("가사 원본\nrepeat repeat\n", encoding="utf-8")
        self.original = self.txt.read_bytes()

    def tearDown(self):
        self.assertEqual(self.original, self.txt.read_bytes())
        self.assertTrue(self.workspace.resolve().is_relative_to(self.base.resolve()))
        self.temporary.cleanup()

    def test_copy_preserves_name_hash_and_original(self):
        saved = Path(self.store.save(self.txt, "txt"))
        self.assertEqual(self.txt.name, saved.name)
        self.assertTrue(saved.is_relative_to(self.project / "work" / "uploads"))
        self.assertEqual(self.original, saved.read_bytes())
        self.assertTrue(self.store.managed(saved, "txt"))
        manifest = json.loads((saved.parent / "manifest.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(self.original).hexdigest()
        self.assertEqual(digest, manifest["source_sha256"])
        self.assertEqual(digest, manifest["copied_sha256"])
        self.assertEqual(self.txt.name, manifest["original_name"])
        self.assertNotIn("source_path", manifest)
        self.assertEqual(self.project, self.store.root)

    def test_duplicate_original_names_never_overwrite(self):
        first = Path(self.store.save(str(self.txt), "txt"))
        second = Path(self.store.save(str(self.txt), "txt"))
        self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(first.name, second.name)
        self.assertEqual(self.original, first.read_bytes())
        self.assertEqual(self.original, second.read_bytes())

    def test_existing_collection_is_preserved_on_id_collision(self):
        import uuid
        fixed = uuid.UUID("78db98df-e646-499f-8906-e17bdb3022ec")
        with patch("svp_alignment.jobs.uploads.uuid.uuid4", return_value=fixed):
            first = Path(self.store.save(self.txt, "txt"))
            with self.assertRaises(FileExistsError):
                self.store.save(self.txt, "txt")
        self.assertEqual(self.original, first.read_bytes())
        self.assertTrue(self.store.managed(first, "txt"))
        self.assertEqual([first.parent], list(self.store.storage.iterdir()))

    def test_gradio_string_original_name_is_preserved(self):
        cached = self.sources / "opaque-cache-file"
        cached.write_bytes(self.original)
        incoming = _NamedPath(str(cached))
        incoming.orig_name = "사용자가 고른 가사.txt"
        saved = Path(self.store.save(incoming, "txt"))
        self.assertEqual(incoming.orig_name, saved.name)
        self.assertTrue(self.store.managed(saved, "txt"))
        fallback = _NamedPath(str(self.txt))
        fallback.orig_name = None
        self.assertEqual(self.txt.name, Path(self.store.save(fallback, "txt")).name)

    def test_bad_kind_missing_file_and_wrong_extension_fail_without_uploads(self):
        for source, kind in ((self.txt, "svp"), (None, "txt"), (self.txt, "pdf"),
                             (self.sources / "missing.txt", "txt")):
            with self.subTest(source=source, kind=kind):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.store.save(source, kind)
        self.assertFalse(self.store.storage.exists())
        self.assertFalse(self.store.managed(self.txt, "invalid"))
        self.assertFalse(self.store.managed(None, "txt"))

    def test_original_name_cannot_traverse_or_use_windows_special_names(self):
        for filename in ("../escaped.txt", "..\\escaped.txt", "C:\\escaped.txt",
                         "CON.txt", "safe.txt ", "bad:name.txt", "bad\x00.txt"):
            with self.subTest(filename=filename):
                incoming = _NamedPath(str(self.txt))
                incoming.orig_name = filename
                with self.assertRaises(ValueError):
                    self.store.save(incoming, "txt")
        self.assertFalse(self.store.storage.exists())

    def test_recovery_requires_valid_manifest_and_matching_file(self):
        saved = Path(self.store.save(self.txt, "txt"))
        self.assertFalse(self.store.managed(saved, "wav"))
        self.assertFalse(self.store.managed(self.txt, "txt"))
        self.assertFalse(self.store.managed("../outside.txt", "txt"))
        saved.write_bytes(b"changed")
        self.assertFalse(self.store.managed(saved, "txt"))
        saved.write_bytes(self.original)
        (saved.parent / "manifest.json").write_text("{}", encoding="utf-8")
        self.assertFalse(self.store.managed(saved, "txt"))

    def test_failed_copy_removes_its_unpublished_staging_files(self):
        import svp_alignment.jobs.uploads as uploads
        digest = uploads._digest
        calls = []
        def changed_hash(file):
            calls.append(Path(file))
            return "changed" if len(calls) == 3 else digest(Path(file))
        with patch("svp_alignment.jobs.uploads._digest", side_effect=changed_hash):
            with self.assertRaises(ValueError):
                self.store.save(self.txt, "txt")
        self.assertTrue(self.store.storage.is_dir())
        self.assertEqual([], list(self.store.storage.iterdir()))

    def test_source_copies_can_be_recovered_after_store_restart(self):
        saved = self.store.save(self.txt, "txt")
        restarted = UploadStore(self.project)
        self.assertTrue(restarted.managed(saved, "txt"))
        Path(saved).unlink()
        self.assertFalse(restarted.managed(saved, "txt"))

    def _link_directory(self, link, destination):
        if os.name == "nt":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                                    capture_output=True, check=False)
            if result.returncode:
                self.skipTest("Directory junction creation unavailable")
        else:
            link.symlink_to(destination, target_is_directory=True)

    def _unlink_directory(self, link):
        self.assertTrue(link.absolute().is_relative_to(self.workspace))
        self.assertTrue(link.resolve().is_relative_to(self.workspace))
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()

    def test_storage_root_link_cannot_redirect_copies(self):
        outside = self.workspace / "outside uploads"
        outside.mkdir()
        self.store.storage.parent.mkdir(parents=True)
        self._link_directory(self.store.storage, outside)
        try:
            with self.assertRaises(ValueError):
                self.store.save(self.txt, "txt")
            self.assertFalse(self.store.managed(outside / "fake.txt", "txt"))
            self.assertEqual([], list(outside.iterdir()))
        finally:
            self._unlink_directory(self.store.storage)

    def test_recovery_rejects_collection_link(self):
        saved = Path(self.store.save(self.txt, "txt"))
        outside = self.workspace / "moved collection"
        saved.parent.rename(outside)
        self._link_directory(saved.parent, outside)
        try:
            self.assertFalse(self.store.managed(saved, "txt"))
        finally:
            self._unlink_directory(saved.parent)

    def test_real_supported_inputs_copy_without_modifying_sources(self):
        inputs = tuple(default_input_paths())
        if not all(source.is_file() for source in inputs):
            self.skipTest("Local verified Counting Stars inputs are unavailable")
        for source, kind, expected_hash in zip(inputs, ("svp", "txt", "wav"), SOURCE_HASHES):
            with self.subTest(kind=kind):
                before = hashlib.sha256(source.read_bytes()).hexdigest()
                self.assertEqual(expected_hash, before)
                saved = Path(self.store.save(source, kind))
                self.assertEqual(before, hashlib.sha256(saved.read_bytes()).hexdigest())
                self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
                self.assertTrue(self.store.managed(saved, kind))


if __name__ == "__main__":
    unittest.main()
