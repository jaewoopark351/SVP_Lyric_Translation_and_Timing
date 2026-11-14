"""Heavy ASR+aligner evidence remains word-only and explicitly unverified."""

import unittest

from svp_alignment.alignment.general_lyrics import parse_words
from svp_alignment.alignment.general_matching import match_words_to_notes
from svp_alignment.audio.model_catalog import HEAVY_MODEL
from svp_alignment.ui.presentation import model_text, review_text
from svp_alignment.verification.general_reporting import lyric_rows, markdown, note_rows


class HeavyReportingTests(unittest.TestCase):
    def fixture(self):
        words = parse_words('Go missing')
        notes = [dict(onset=0, duration=500, pitch=60, detune=0, lyrics='la',
                      start_s=0.0, end_s=.5, note_id='retained-note')]
        observations = [
            dict(word_index=0, source='Go', start=.05, end=.45, p=None, chars=[],
                 status='AUTO', alignment_unit='word', score_unavailable=True,
                 recognition_status='MATCHED'),
            dict(word_index=1, source='missing', start=None, end=None, p=None,
                 chars=[], status='UNKNOWN', alignment_unit='word',
                 score_unavailable=True, recognition_status='UNMATCHED',
                 reason='ASR 인식문에서 대응하는 원문 단어를 찾지 못했습니다.'),
        ]
        alignment = match_words_to_notes(words, observations, notes)
        evidence = [dict(start_reference=.05, end_reference=.45,
                         start_basis='MODEL_WORD_WINDOW_ONLY', end_basis='MODEL_WORD_WINDOW_ONLY')]
        rows = note_rows(notes, notes, alignment, evidence)
        lyrics = lyric_rows(words, alignment, notes, model_id=HEAVY_MODEL)
        return rows, lyrics

    def test_heavy_csv_has_no_character_observations_or_fake_score(self):
        rows, lyrics = self.fixture()
        self.assertEqual('MODEL_WORD_WINDOW_ONLY', rows[0]['timing_evidence'])
        for row in lyrics:
            self.assertEqual(HEAVY_MODEL, row['model_id'])
            self.assertEqual('word', row['alignment_unit'])
            self.assertFalse(row['score_available'])
            for column in ('ctc_starts_s', 'ctc_end_s', 'ctc_p', 'mms_onsets_s'):
                self.assertEqual('', row[column], column)
        self.assertEqual('', lyrics[1]['observed_word_start_s'])
        self.assertEqual('UNKNOWN', lyrics[1]['status'])
        self.assertEqual('UNPLACED', lyrics[1]['placement_state'])

    def test_report_identifies_two_models_and_retains_txt_as_authority(self):
        rows, lyrics = self.fixture()
        report = markdown(rows, lyrics, {'mode': 'general', 'operation': 'lyrics_only'},
                          {'model_id': HEAVY_MODEL, 'cache_reused': False})
        self.assertIn('ASR 1.7B 인식 + ForcedAligner 0.6B', report)
        self.assertIn('제공 TXT가 최종 가사의 기준', report)
        self.assertIn('인식문으로 교체하지 않습니다', report)
        self.assertIn('인식문과 모델 시각은 실제 가창의 정답이 아닙니다', report)
        self.assertIn('`NOT_VERIFIED`', report)
        self.assertNotIn('CTC 문자 시각', report)

    def test_report_and_ui_distinguish_observation_reuse_from_fresh_inference(self):
        rows, lyrics = self.fixture()
        provenance = {'model_id': HEAVY_MODEL, 'cache_reused': True}
        report = markdown(rows, lyrics, {'mode': 'general', 'operation': 'lyrics_only'}, provenance)
        self.assertIn('새 추론: `NOT_RUN`', report)
        self.assertNotIn('단어 정렬: `RUN`', report)
        snapshot = {'status': 'REVIEW_READY', 'input_summary': {
            'mode': 'general', 'operation': 'lyrics_only', 'model_choice': HEAVY_MODEL,
            'model_id': HEAVY_MODEL}, 'summary': {'provenance': provenance},
            'comparison_rows': rows, 'lyric_rows': lyrics}
        text = review_text(snapshot)
        self.assertIn('저장 관측으로 자동 후보를 복원', text)
        self.assertIn('새 추론·전체 WAV 청취 검증: **NOT_RUN**', text)
        self.assertNotIn('새 ASR 인식·단어 정렬 실행 완료', text)
        self.assertIn('ASR 인식문은 정답이 아니며', text)
        self.assertIn('Qwen3 ASR', model_text(snapshot))

    def test_ui_explains_fresh_heavy_evidence_for_recovered_provenance(self):
        snapshot = {'status': 'REVIEW_READY', 'input_summary': {
            'mode': 'general', 'operation': 'lyrics_only', 'model_choice': HEAVY_MODEL},
            'summary': {'provenance': {'model_id': HEAVY_MODEL, 'cache_reused': False}}}
        text = review_text(snapshot)
        self.assertIn('새 ASR 인식·단어 정렬 실행 완료', text)
        self.assertIn('개별 음절·문자 시각과 신뢰도 점수는 제공하지 않습니다', text)
        self.assertIn('가사 대응 전체 판정: NOT_VERIFIED', text)


if __name__ == '__main__':
    unittest.main()
