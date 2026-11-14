"""Direct Gradio callback and component checks; these do not verify browser layout."""

import asyncio
from functools import partial
import hashlib
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["GRADIO_TEMP_DIR"] = str(Path(__file__).resolve().parents[1] / "work" / "gradio_cache")
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

import gradio as gr

from svp_alignment.audio.model_catalog import MODEL_CHOICES
from svp_alignment.jobs.manager import JobManager
from svp_alignment.jobs.input_selection import InputSelectionRegistry
from svp_alignment.jobs.uploads import UploadStore
from svp_alignment.profiles.counting_stars import ROOT, default_input_paths
from svp_alignment.ui.callbacks import OUTPUT_COUNT, input_signature, make_callbacks
from svp_alignment.ui.gradio_app import build_app
from svp_alignment.ui.presentation import filtered_notes, model_text, report_text, review_text, status_text
from svp_alignment.ui.upload_callbacks import make_upload_callbacks, resolve_uploaded_inputs

CACHED_MODEL = "cached_counting_stars"


def cached_callbacks(manager, **kwargs):
    """Explicitly select saved observations so lifecycle tests never run a model."""
    callbacks = make_callbacks(manager, **kwargs)
    for name in ("inspect", "run", "cancel", "export", "filter", "preview", "select_note", "select_lyric"):
        callbacks[name] = partial(callbacks[name], model_choice=CACHED_MODEL)
    return callbacks


