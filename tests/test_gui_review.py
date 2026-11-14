"""Review classifications and revision-bound lyric correction without model inference."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import gradio as gr

from svp_alignment.ui.callbacks import OUTPUT_COUNT, input_signature, make_callbacks
from svp_alignment.ui.presentation import filtered_lyrics, filtered_notes, review_text, status_text


def review_snapshot():
    return {
        "job_id": "review-job", "status": "REVIEW_READY",
        "input_summary": {"operation": "lyrics_only", "mode": "general", "model_choice": "auto",
                          "placement_policy": "word_note_groups_v1"},
        "summary": {"quality_known": True, "draft_revision": 3, "placement_complete": False,
                    "unresolved_notes": 1, "review_required_notes": 1, "confirmed_notes": 1,
                    "symbol_risks": 1},
        "comparison_rows": [
            {"note": 1, "note_id": "one", "old_lyrics": "la", "new_lyrics": "la",
             "placement_action": "UNASSIGNED_ORIGINAL", "review_status": "NEEDS_REVIEW",
             "symbol_risk": "False", "assignment": "UNKNOWN"},
            {"note": 4, "note_id": "four", "new_lyrics": "run", "txt_word": "run", "word_index": 0,
             "placement_action": "WORD_START", "review_status": "NEEDS_REVIEW",
             "symbol_risk": "True", "assignment": "UNKNOWN"},
            {"note": 5, "note_id": "five", "new_lyrics": "-", "word_index": 0,
             "placement_action": "CONTINUE", "review_status": "USER_CONFIRMED",
             "symbol_risk": False, "assignment": "UNKNOWN"}],
        "lyric_rows": [
            {"word_index": 0, "txt_line": 1, "txt_word": "run", "note_numbers": "4 / 5",
             "review_status": "NEEDS_REVIEW", "symbol_risk": True},
            {"word_index": 1, "txt_line": 2, "txt_word": "run", "note_numbers": "",
             "review_status": "NEEDS_REVIEW", "symbol_risk": False}],
    }


class GuiReviewDisplayTests(unittest.TestCase):
    def test_classifications_distinguish_unassigned_review_confirmed_and_string_false(self):
        snapshot = review_snapshot()
        self.assertEqual([1], [row["note"] for row in filtered_notes(snapshot, quality_filter="unassigned_notes")])
        self.assertEqual([4], [row["note"] for row in filtered_notes(snapshot, quality_filter="review_required")])
        self.assertEqual([5], [row["note"] for row in filtered_notes(snapshot, quality_filter="confirmed")])
        self.assertEqual([4], [row["note"] for row in filtered_notes(snapshot, quality_filter="symbol_risks")])
        self.assertEqual([], filtered_lyrics(snapshot, quality_filter="unassigned_notes"))
        self.assertEqual([1], [row["word_index"] for row in filtered_lyrics(snapshot, quality_filter="unplaced_words")])
        self.assertEqual([], filtered_notes(snapshot, quality_filter="unplaced_words"))

    def test_saved_partial_and_historical_quality_are_explicit(self):
        snapshot = review_snapshot()
        snapshot["status"] = "COMPLETED"
        self.assertIn("부분 초안 저장 완료", status_text(snapshot))
        self.assertIn("미대응 음표 1개", review_text(snapshot))
        self.assertIn("배치 후 검토 필요 1개", review_text(snapshot))
        snapshot["summary"] = {}
        self.assertIn("가사 완성도 확인 불가", status_text(snapshot))
        self.assertIn("새 검토 분류 기록 없음", review_text(snapshot))
        historical = {"comparison_rows": [{"note": 1, "assignment": "UNKNOWN"}], "lyric_rows": []}
        self.assertEqual(historical["comparison_rows"], filtered_notes(historical, quality_filter="legacy_unknown"))
        self.assertEqual([], filtered_notes(historical, quality_filter="unassigned_notes"))


class GuiCorrectionCallbackTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = review_snapshot()
        self.manager = Mock()
        self.manager.session_revision.return_value = 2
        self.manager.current_session_job.return_value = "review-job"
        self.manager.snapshot.side_effect = lambda _: copy.deepcopy(self.snapshot)
        self.callbacks = make_callbacks(self.manager)
        self.request = SimpleNamespace(session_hash="browser-one")
        self.signature = input_signature("a.svp", "a.txt", "a.wav")
        self.bound = ("review-job", self.signature, "a.svp", "a.txt", "a.wav", False, False, 100)

    def select(self):
        # The filtered row is note 4, so the editor must never use its displayed row index as an ID.
        return self.callbacks["select_correction"](
            *self.bound, self.request, SimpleNamespace(index=(0, 0)), quality_filter="symbol_risks")

    def apply(self, selection, action="NEXT_SYLLABLE", word_index=0, syllable=2, end=4, confirmed=True):
        return self.callbacks["apply_correction"](
            *self.bound, selection, action, word_index, syllable, end, confirmed, self.request)

    def test_selection_preserves_token_zero_and_original_note_number_with_draft_revision(self):
        selected = self.select()
        token = selected[0]
        self.assertEqual(4, token["note_number"])
        self.assertEqual("four", token["note_id"])
        self.assertEqual(3, token["draft_revision"])
        self.assertEqual(2, token["session_revision"])
        self.assertEqual(0, selected[2]["value"])
        self.assertEqual([0, 1], [value for _, value in selected[2]["choices"]])
        self.assertEqual(2, selected[4])

    def test_selection_preserves_existing_plus_word_local_boundary(self):
        first, selected, continuation = self.snapshot["comparison_rows"]
        first.update(word_index=0, placement_action="WORD_START", syllable_ids="7 8")
        selected.update(placement_action="NEXT_SYLLABLE", syllable_ids="9", new_lyrics="+")
        continuation.update(syllable_ids="9")
        # Global syllable ID 9 is the third syllable of this word, not the tenth.
        self.assertEqual(3, self.select()[4])

    def test_continuation_selection_suggests_next_available_boundary(self):
        self.snapshot["comparison_rows"] = [
            {"note": 1, "word_index": "0", "placement_action": "WORD_START", "syllable_ids": "10"},
            {"note": 2, "word_index": "0", "placement_action": "TEXT_FRAGMENT", "syllable_ids": "11 12"},
            {"note": 3, "word_index": "0", "placement_action": "CONTINUE", "syllable_ids": "11 12"},
            {"note": 4, "word_index": "0", "placement_action": "NEXT_SYLLABLE", "syllable_ids": "13"}]
        selected = self.callbacks["select_correction"](
            *self.bound, self.request, SimpleNamespace(index=(2, 0)))
        # Syllable 2 already starts at note 2; the next available boundary is 3.
        self.assertEqual(3, selected[4])

    def test_apply_converts_syllable_number_and_forwards_optimistic_revision(self):
        token = self.select()[0]
        self.manager.correct_lyrics.return_value = copy.deepcopy(self.snapshot)
        result = self.apply(token)
        self.manager.correct_lyrics.assert_called_once_with(
            "review-job", 4, "NEXT_SYLLABLE", word_index=0, syllable_index=1,
            confirmed=True, expected_revision=3, end_note_number=None)
        self.assertEqual(OUTPUT_COUNT + 8, len(result))
        self.assertIsNone(result[OUTPUT_COUNT])
        self.assertIn("다시 검사", result[-1])

    def test_input_or_model_change_blocks_old_selection_before_writing(self):
        token = self.select()[0]
        token["signature"] = "old-input"
        result = self.apply(token)
        self.manager.correct_lyrics.assert_not_called()
        self.assertIn("다시 선택", result[-1])
        result = self.callbacks["apply_correction"](
            *self.bound, self.select()[0], "CONFIRM", 0, 1, 4, True, self.request,
            model_choice="WAV2VEC2_ASR_LARGE_LV60K_960H")
        self.manager.correct_lyrics.assert_not_called()
        self.assertIn("입력 검사", result[-1])

    def test_other_correction_or_session_revision_blocks_stale_selection(self):
        token = self.select()[0]
        self.snapshot["summary"]["draft_revision"] = 4
        self.assertIn("다른 교정", self.apply(token)[-1])
        self.manager.correct_lyrics.assert_not_called()
        self.snapshot["summary"]["draft_revision"] = 3
        self.manager.session_revision.return_value = 3
        self.assertIn("다시 선택", self.apply(token)[-1])
        self.manager.correct_lyrics.assert_not_called()

    def test_completed_or_historical_job_cannot_enter_editor(self):
        for state, quality in (("COMPLETED", True), ("REVIEW_READY", False)):
            self.snapshot["status"] = state
            self.snapshot["summary"]["quality_known"] = quality
            selected = self.select()
            self.assertIsNone(selected[0])
            self.assertIn("교정할 수 없습니다", selected[-1])

    def test_exported_or_previous_policy_draft_cannot_apply_previously_selected_edit(self):
        token = self.select()[0]
        self.snapshot["status"] = "COMPLETED"
        self.assertIn("교정할 수 없습니다", self.apply(token)[-1])
        self.snapshot["status"] = "REVIEW_READY"
        self.snapshot["input_summary"].pop("placement_policy")
        self.assertIn("교정할 수 없습니다", self.apply(token)[-1])
        self.manager.correct_lyrics.assert_not_called()

    def test_recovered_previous_policy_disables_run_and_save_with_model_selection_preserved(self):
        self.snapshot["input_summary"].pop("placement_policy")
        self.manager.recover.return_value = copy.deepcopy(self.snapshot)
        result = self.callbacks["recover"]("review-job", False, False, 100, self.request)
        self.assertFalse(result[10]["interactive"])
        self.assertFalse(result[11]["interactive"])
        self.assertEqual("auto", result[18])
        self.assertIn("이전 가사 배치 방식", result[3])

    def test_confirmation_requires_explicit_acknowledgement_and_selection_rejects_negative_index(self):
        self.assertIn("확인란", self.apply(self.select()[0], action="CONFIRM", confirmed=False)[-1])
        self.manager.correct_lyrics.assert_not_called()
        selected = self.callbacks["select_correction"](
            *self.bound, self.request, SimpleNamespace(index=(-1, 0)))
        self.assertIsNone(selected[0])
        self.assertIn("다시 선택", selected[-1])

    def test_late_correction_result_cannot_restore_detached_input(self):
        token = self.select()[0]
        def detached(*args, **kwargs):
            self.manager.session_revision.return_value = 3
            return copy.deepcopy(self.snapshot)
        self.manager.correct_lyrics.side_effect = detached
        self.assertEqual((gr.skip(),) * (OUTPUT_COUNT + 8), self.apply(token))


if __name__ == "__main__":
    unittest.main()
