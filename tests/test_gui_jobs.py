"""Regression and filesystem lifecycle checks for the local GUI backend."""
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from svp_alignment.jobs.manager import JobManager
from svp_alignment.pipeline import inspect_paths, prepare_paths
from svp_alignment.profiles.counting_stars import ROOT, TARGET, NOTES, LYRICS, REPORT, default_input_paths
from svp_alignment.svp import read_svp
from svp_alignment.project import read_project
from svp_alignment.verification.lyrics_only import verify_lyrics_only
from svp_alignment.jobs.artifacts import digest_file


class GuiJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = tuple(default_input_paths())
        if not all(p.is_file() for p in cls.inputs):
            raise unittest.SkipTest("Local verified Counting Stars inputs are unavailable")
        cls.base = ROOT / "work" / "gui-validation"
        cls.base.mkdir(parents=True, exist_ok=True)
        cls.original_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.inputs]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="jobs-", dir=self.base)
        self.workspace = Path(self.temporary.name).resolve()
        self.assertTrue(self.workspace.is_relative_to(self.base.resolve()))
        self.manager = JobManager(root=self.workspace)

    def tearDown(self):
        self.assertEqual(self.original_hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.inputs])
        self.assertTrue(self.workspace.is_relative_to(self.base.resolve()))
        self.temporary.cleanup()

    def ready(self, paths=None):
        snapshot = self.manager.inspect(*(paths or self.inputs), model_choice='cached_counting_stars')
        self.assertEqual("READY", snapshot["status"])
        return snapshot["job_id"]

    def test_input_inspection_and_calculation_match_legacy_svp(self):
        summary = inspect_paths(*self.inputs)
        self.assertEqual((715, 527, 120), (summary["note_count"], summary["word_count"], summary["bpm"]))
        prepared = prepare_paths(*self.inputs)
        baseline = self.base / "legacy-baseline" / TARGET
        if baseline.is_file():
            self.assertEqual(read_svp(baseline), (prepared.updated, prepared.suffix))

    def test_generate_review_publish_and_recover(self):
        job_id = self.ready()
        review = self.manager.run(job_id)
        self.assertEqual("REVIEW_READY", review["status"])
        self.assertFalse(review["files"])
        self.assertEqual(715, len(review["comparison_rows"]))
        self.assertEqual(527, len(review["lyric_rows"]))
        self.assertIn("NOT_VERIFIED", review["report"])
        published = self.manager.export(job_id)
        self.assertEqual("COMPLETED", published["status"])
        self.assertEqual(set(review['input_summary']['artifact_names']),
                         {Path(p).name for p in published["files"]})
        self.assertTrue(Path(published['files'][0]).name.endswith('_LYRICS_FILLED.svp'))
        self.assertTrue(verify_lyrics_only(read_project(self.inputs[0], uploaded=True),
                                          read_svp(published['files'][0])[0]))
        self.assertEqual('UNCHANGED', published['summary']['timing'])
        for p in published["files"]:
            self.assertTrue(Path(p).resolve().is_relative_to(self.workspace / "outputs" / job_id))
        recovered = JobManager(root=self.workspace).recover(job_id)
        self.assertEqual("COMPLETED", recovered["status"])
        self.assertEqual(715, len(recovered["comparison_rows"]))
        self.assertEqual(published["files"], recovered["files"])

    def test_changed_original_cannot_be_run_after_inspection(self):
        copied = self.workspace / "가사 원본.txt"
        copied.write_bytes(self.inputs[1].read_bytes())
        job_id = self.ready((self.inputs[0], copied, self.inputs[2]))
        copied.write_bytes(copied.read_bytes() + b"\nchanged")
        result = self.manager.run(job_id)
        self.assertEqual("FAILED", result["status"])
        self.assertFalse(result["files"])
        self.assertFalse((self.workspace / "outputs" / job_id).exists())

    def test_cached_gui_only_changes_lyrics_and_never_calls_timing_pipeline(self):
        job_id = self.ready()
        with patch('svp_alignment.pipeline.prepare_paths', side_effect=AssertionError('legacy timing called')), \
                patch('svp_alignment.alignment.timing.time_notes', side_effect=AssertionError('timing called')):
            review = self.manager.run(job_id)
        self.assertEqual('REVIEW_READY', review['status'], review['error'])
        prepared = self.manager._job(job_id).prepared
        self.assertTrue(verify_lyrics_only(prepared.document, prepared.updated))
        self.assertTrue(any(row['old_lyrics'] != row['new_lyrics'] for row in review['comparison_rows']))
        self.assertTrue(all(row['old_onset_blick'] == row['new_onset_blick']
                            and row['old_duration_blick'] == row['new_duration_blick']
                            for row in review['comparison_rows']))

    def test_consistent_hash_cannot_hide_changed_note_duration(self):
        job_id = self.ready()
        self.manager.run(job_id)
        job = self.manager._job(job_id)
        name = self.manager.store.names(job)[0]
        output = self.workspace / 'work' / 'gradio' / job_id / 'draft' / name
        project, suffix = read_svp(output)
        locator = read_project(self.inputs[0], uploaded=True).target_notes()[0]['locator']
        note = project
        for part in locator:
            note = note[part]
        note['duration'] -= 1
        output.write_bytes(json.dumps(project, ensure_ascii=False).encode('utf-8') + suffix)
        job.artifact_hashes[name] = digest_file(output)
        failed = self.manager.snapshot(job_id)
        self.assertEqual('FAILED', failed['status'])
        self.assertFalse(failed['files'])

    def test_previous_review_cannot_be_exported_as_a_lyrics_only_job(self):
        job_id = self.ready()
        self.manager.run(job_id)
        manifest_path = self.workspace / 'work' / 'gradio' / job_id / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['input_summary'].pop('operation')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        restarted = JobManager(root=self.workspace)
        self.assertEqual('REVIEW_READY', restarted.recover(job_id)['status'])
        with self.assertRaisesRegex(ValueError, '이전 타이밍'):
            restarted.export(job_id)
        self.assertFalse((self.workspace / 'outputs' / job_id).exists())

    def test_previous_completed_result_can_be_recovered_without_rewriting(self):
        job_id = self.ready()
        self.manager.run(job_id)
        published = self.manager.export(job_id)
        before = {p: digest_file(p) for p in published['files']}
        manifest_path = self.workspace / 'work' / 'gradio' / job_id / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['input_summary'].pop('operation')
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        recovered = JobManager(root=self.workspace).recover(job_id)
        self.assertEqual('COMPLETED', recovered['status'])
        self.assertEqual(published['files'], recovered['files'])
        self.assertEqual(before, {p: digest_file(p) for p in recovered['files']})

    def test_cancel_at_calculation_boundary_has_no_downloads(self):
        job_id = self.ready()
        def progress(label, fraction):
            if fraction >= 0.4:
                self.manager.cancel(job_id)
        result = self.manager.run(job_id, progress=progress)
        self.assertEqual("CANCELLED", result["status"])
        self.assertFalse(result["files"])
        self.assertFalse((self.workspace / "outputs" / job_id).exists())

    def test_output_collision_preserves_existing_directory(self):
        job_id = self.ready()
        self.manager.run(job_id)
        target = self.workspace / "outputs" / job_id
        target.mkdir(parents=True)
        sentinel = target / "existing.txt"
        sentinel.write_text("keep", encoding="utf-8")
        result = self.manager.export(job_id)
        self.assertEqual("FAILED", result["status"])
        self.assertFalse(result["files"])
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
        self.assertEqual(["existing.txt"], [p.name for p in target.iterdir()])

    def test_failed_copy_does_not_publish_partial_bundle(self):
        job_id = self.ready()
        self.manager.run(job_id)
        with patch("svp_alignment.jobs.artifacts.shutil.copyfile", side_effect=OSError("simulated write failure")):
            result = self.manager.export(job_id)
        self.assertEqual("FAILED", result["status"])
        self.assertFalse(result["files"])
        self.assertFalse((self.workspace / "outputs" / job_id).exists())
        self.assertFalse(list((self.workspace / "outputs").glob(".publish-*")))

    def test_recovery_rejects_tampered_result(self):
        job_id = self.ready()
        self.manager.run(job_id)
        published = self.manager.export(job_id)
        Path(published["files"][0]).write_bytes(b"tampered")
        recovered = JobManager(root=self.workspace).recover(job_id)
        self.assertEqual("FAILED", recovered["status"])
        self.assertFalse(recovered["files"])

    def test_two_jobs_have_separate_results(self):
        ids = [self.ready(), self.ready()]
        with ThreadPoolExecutor(max_workers=2) as pool:
            reviews = list(pool.map(self.manager.run, ids))
        self.assertTrue(all(r["status"] == "REVIEW_READY" for r in reviews))
        published = [self.manager.export(job_id) for job_id in ids]
        self.assertTrue(all(r["status"] == "COMPLETED" for r in published))
        self.assertFalse(set(published[0]["files"]) & set(published[1]["files"]))

    def test_stale_session_revision_cannot_bind_new_job(self):
        revision = self.manager.session_revision("session-a")
        job_id = self.ready()
        self.manager.invalidate_session("session-a")
        self.assertFalse(self.manager.bind_session("session-a", job_id, expected_revision=revision))
        self.assertIsNone(self.manager.current_session_job("session-a"))

    def test_preview_is_scoped_and_bounded(self):
        job_id = self.ready()
        clip = Path(self.manager.preview(job_id, 0, 1))
        self.assertTrue(clip.resolve().is_relative_to(self.workspace / "work" / "gradio" / job_id))
        import wave
        with wave.open(str(clip), "rb") as audio:
            self.assertEqual(44100, audio.getnframes())
        with self.assertRaises(ValueError):
            self.manager.preview(job_id, 0, 31)

    def test_job_ids_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            self.manager.recover("../../outputs")


    def test_same_manager_snapshot_rejects_tampered_result(self):
        job_id = self.ready()
        self.manager.run(job_id)
        published = self.manager.export(job_id)
        Path(published["files"][1]).write_bytes(b"modified comparison")
        snapshot = self.manager.snapshot(job_id)
        self.assertEqual("FAILED", snapshot["status"])
        self.assertFalse(snapshot["files"])

    def test_review_can_be_exported_after_server_restart(self):
        job_id = self.ready()
        self.manager.run(job_id)
        restarted = JobManager(root=self.workspace)
        restored = restarted.recover(job_id)
        self.assertEqual("REVIEW_READY", restored["status"])
        self.assertEqual(715, len(restored["comparison_rows"]))
        published = restarted.export(job_id)
        self.assertEqual("COMPLETED", published["status"])
        self.assertEqual(4, len(published["files"]))

    def test_interrupted_manifest_is_not_recovered_as_completed(self):
        job_id = self.ready()
        manifest_path = self.workspace / "work" / "gradio" / job_id / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "RUNNING"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        recovered = JobManager(root=self.workspace).recover(job_id)
        self.assertEqual("FAILED", recovered["status"])
        self.assertFalse(recovered["files"])

    def test_progress_does_not_move_backwards(self):
        job_id = self.ready()
        fractions = []
        result = self.manager.run(job_id, progress=lambda label, fraction: fractions.append(fraction))
        self.assertEqual("REVIEW_READY", result["status"])
        self.assertEqual(sorted(fractions), fractions)
        self.assertTrue(all(0 <= value <= 1 for value in fractions))


if __name__ == "__main__":
    unittest.main()
