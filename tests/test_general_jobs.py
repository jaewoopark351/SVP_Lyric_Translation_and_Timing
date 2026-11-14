"""Exercise real general-song jobs while replacing only acoustic inference."""

import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from svp_alignment.jobs.manager import JobManager
from svp_alignment.jobs.processing import inspect_job_inputs
from svp_alignment.general_pipeline import prepare_song
from svp_alignment.profiles.counting_stars import SOURCE_HASHES
from svp_alignment.project import BLICK_PER_QUARTER as Q, read_project
from svp_alignment.verification.lyrics_only import verify_lyrics_only
from svp_alignment.audio.transcript import select_model

ROOT = Path(__file__).resolve().parents[1]


def synthetic_project():
    """Two notes span a tempo change, with nonzero project/group offsets."""
    return {
        'version': 153,
        'arbitrary': {'preserve': ['metadata', 123]},
        'time': {'startTimeSeconds': .25,
                 'tempo': [{'position': 0, 'bpm': 120}, {'position': 2 * Q, 'bpm': 60}],
                 'meter': [{'index': 0, 'numerator': 3, 'denominator': 4}]},
        'library': [{'uuid': 'user-song', 'parameters': {'keep': [1, 2]}, 'notes': [
            {'uuid': 'first-note', 'onset': 0, 'duration': Q, 'pitch': 57, 'detune': 3,
             'lyrics': 'la', 'phonemes': '', 'attributes': {'muted': False}},
            {'uuid': 'second-note', 'onset': 2 * Q, 'duration': Q, 'pitch': 64, 'detune': -5,
             'lyrics': 'la', 'phonemes': '', 'attributes': {'muted': False}},
        ]}],
        'tracks': [
            {'name': 'User vocal', 'mainGroup': {'uuid': 'empty-main', 'notes': []},
             'mainRef': {'uuid': 'main-ref', 'groupID': 'empty-main', 'isInstrumental': False},
             'groups': [{'uuid': 'user-ref', 'groupID': 'user-song', 'isInstrumental': False,
                         'blickOffset': Q, 'pitchOffset': -12,
                         'blickAbsoluteBegin': -1, 'blickAbsoluteEnd': -1,
                         'voice': {'paramLoudness': -2.0}}]},
            {'name': 'Reference audio', 'mainGroup': {'uuid': 'audio-main', 'notes': []},
             'groups': [], 'mainRef': {'uuid': 'audio-ref', 'isInstrumental': True,
                                       'blickOffset': 0, 'pitchOffset': 0,
                                       'audio': {'filename': 'Z:/not-required/user-vocals.wav', 'duration': 99.0}}},
        ],
    }


def deterministic_alignment(wav_path, words, workspace, progress=None, cancelled=None,
                            cache_reused=False, language='auto', model_choice='auto'):
    """Return known model-shaped spans; no model, GPU or actual speech assertion."""
    if cancelled is not None and cancelled():
        raise InterruptedError('synthetic acoustic cancellation')
    if progress is not None:
        progress('synthetic acoustic progress', .5)
    if cancelled is not None and cancelled():
        raise InterruptedError('synthetic acoustic cancellation')
    spans = []
    for index, (word, (start, end)) in enumerate(zip(words, ((.52, .9), (2.02, 2.7)))):
        source = word['source']
        chars = [{'char': character.lower(), 'start': start + (end - start) * position / len(source),
                  'end': start + (end - start) * (position + 1) / len(source), 'p': .97}
                 for position, character in enumerate(source)]
        spans.append({**word, 'word_index': index, 'normalized': source.lower(),
                      'start': start, 'end': end, 'p': .97, 'chars': chars, 'status': 'AUTO', 'reason': ''})
    return spans, {'model_id': select_model(words, language, model_choice), 'model_sha256': '0' * 64,
                   'cache_reused': cache_reused, 'language': language, 'model_choice': model_choice,
                   'settings': {'test_only': True},
                   'audio': {'duration': 4.0, 'sample_rate': 16000, 'channels': 1}}


class GeneralJobTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'work' / 'gui-validation'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='general-jobs-', dir=base)
        self.workspace = Path(self.temporary.name).resolve()
        self.assertTrue(self.workspace.is_relative_to(base.resolve()))
        self.inputs_folder = self.workspace / '사용자 원본'
        self.inputs_folder.mkdir()
        self.title = '별빛 연습'
        svp = self.inputs_folder / (self.title + '.svp')
        txt = self.inputs_folder / (self.title + '.txt')
        wav = self.inputs_folder / (self.title + '.wav')
        svp.write_bytes(json.dumps(synthetic_project(), ensure_ascii=False).encode('utf-8') + b'\0')
        txt.write_text('cat dog\n', encoding='utf-8')
        with wave.open(str(wav), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\0\0' * (16000 * 4))
        self.paths = (svp, txt, wav)
        self.expected_input_bytes = [path.read_bytes() for path in self.paths]
        self.manager = JobManager(root=self.workspace)

    def tearDown(self):
        self.assertEqual(self.expected_input_bytes, [path.read_bytes() for path in self.paths])
        self.assertTrue(self.workspace.is_relative_to((ROOT / 'work/gui-validation').resolve()))
        self.temporary.cleanup()

    def ready(self):
        result = self.manager.inspect(*self.paths)
        self.assertEqual(result['status'], 'READY', result.get('error'))
        self.assertEqual(result['input_summary']['mode'], 'general')
        self.assertEqual(result['input_summary']['operation'], 'lyrics_only')
        return result

    def run_review(self):
        ready = self.ready()
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
            review = self.manager.run(ready['job_id'])
        self.assertEqual(review['status'], 'REVIEW_READY', review.get('error'))
        inference.assert_called_once()
        return review

    def test_non_profile_song_inspection_accepts_arbitrary_notes_and_tempo(self):
        ready = self.ready()
        summary = ready['input_summary']
        self.assertEqual(summary['note_count'], 2)
        self.assertEqual(summary['word_count'], 2)
        self.assertEqual(summary['tempo'], synthetic_project()['time']['tempo'])
        self.assertEqual(summary['meter'], [{'index': 0, 'numerator': 3, 'denominator': 4}])
        self.assertEqual(summary['audio_offset'], .25)
        self.assertEqual(summary['duration'], 4.0)
        self.assertEqual(summary['linked_audio'][0]['audio']['duration'], 99.0)
        self.assertTrue(any('missing' in warning for warning in summary['warnings']))
        self.assertFalse(ready['files'])
        self.assertFalse((self.workspace / 'outputs').exists())

    def test_selected_model_is_forwarded_persisted_and_restored_for_export(self):
        choice = 'WAV2VEC2_ASR_BASE_960H'
        ready = self.manager.inspect(*self.paths, model_choice=choice)
        self.assertEqual(choice, ready['input_summary']['model_choice'])
        self.assertEqual(choice, ready['input_summary']['model_id'])
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
            review = self.manager.run(ready['job_id'])
        self.assertEqual('REVIEW_READY', review['status'], review['error'])
        self.assertEqual(choice, inference.call_args.kwargs['model_choice'])
        restarted = JobManager(root=self.workspace)
        restored = restarted.recover(ready['job_id'])
        self.assertEqual(choice, restored['input_summary']['model_choice'])
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
            published = restarted.export(ready['job_id'])
        self.assertEqual('COMPLETED', published['status'], published['error'])
        inference.assert_not_called()
        self.assertEqual(choice, published['summary']['provenance']['model_id'])
        self.assertTrue(verify_lyrics_only(read_project(self.paths[0], uploaded=True),
                                          read_project(published['files'][0], uploaded=True).data))

    def test_a_different_executed_model_is_rejected_before_draft_publication(self):
        ready = self.ready()
        def wrong_model(*args, **kwargs):
            result, provenance = deterministic_alignment(*args, **kwargs)
            provenance['model_id'] = 'WAV2VEC2_ASR_BASE_960H'
            return result, provenance
        with patch('svp_alignment.audio.alignment.align_words', side_effect=wrong_model):
            result = self.manager.run(ready['job_id'])
        self.assertEqual('FAILED', result['status'])
        self.assertIn('모델', result['error'])
        self.assertFalse((self.workspace / 'work' / 'gradio' / ready['job_id'] / 'draft').exists())

    def test_changed_model_selection_is_rejected_when_revalidating(self):
        ready = self.ready()
        job = self.manager._job(ready['job_id'])
        job.input_summary['model_choice'] = 'WAV2VEC2_ASR_BASE_960H'
        with patch('svp_alignment.audio.alignment.align_words') as inference:
            failed = self.manager.run(ready['job_id'])
        self.assertEqual('FAILED', failed['status'])
        inference.assert_not_called()

    def test_default_fresh_processing_does_not_consult_the_legacy_cache(self):
        reason = 'Missing external No Reverb audio or unavailable cached observations'
        for cache_error in (ValueError(reason), OSError(reason)):
            with self.subTest(error_type=type(cache_error).__name__):
                with patch('svp_alignment.jobs.processing.inspect_paths', side_effect=cache_error) as cached:
                    ready = self.manager.inspect(*self.paths, language='eng')
                cached.assert_not_called()
                self.assertEqual(ready['status'], 'READY', ready.get('error'))
                self.assertEqual(ready['input_summary']['mode'], 'general')
                self.assertEqual(ready['input_summary']['language'], 'eng')
                self.assertEqual(ready['input_summary']['note_count'], 2)
                self.assertEqual(ready['input_summary']['model_id'], 'WAV2VEC2_ASR_LARGE_LV60K_960H')
                with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
                    review = self.manager.run(ready['job_id'])
                self.assertEqual(review['status'], 'REVIEW_READY', review.get('error'))
                inference.assert_called_once()
                self.assertEqual(inference.call_args.kwargs['language'], 'eng')
                self.assertEqual(review['summary']['analysis'], 'FRESH')
                self.assertFalse(review['files'])

    def test_explicit_cached_choice_failure_never_silently_runs_another_model(self):
        with patch('svp_alignment.jobs.processing.file_hash', side_effect=SOURCE_HASHES), \
             patch('svp_alignment.jobs.processing.inspect_paths', side_effect=ValueError('missing cached audio')), \
             patch('svp_alignment.audio.alignment.align_words') as inference:
            result = self.manager.inspect(*self.paths, model_choice='cached_counting_stars')
        self.assertEqual('FAILED', result['status'])
        self.assertIn('missing cached audio', result['error'])
        inference.assert_not_called()

    def test_invalid_general_input_is_not_hidden_by_counting_stars_cache_fallback(self):
        self.paths[0].write_bytes(b'invalid uploaded SVP JSON')
        self.expected_input_bytes[0] = self.paths[0].read_bytes()
        with patch('svp_alignment.jobs.processing.file_hash', side_effect=SOURCE_HASHES), \
             patch('svp_alignment.jobs.processing.inspect_paths', side_effect=ValueError('missing external audio')):
            with self.assertRaisesRegex(ValueError, 'Cannot parse SVP JSON'):
                inspect_job_inputs(self.paths)

    def test_general_run_publish_and_recover_four_dynamic_artifacts(self):
        review = self.run_review()
        self.assertEqual(len(review['comparison_rows']), 2)
        self.assertEqual([row['txt_word'] for row in review['lyric_rows']], ['cat', 'dog'])
        self.assertFalse(review['files'])
        self.assertIn('NOT_VERIFIED', review['report'])
        self.assertIn('WAV2VEC2_ASR_LARGE_LV60K_960H', review['report'])
        completed = self.manager.export(review['job_id'])
        self.assertEqual(completed['status'], 'COMPLETED', completed.get('error'))
        names = {self.title + suffix for suffix in ('_LYRICS_FILLED.svp', ' - Note comparison.csv',
                                                    ' - Lyric verification.csv', ' - Verification.md')}
        self.assertEqual({Path(value).name for value in completed['files']}, names)
        self.assertEqual(len(completed['files']), 4)
        for value in completed['files']:
            self.assertTrue(Path(value).is_file())
            self.assertTrue(Path(value).resolve().is_relative_to(self.workspace / 'outputs' / review['job_id']))
        restored = JobManager(root=self.workspace).recover(review['job_id'])
        self.assertEqual(restored['status'], 'COMPLETED', restored.get('error'))
        self.assertEqual(restored['files'], completed['files'])
        self.assertEqual(len(restored['comparison_rows']), 2)
        self.assertEqual([row['txt_word'] for row in restored['lyric_rows']], ['cat', 'dog'])

    def test_only_lyrics_change_despite_different_high_confidence_acoustic_times(self):
        with patch('svp_alignment.alignment.general_timing.time_notes',
                   side_effect=AssertionError('Lyrics-only jobs must never calculate note edits')):
            review = self.run_review()
        completed = self.manager.export(review['job_id'])
        self.assertEqual(completed['status'], 'COMPLETED', completed.get('error'))
        destination = next(Path(value) for value in completed['files'] if value.endswith('.svp'))
        original = read_project(self.paths[0], uploaded=True)
        edited = read_project(destination, uploaded=True)
        self.assertTrue(original.verify(edited.data))
        self.assertTrue(verify_lyrics_only(original, edited.data))
        before = original.target_notes()
        after = original.target_notes(project=edited.data)
        self.assertEqual([row['lyrics'] for row in after], ['cat', 'dog'])
        self.assertEqual([row['onset'] for row in before], [row['onset'] for row in after])
        self.assertEqual([row['duration'] for row in before], [row['duration'] for row in after])
        self.assertEqual([row['noteID'] for row in before], [row['noteID'] for row in after])
        self.assertEqual([row['pitch'] for row in before], [row['pitch'] for row in after])
        self.assertEqual([row['detune'] for row in before], [row['detune'] for row in after])
        self.assertEqual(original.data['time'], edited.data['time'])
        self.assertEqual(original.data['tracks'], edited.data['tracks'])
        self.assertEqual(original.suffix, edited.suffix)
        original_fields, edited_fields = deepcopy(original.data), deepcopy(edited.data)
        for project in (original_fields, edited_fields):
            for note in project['library'][0]['notes']:
                note.pop('lyrics', None)
        self.assertEqual(original_fields, edited_fields)
        rows = review['comparison_rows']
        self.assertTrue(any(row['onset_error_before_ms'] != 0 for row in rows))
        for row in rows:
            self.assertEqual(row['onset_change_ms'], 0)
            self.assertEqual(row['duration_change_ms'], 0)
            self.assertEqual(row['onset_error_before_ms'], row['onset_error_after_ms'])
            self.assertEqual(row['end_error_before_ms'], row['end_error_after_ms'])
        self.assertIn('ALIGNED와 UNKNOWN 모두 원본 음표 시각을 유지', review['report'])
        self.assertNotIn('0.75초 초과 이동', review['report'])

    def test_lyrics_only_preservation_rejects_onset_and_duration_edits(self):
        original = read_project(self.paths[0], uploaded=True)
        for field in ('onset', 'duration'):
            with self.subTest(field=field):
                updated = deepcopy(original.data)
                updated['library'][0]['notes'][0][field] += 1
                # The general format validator permits these historical timing
                # edits, while the new operation requires a stricter boundary.
                self.assertTrue(original.verify(updated))
                with self.assertRaisesRegex(ValueError, 'lyrics'):
                    verify_lyrics_only(original, updated)

    def test_direct_general_prepare_rejects_historical_timing_operation_before_inference(self):
        summary = dict(self.ready()['input_summary'])
        summary.pop('operation')
        with patch('svp_alignment.audio.alignment.align_words') as inference:
            with self.assertRaisesRegex(ValueError, '새로 검사'):
                prepare_song(self.paths, summary, self.workspace)
        inference.assert_not_called()

    def test_lyrics_only_preservation_checks_non_note_json_types_and_other_lyrics(self):
        original = read_project(self.paths[0], uploaded=True)
        updated = deepcopy(original.data)
        updated['arbitrary']['preserve'][1] = 123.0
        self.assertTrue(original.verify(updated))
        with self.assertRaisesRegex(ValueError, 'lyrics'):
            verify_lyrics_only(original, updated)
        updated = deepcopy(original.data)
        updated['tracks'][0]['mainGroup']['notes'].append(
            {'onset': 0, 'duration': Q, 'pitch': 60, 'lyrics': 'extra'})
        with self.assertRaises(ValueError):
            verify_lyrics_only(original, updated)

    def test_changed_input_after_inspection_fails_before_inference_or_output(self):
        ready = self.ready()
        self.paths[1].write_text('cat dog changed\n', encoding='utf-8')
        self.expected_input_bytes[1] = self.paths[1].read_bytes()
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
            result = self.manager.run(ready['job_id'])
        inference.assert_not_called()
        self.assertEqual(result['status'], 'FAILED')
        self.assertFalse(result['files'])
        self.assertFalse((self.workspace / 'outputs' / ready['job_id']).exists())
        self.assertFalse((self.workspace / 'work/gradio' / ready['job_id'] / 'draft').exists())

    def test_cancel_during_acoustic_progress_never_publishes_partial_results(self):
        ready = self.ready()
        observed = []
        def progress(label, fraction):
            observed.append(label)
            if label == 'synthetic acoustic progress':
                self.manager.cancel(ready['job_id'])
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment):
            result = self.manager.run(ready['job_id'], progress=progress)
        self.assertIn('synthetic acoustic progress', observed)
        self.assertEqual(result['status'], 'CANCELLED', result.get('error'))
        self.assertFalse(result['files'])
        self.assertFalse((self.workspace / 'outputs' / ready['job_id']).exists())
        self.assertFalse((self.workspace / 'work/gradio' / ready['job_id'] / 'draft').exists())

    def test_review_export_after_restart_reuses_deterministic_aligned_candidates(self):
        ready = self.ready()
        cache_states = iter((False, True))
        def inference_result(*args, **kwargs):
            return deterministic_alignment(*args, **kwargs, cache_reused=next(cache_states))
        with patch('svp_alignment.audio.alignment.align_words', side_effect=inference_result) as inference:
            review = self.manager.run(ready['job_id'])
            self.assertEqual(review['status'], 'REVIEW_READY', review.get('error'))
            draft = self.workspace / 'work/gradio' / ready['job_id'] / 'draft' / (self.title + '_LYRICS_FILLED.svp')
            draft_bytes = draft.read_bytes()
            restarted = JobManager(root=self.workspace)
            restored = restarted.recover(ready['job_id'])
            self.assertEqual(restored['status'], 'REVIEW_READY', restored.get('error'))
            exported = restarted.export(ready['job_id'])
        self.assertEqual(inference.call_count, 1)
        self.assertEqual(exported['status'], 'COMPLETED', exported.get('error'))
        result_path = next(Path(value) for value in exported['files'] if value.endswith('.svp'))
        self.assertEqual(result_path.read_bytes(), draft_bytes)
        self.assertEqual(read_project(result_path).data['library'][0]['notes'][0]['lyrics'], 'cat')

    def test_explicit_korean_language_is_forwarded_and_persisted_through_recovery(self):
        ready = self.manager.inspect(*self.paths, language='kor')
        self.assertEqual(ready['status'], 'READY', ready.get('error'))
        self.assertEqual(ready['input_summary']['language'], 'kor')
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as inference:
            review = self.manager.run(ready['job_id'])
        self.assertEqual(review['status'], 'REVIEW_READY', review.get('error'))
        self.assertEqual(inference.call_args.kwargs['language'], 'kor')
        self.assertEqual(review['summary']['provenance']['language'], 'kor')
        manifest_path = self.workspace / 'work/gradio' / ready['job_id'] / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['input_summary']['language'], 'kor')
        restarted = JobManager(root=self.workspace)
        restored = restarted.recover(ready['job_id'])
        self.assertEqual(restored['input_summary']['language'], 'kor')
        with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment) as replay:
            exported = restarted.export(ready['job_id'])
        self.assertEqual(exported['status'], 'COMPLETED', exported.get('error'))
        replay.assert_not_called()
        self.assertEqual(exported['summary']['provenance']['language'], 'kor')

    def test_manifest_result_name_traversal_is_rejected_without_exposing_files(self):
        review = self.run_review()
        manifest_path = self.workspace / 'work/gradio' / review['job_id'] / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['input_summary']['artifact_names'][0] = '../escape.svp'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        restored = JobManager(root=self.workspace).recover(review['job_id'])
        self.assertEqual(restored['status'], 'FAILED')
        self.assertFalse(restored['files'])
        self.assertFalse(restored['comparison_rows'])
        self.assertFalse((self.workspace / 'outputs' / review['job_id']).exists())
        self.assertFalse((self.workspace / 'escape.svp').exists())


if __name__ == '__main__':
    unittest.main()
