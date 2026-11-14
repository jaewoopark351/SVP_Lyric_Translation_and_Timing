"""Public legacy CLI and report-only compatibility regression."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from svp_alignment.profiles.counting_stars import ROOT, SOURCE, TARGET, NOTES, LYRICS, REPORT, LEGACY_INPUT_NAMES

BASELINE = {
    "Counting Stars - Lyric verification.csv": "ada2120a82b43dc6f6931721a19da1ed9e71a9e04c8a1089af3b181c4bd50339",
    "Counting Stars - Note comparison.csv": "27d4cb60ffb6685a81a8d6608db84d281580b6e8d49b78486b1499db6a0dbb7c",
    "Counting Stars - Verification.md": "09847c12eee94fbb42840cee3af5a84d440f188320b71a699fb7e766eb18a318",
    "OneRepublic - Counting Stars 여자 커버_TIMING_FIXED.svp": "2c242e767cabb70be64a95e31e7db28ac99ac53e4c548d2cf4bb83da78f80a8c",
}


class LegacyCliTests(unittest.TestCase):
    def test_original_outputs_collision_and_report_only_contract(self):
        if not all((SOURCE / name).is_file() for name in LEGACY_INPUT_NAMES):
            self.skipTest("Verified local legacy input files unavailable")
        base = ROOT / "work" / "gui-validation"
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="legacy-", dir=base) as temporary:
            folder = Path(temporary).resolve()
            self.assertTrue(folder.is_relative_to(base.resolve()))
            destination = folder / "새 결과"
            command = [sys.executable, "-B", str(ROOT / "work" / "counting_stars" / "run.py"), "--output", str(destination)]
            first = subprocess.run(command, cwd=folder, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(0, first.returncode, first.stderr)
            summary = json.loads(first.stdout)
            self.assertEqual((715, 527), (summary["note_rows"], summary["lyric_rows"]))
            for name, digest in BASELINE.items():
                self.assertEqual(digest, hashlib.sha256((destination / name).read_bytes()).hexdigest(), name)
            collision = subprocess.run(command, cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(0, collision.returncode)
            for name, digest in BASELINE.items():
                self.assertEqual(digest, hashlib.sha256((destination / name).read_bytes()).hexdigest(), name)
            status = "NOT_RUN: compatibility test"
            report_only = subprocess.run(command + ["--report-only", "--studio-status", status], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(0, report_only.returncode, report_only.stderr)
            self.assertIn(status, (destination / REPORT).read_text(encoding="utf-8"))
            self.assertEqual(BASELINE[TARGET], hashlib.sha256((destination / TARGET).read_bytes()).hexdigest())
            saved_report = (destination / REPORT).read_bytes()
            repeat = subprocess.run(command + ["--report-only", "--studio-status", "different"], cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(0, repeat.returncode)
            self.assertEqual(saved_report, (destination / REPORT).read_bytes())


if __name__ == "__main__":
    unittest.main()