def source_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class GuiUiDisplayTests(unittest.TestCase):
    def test_components_are_read_only_and_run_callbacks_share_full_lifetime_queue(self):
        async def construct():
            return build_app(manager=JobManager(root=ROOT))
        app = asyncio.run(construct())
        self.addCleanup(app.close, verbose=False)
        self.assertEqual("SVP 기존 음표에 가사 넣기", app.title)
        components = {component.elem_id: component for component in app.blocks.values()
                      if getattr(component, "elem_id", None)}
        for name in ("notes-table", "lyrics-table", "source-audio", "downloads", "job-id"):
            self.assertFalse(components[name].interactive, name)
        self.assertFalse(components["run"].interactive)
        self.assertFalse(components["export"].interactive)
        self.assertEqual("기존 음표에 가사 넣기", components["run"].value)
        for kind in ("svp", "txt", "wav"):
            component = components[f"{kind}-upload"]
            self.assertIsInstance(component, gr.File)
            self.assertEqual("single", component.file_count)
            self.assertEqual([f".{kind}"], component.file_types)
            self.assertIsNone(component.value)
        self.assertEqual("multiple", components["downloads"].file_count)
        self.assertEqual([], components["source-audio"].buttons)
        self.assertEqual("auto", components["model-choice"].value)
        self.assertEqual(list(MODEL_CHOICES), components["model-choice"].choices)
        events = {event.fn.__name__: event for event in app.fns.values()}
        for name in ("inspect_inputs", "run", "export", "recover", "apply_correction"):
            self.assertTrue(events[name].queue, name)
            self.assertEqual("svp-alignment", events[name].concurrency_id)
            self.assertEqual(1, events[name].concurrency_limit)
        self.assertFalse(events["cancel"].queue)
        for kind in ("svp", "txt", "wav"):
            self.assertFalse(events[f"upload_{kind}"].queue)
            self.assertFalse(events[f"clear_{kind}"].queue)
        self.assertTrue(all(event.api_visibility == "private" for event in app.fns.values()))
        for name in ("inspect_inputs", "run", "cancel", "export", "filter_rows",
                     "select_note", "select_lyric", "preview", "select_correction", "apply_correction"):
            self.assertEqual("model-choice", events[name].inputs[-1 if name == "preview" else -2].elem_id, name)
        self.assertEqual("all", components["quality-filter"].value)
        self.assertEqual(8, len(events["select_correction"].outputs))
        self.assertEqual(OUTPUT_COUNT + 8, len(events["apply_correction"].outputs))
        model_events = [event for event in app.fns.values()
                        if event.fn.__name__ == "invalidate"
                        and any(target[0] == components["model-choice"]._id for target in event.targets)]
        self.assertEqual(1, len(model_events))
        self.assertFalse(model_events[0].queue)
        # The screen owns job/input identifiers and a small revision-bound correction selection.
        states = [component for component in app.blocks.values() if isinstance(component, gr.State)]
        self.assertEqual(3, len(states))
        self.assertTrue(all(component.value is None for component in states))

    def test_lyrics_only_review_states_full_note_preservation_without_legacy_timing_warning(self):
        snapshot = {
            "status": "REVIEW_READY", "stage": "검토 준비",
            "input_summary": {"mode": "general", "operation": "lyrics_only"},
            "comparison_rows": [], "lyric_rows": [], "report": "new report",
            "summary": {"parse": "PASS", "preservation": "PASS"},
        }
        text = review_text(snapshot)
        self.assertIn("원본 음표 시간 고정", text)
        self.assertIn("가사 외 전체 필드 보존: **PASS**", text)
        self.assertNotIn("이전 타이밍 수정 작업", text)
        self.assertNotIn("이전 타이밍 수정 작업", status_text(snapshot))
        self.assertEqual("new report", report_text(snapshot))

    def test_previous_timing_job_review_status_and_report_are_explicitly_identified(self):
        for state in ("REVIEW_READY", "COMPLETED"):
            with self.subTest(state=state):
                snapshot = {
                    "status": state, "input_summary": {"mode": "general"},
                    "comparison_rows": [], "lyric_rows": [], "report": "original report",
                    "summary": {"parse": "PASS", "preservation": "PASS"},
                }
                self.assertIn("이전 타이밍 수정 작업", status_text(snapshot))
                self.assertIn("이전 타이밍 수정 작업", review_text(snapshot))
                self.assertIn("이전 타이밍 수정 작업 보고서", report_text(snapshot))
                self.assertTrue(report_text(snapshot).endswith("original report"))

    def test_review_shows_selected_and_resolved_model_without_claiming_cached_ai_run(self):
        snapshot = {"status": "REVIEW_READY",
                    "input_summary": {"operation": "lyrics_only", "mode": "general",
                                      "model_choice": "auto", "model_id": "WAV2VEC2_ASR_LARGE_LV60K_960H"}}
        self.assertIn("WAV2VEC2_ASR_LARGE_LV60K_960H", status_text(snapshot))
        self.assertIn("WAV2VEC2_ASR_LARGE_LV60K_960H", review_text(snapshot))
        snapshot["input_summary"].update(mode="counting_stars", model_choice=CACHED_MODEL, model_id=None)
        self.assertIn("새 AI 모델 분석은 실행하지 않습니다", model_text(snapshot))

    def test_qwen_review_explains_word_only_unknown_for_new_and_recovered_jobs(self):
        qwen = "Qwen/Qwen3-ForcedAligner-0.6B"
        for recorded_in_input in (True, False):
            with self.subTest(recorded_in_input=recorded_in_input):
                snapshot = {
                    "status": "REVIEW_READY",
                    "input_summary": {"operation": "lyrics_only", "mode": "general",
                                      "model_choice": "auto", "model_id": qwen if recorded_in_input else None},
                    "summary": {"provenance": {"model_id": qwen}},
                    "comparison_rows": [{"assignment": "UNKNOWN"}],
                    "lyric_rows": [{"status": "UNKNOWN", "note_numbers": "1"}],
                }
                text = review_text(snapshot)
                self.assertIn("단어 시간 범위만 제공", text)
                self.assertIn("개별 음절·문자 시각과 신뢰도 점수는 제공하지 않습니다", text)
                self.assertIn("가사 후보는 UNKNOWN", text)
                self.assertIn("원본 음표 시간 고정", text)
                snapshot["input_summary"]["model_id"] = "WAV2VEC2_ASR_LARGE_LV60K_960H"
                snapshot["summary"]["provenance"]["model_id"] = "WAV2VEC2_ASR_LARGE_LV60K_960H"
                self.assertNotIn("단어 시간 범위만 제공", review_text(snapshot))


class GuiUiCallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = tuple(default_input_paths())
        if not all(path.is_file() for path in cls.inputs):
            raise unittest.SkipTest("Local verified Counting Stars inputs are unavailable")
        cls.paths = tuple(map(str, cls.inputs))
        cls.original_hashes = [source_hash(path) for path in cls.inputs]
        cls.base = (ROOT / "work" / "gui-validation").resolve()
        cls.base.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        if cls.original_hashes != [source_hash(path) for path in cls.inputs]:
            raise AssertionError("A UI callback changed an original input")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ui-", dir=self.base)
        self.workspace = Path(self.temporary.name).resolve()
        self.assertTrue(self.workspace.is_relative_to(self.base))
        self.manager = JobManager(root=self.workspace)
        self.store = UploadStore(root=self.workspace)
        self.selections = InputSelectionRegistry()
        self.callbacks = cached_callbacks(
            self.manager,
            resolve_inputs=lambda svp, txt, wav, request: resolve_uploaded_inputs(
                self.store, self.selections, svp, txt, wav, request),
            reset_inputs=self.selections.reset,
        )
        self.uploads = make_upload_callbacks(
            self.manager, self.store, self.selections,
            self.callbacks["reset_view"], self.callbacks["skip_view"])
        self.request = SimpleNamespace(session_hash="direct-ui-session")

    def tearDown(self):
        # Verify the exact temporary cleanup target before recursive removal on Windows.
        self.assertTrue(self.workspace.is_relative_to(self.base))
        self.assertNotEqual(self.workspace, self.base)
        self.temporary.cleanup()

    def ready(self):
        for kind, filename in zip(("svp", "txt", "wav"), self.paths):
            self.uploads[f"upload_{kind}"](filename, self.request)
        outputs = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
        self.assertEqual(OUTPUT_COUNT, len(outputs))
        self.assertEqual("READY", self.manager.snapshot(outputs[0])["status"])
        self.assertEqual(outputs[0], self.manager.current_session_job(self.request.session_hash))
        self.assertEqual(input_signature(*self.paths, model_choice=CACHED_MODEL), outputs[1])
        self.assertTrue(outputs[10]["interactive"])
        return outputs[0], outputs[1]

    def bound_inputs(self, job_id, signature):
        return (job_id, signature, *self.paths, False, False, 100, self.request)

    def assert_skipped(self, outputs, count=OUTPUT_COUNT):
        self.assertEqual(count, len(outputs))
        self.assertTrue(all(value == gr.skip() for value in outputs), outputs)

    def test_full_callback_flow_and_refresh_recovery(self):
        job_id, signature = self.ready()
        review = self.callbacks["run"](*self.bound_inputs(job_id, signature))
        self.assertEqual("REVIEW_READY", self.manager.snapshot(job_id)["status"])
        self.assertEqual(715, len(review[6]["data"]))
        self.assertEqual(527, len(review[7]["data"]))
        self.assertIsNone(review[9])
        self.assertTrue(review[11]["interactive"])
        self.assertIn("NOT_VERIFIED", review[5])
        self.assertIn("NOT_RUN", review[5])
        self.assertIn("원본 음표 시간 고정", review[5])
        self.assertIn("가사 외 전체 필드 보존: **PASS**", review[5])
        comparison = self.manager.snapshot(job_id)["comparison_rows"]
        self.assertTrue(all(row["old_start_s"] == row["new_start_s"]
                            and row["old_end_s"] == row["new_end_s"] for row in comparison))
        unknown = self.callbacks["filter"](job_id, signature, *self.paths, True, False, 100, self.request)
        self.assertEqual(183, len(unknown[0]["data"]))
        self.assertEqual(158, len(unknown[1]["data"]))
        for table in unknown:
            status_column = table["headers"].index("상태")
            self.assertTrue(all(row[status_column] == "UNKNOWN" for row in table["data"]))
        large = self.callbacks["filter"](job_id, signature, *self.paths, False, True, 100, self.request)
        self.assertEqual(len(filtered_notes(self.manager.snapshot(job_id), False, True, 100)),
                         len(large[0]["data"]))
        clip, message = self.callbacks["preview"](job_id, signature, *self.paths, 0, 1, self.request)
        self.assertTrue(Path(clip).resolve().is_relative_to(self.workspace / "work" / "gradio" / job_id))
        with wave.open(clip, "rb") as source:
            self.assertEqual(44100, source.getnframes())
        self.assertIn("원본 보컬", message)
        invalid_clip, _ = self.callbacks["preview"](job_id, signature, *self.paths, 0, 31, self.request)
        self.assertIsNone(invalid_clip)
        published = self.callbacks["export"](*self.bound_inputs(job_id, signature))
        self.assertEqual("COMPLETED", self.manager.snapshot(job_id)["status"])
        self.assertEqual(4, len(published[9]))
        for filename in published[9]:
            self.assertTrue(Path(filename).resolve().is_relative_to(self.workspace / "outputs" / job_id))
            self.assertTrue(Path(filename).is_file())
        refreshed = cached_callbacks(JobManager(root=self.workspace))
        recovered = refreshed["recover"](job_id, False, False, 100,
                                         SimpleNamespace(session_hash="after-refresh"))
        self.assertEqual(job_id, recovered[0])
        self.assertEqual(input_signature(None, None, None, model_choice=CACHED_MODEL), recovered[1])
        self.assertEqual(published[9], recovered[9])
        self.assertEqual((None, None, None), recovered[14:17])
        self.assertEqual(715, len(recovered[6]["data"]))
        self.assertEqual(527, len(recovered[7]["data"]))

    def test_input_change_clears_current_results_and_blocks_unchecked_signature(self):
        job_id, signature = self.ready()
        changed_paths = (self.paths[0], self.paths[1] + ".changed", self.paths[2])
        with patch.object(self.manager, "run") as execute:
            blocked = self.callbacks["run"](job_id, signature, *changed_paths,
                                             False, False, 100, self.request)
            execute.assert_not_called()
        self.assertIsNone(blocked[0])
        self.assertIsNone(blocked[9])
        cleared = self.callbacks["invalidate"](self.request)
        self.assertIsNone(self.manager.current_session_job(self.request.session_hash))
        for index in (0, 1, 9, 13):
            self.assertIsNone(cleared[index])
        self.assertFalse(cleared[10]["interactive"])
        self.assertFalse(cleared[11]["interactive"])

    def test_inspection_completed_after_edit_cannot_reattach_job(self):
        for kind, filename in zip(("svp", "txt", "wav"), self.paths):
            self.uploads[f"upload_{kind}"](filename, self.request)
        inspect_original = self.manager.inspect
        def inspect_then_edit(*paths, **kwargs):
            result = inspect_original(*paths, **kwargs)
            self.callbacks["invalidate"](self.request)
            return result
        with patch.object(self.manager, "inspect", side_effect=inspect_then_edit):
            outputs = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
        self.assert_skipped(outputs)
        self.assertIsNone(self.manager.current_session_job(self.request.session_hash))

    def test_run_completed_after_edit_cannot_reattach_results(self):
        job_id, signature = self.ready()
        def run_then_edit(*args, **kwargs):
            self.callbacks["invalidate"](self.request)
            return {"job_id": job_id, "status": "REVIEW_READY"}
        with patch.object(self.manager, "run", side_effect=run_then_edit):
            outputs = self.callbacks["run"](*self.bound_inputs(job_id, signature))
        self.assert_skipped(outputs)
        self.assertIsNone(self.manager.current_session_job(self.request.session_hash))

    def test_saved_completion_after_edit_stays_detached_but_can_be_recovered(self):
        job_id, signature = self.ready()
        self.callbacks["run"](*self.bound_inputs(job_id, signature))
        export_original = self.manager.export
        def export_then_edit(*args):
            result = export_original(*args)
            self.callbacks["invalidate"](self.request)
            return result
        with patch.object(self.manager, "export", side_effect=export_then_edit):
            outputs = self.callbacks["export"](*self.bound_inputs(job_id, signature))
        self.assert_skipped(outputs)
        self.assertEqual("COMPLETED", self.manager.snapshot(job_id)["status"])
        recovered = self.callbacks["recover"](job_id, False, False, 100, self.request)
        self.assertEqual(job_id, recovered[0])
        self.assertEqual(4, len(recovered[9]))

    def test_failed_inspection_recovery_is_visible_without_downloads(self):
        failed = self.manager.inspect("", "", "")
        self.assertEqual("FAILED", failed["status"])
        recovered = self.callbacks["recover"](failed["job_id"], False, False, 100, self.request)
        self.assertEqual(failed["job_id"], recovered[0])
        self.assertIn("FAILED", recovered[3])
        self.assertIsNone(recovered[9])
        self.assertEqual((None, None, None), recovered[14:17])

    def test_uploaded_inputs_are_immediately_persisted_and_inspected_from_project(self):
        job_id, _ = self.ready()
        saved = self.manager.snapshot(job_id)["paths"]
        for kind, expected_hash in zip(("svp", "txt", "wav"), self.original_hashes):
            copied = Path(saved[kind])
            self.assertTrue(copied.is_relative_to(self.workspace / "work" / "uploads"))
            self.assertEqual(expected_hash, source_hash(copied))
            self.assertTrue(self.store.managed(copied, kind))
        cleared = self.uploads["clear_txt"](self.request)
        self.assertIsNone(cleared[0])
        self.assertTrue(all(Path(filename).is_file() for filename in saved.values()))
        with patch.object(self.manager, "inspect") as inspect:
            blocked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
            inspect.assert_not_called()
        self.assertIsNone(blocked[0])

    def test_pending_or_missing_uploads_block_inspection(self):
        self.selections.begin(self.request.session_hash, "svp", self.paths[0])
        with patch.object(self.manager, "inspect") as inspect:
            blocked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
            inspect.assert_not_called()
        self.assertIsNone(blocked[0])
        self.assertIsNone(blocked[9])

    def test_late_upload_after_clear_cannot_restore_selection(self):
        save = self.store.save
        def save_then_clear(source, kind):
            destination = save(source, kind)
            self.uploads["clear_svp"](self.request)
            return destination
        with patch.object(self.store, "save", side_effect=save_then_clear):
            result = self.uploads["upload_svp"](self.paths[0], self.request)
        self.assert_skipped(result)
        with self.assertRaises(ValueError):
            self.selections.resolve(self.request.session_hash, self.paths)
        self.assertIsNone(self.manager.current_session_job(self.request.session_hash))

    def test_overlapping_different_file_uploads_keep_both_saved_selections(self):
        save = self.store.save
        def save_with_other_drop(source, kind):
            destination = save(source, kind)
            if kind == "svp":
                self.uploads["upload_txt"](self.paths[1], self.request)
            return destination
        with patch.object(self.store, "save", side_effect=save_with_other_drop):
            result = self.uploads["upload_svp"](self.paths[0], self.request)
        self.assert_skipped(result)
        self.uploads["upload_wav"](self.paths[2], self.request)
        checked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
        self.assertEqual("READY", self.manager.snapshot(checked[0])["status"])

    def test_recovered_job_uses_persistent_inputs_after_upload_cache_is_removed(self):
        import shutil
        cache = self.workspace / "browser-cache"
        cache.mkdir()
        cached = []
        for original in self.inputs:
            target = cache / original.name
            shutil.copyfile(original, target)
            cached.append(str(target))
        self.paths = tuple(cached)
        job_id, _ = self.ready()
        for filename in cached:
            Path(filename).unlink()
        cache.rmdir()
        refreshed = cached_callbacks(JobManager(root=self.workspace))
        request = SimpleNamespace(session_hash="after-cache-expiry")
        recovered = refreshed["recover"](job_id, False, False, 100, request)
        signature = recovered[1]
        self.assertEqual((None, None, None), recovered[14:17])
        review = refreshed["run"](job_id, signature, None, None, None, False, False, 100, request)
        self.assertTrue(review[11]["interactive"])
        published = refreshed["export"](job_id, signature, None, None, None, False, False, 100, request)
        self.assertEqual(4, len(published[9]))

    def test_changed_saved_upload_is_rejected_before_inspection(self):
        job_id, _ = self.ready()
        saved_txt = Path(self.manager.snapshot(job_id)["paths"]["txt"])
        saved_txt.write_text("changed upload copy", encoding="utf-8")
        with patch.object(self.manager, "inspect") as inspect:
            blocked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request)
            inspect.assert_not_called()
        self.assertIsNone(blocked[0])

    def test_recovered_csv_times_are_numeric_when_selecting_a_lyric(self):
        job_id, signature = self.ready()
        snapshot = {"comparison_rows": [
            {"note": "1", "old_start_s": "9.950", "old_end_s": "10.100"},
            {"note": "2", "old_start_s": "10.050", "old_end_s": "10.200"}],
            "lyric_rows": [{"note_numbers": "1 / 2", "unknown_start_s": ""}]}
        with patch.object(self.manager, "snapshot", return_value=snapshot):
            interval = self.callbacks["select_lyric"](*self.bound_inputs(job_id, signature),
                                                       SimpleNamespace(index=(0, 0)))
        self.assertEqual((9.7, 10.45), interval)

    def test_selected_note_and_lyric_preview_use_wav_clock_with_audio_offset(self):
        job_id, signature = self.ready()
        snapshot = {"input_summary": {"audio_offset": 10.0},
                    "comparison_rows": [{"note": 1, "old_start_s": 11.0, "old_end_s": 12.0}],
                    "lyric_rows": [{"note_numbers": "1", "unknown_start_s": ""}]}
        with patch.object(self.manager, "snapshot", return_value=snapshot):
            note = self.callbacks["select_note"](*self.bound_inputs(job_id, signature),
                                                   SimpleNamespace(index=(0, 0)))
            lyric = self.callbacks["select_lyric"](*self.bound_inputs(job_id, signature),
                                                     SimpleNamespace(index=(0, 0)))
        self.assertEqual((0.75, 2.25), note)
        self.assertEqual((0.75, 2.25), lyric)

    def test_language_change_blocks_previous_inspected_input_signature(self):
        job_id, signature = self.ready()
        with patch.object(self.manager, "run") as execute:
            blocked = self.callbacks["run"](*self.bound_inputs(job_id, signature), "fra")
            execute.assert_not_called()
        self.assertIsNone(blocked[0])
        self.assertIsNone(blocked[9])

    def test_inspection_forwards_model_and_recovery_restores_selection_and_signature(self):
        self.ready()
        choice = "WAV2VEC2_ASR_LARGE_LV60K_960H"
        checked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request,
                                             "eng", model_choice=choice)
        summary = self.manager.snapshot(checked[0])["input_summary"]
        self.assertEqual(choice, summary["model_choice"])
        self.assertEqual(choice, summary["model_id"])
        self.assertEqual("general", summary["mode"])
        self.assertEqual(input_signature(*self.paths, "eng", choice), checked[1])
        recovered = self.callbacks["recover"](checked[0], False, False, 100, self.request)
        self.assertEqual(("eng", choice), recovered[17:19])
        self.assertEqual(input_signature(None, None, None, "eng", choice), recovered[1])
        self.assertTrue(recovered[10]["interactive"])

    def test_changed_model_blocks_run_cancel_export_filter_preview_and_row_selection(self):
        job_id, signature = self.ready()
        choice = "WAV2VEC2_ASR_LARGE_LV60K_960H"
        for action in ("run", "cancel", "export"):
            with self.subTest(action=action), patch.object(self.manager, action) as execute:
                blocked = self.callbacks[action](*self.bound_inputs(job_id, signature), model_choice=choice)
                execute.assert_not_called()
                self.assertIsNone(blocked[0])
                self.assertIsNone(blocked[9])
        with patch.object(self.manager, "snapshot") as read:
            rows = self.callbacks["filter"](*self.bound_inputs(job_id, signature), model_choice=choice)
            self.assertEqual([], rows[0]["data"])
            self.assertEqual([], rows[1]["data"])
            for action in ("select_note", "select_lyric"):
                interval = self.callbacks[action](*self.bound_inputs(job_id, signature),
                                                  SimpleNamespace(index=(0, 0)), model_choice=choice)
                self.assertEqual((gr.skip(), gr.skip()), interval)
            read.assert_not_called()
        with patch.object(self.manager, "preview") as preview:
            clip, message = self.callbacks["preview"](
                job_id, signature, *self.paths, 0, 1, self.request, model_choice=choice)
            preview.assert_not_called()
            self.assertIsNone(clip)
            self.assertIn("입력 검사", message)

    def test_recovery_restores_language_and_its_input_signature(self):
        self.ready()
        checked = self.callbacks["inspect"](*self.paths, False, False, 100, self.request, "eng")
        recovered = self.callbacks["recover"](checked[0], False, False, 100, self.request)
        self.assertEqual("eng", recovered[17])
        self.assertEqual(CACHED_MODEL, recovered[18])
        self.assertEqual(input_signature(None, None, None, "eng", CACHED_MODEL), recovered[1])

    def test_recovered_old_review_disables_execution_and_export_but_keeps_report_visible(self):
        job_id, signature = self.ready()
        self.callbacks["run"](*self.bound_inputs(job_id, signature))
        snapshot = self.manager.snapshot(job_id)
        snapshot["input_summary"].pop("operation", None)
        with patch.object(self.manager, "recover", return_value=snapshot):
            recovered = self.callbacks["recover"](job_id, False, False, 100, self.request)
        self.assertFalse(recovered[10]["interactive"])
        self.assertFalse(recovered[11]["interactive"])
        self.assertIn("이전 타이밍 수정 작업", recovered[3])
        self.assertIn("이전 타이밍 수정 작업", recovered[5])
        self.assertIn("이전 타이밍 수정 작업 보고서", recovered[8])
        self.assertEqual(715, len(recovered[6]["data"]))
        self.assertIsNone(recovered[9])

    def test_recovered_model_less_general_job_keeps_actual_model_and_requires_new_inspection(self):
        job_id, signature = self.ready()
        self.callbacks["run"](*self.bound_inputs(job_id, signature))
        snapshot = self.manager.snapshot(job_id)
        summary = snapshot["input_summary"]
        summary.pop("model_choice", None)
        summary.pop("model_id", None)
        summary.update(mode="general", language="jpn")
        snapshot["summary"]["provenance"] = {"model_id": "MMS_FA"}
        with patch.object(self.manager, "recover", return_value=snapshot):
            recovered = self.callbacks["recover"](job_id, False, False, 100, self.request)
        self.assertEqual(("jpn", "MMS_FA"), recovered[17:19])
        self.assertEqual(input_signature(None, None, None, "jpn", "MMS_FA"), recovered[1])
        self.assertFalse(recovered[10]["interactive"])
        self.assertFalse(recovered[11]["interactive"])
        self.assertIn("모델 선택 이전 작업", recovered[3])
        self.assertIn("MMS_FA", recovered[5])
        self.assertEqual(715, len(recovered[6]["data"]))

    def test_recovered_old_completed_job_preserves_downloads_and_marks_its_report(self):
        job_id, signature = self.ready()
        self.callbacks["run"](*self.bound_inputs(job_id, signature))
        published = self.callbacks["export"](*self.bound_inputs(job_id, signature))
        snapshot = self.manager.snapshot(job_id)
        snapshot["input_summary"].pop("operation", None)
        with patch.object(self.manager, "recover", return_value=snapshot):
            recovered = self.callbacks["recover"](job_id, False, False, 100, self.request)
        self.assertEqual(published[9], recovered[9])
        self.assertEqual(4, len(recovered[9]))
        self.assertFalse(recovered[10]["interactive"])
        self.assertFalse(recovered[11]["interactive"])
        self.assertIn("이전 타이밍 수정 작업", recovered[3])
        self.assertIn("이전 타이밍 수정 작업 보고서", recovered[8])


if __name__ == "__main__":
    unittest.main()
