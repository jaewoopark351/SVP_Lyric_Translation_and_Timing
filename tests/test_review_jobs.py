"""Review revisions preserve prior bundles and never rerun acoustic models."""

import unittest
from threading import Event, Thread
from unittest.mock import patch

from tests import test_general_jobs as general_jobs
from svp_alignment.jobs.manager import JobManager
from svp_alignment.project import read_project
from svp_alignment.verification.lyrics_only import verify_lyrics_only
from svp_alignment.alignment.general_lyrics import parse_words
from svp_alignment.alignment.general_matching import match_words_to_notes
from svp_alignment.alignment.review_edits import apply_review_edit
from svp_alignment.verification.general_lyrics import verify_placement


class ReviewJobTests(unittest.TestCase):
    setUp = general_jobs.GeneralJobTests.setUp
    tearDown = general_jobs.GeneralJobTests.tearDown
    ready = general_jobs.GeneralJobTests.ready
    run_review = general_jobs.GeneralJobTests.run_review

    def test_confirmation_preserves_previous_draft_and_source_and_restores_without_model(self):
        review = self.run_review()
        self.assertTrue(review['summary']['quality_known'])
        self.assertEqual(review['draft_revision'], 0)
        job = self.manager._job(review['job_id'])
        folder = self.manager.store.draft_folder(job)
        previous = {p.name: p.read_bytes() for p in folder.iterdir()}
        corrected = self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM',
                                                confirmed=True, expected_revision=0)
        self.assertEqual(corrected['draft_revision'], 1)
        self.assertEqual(corrected['summary']['draft_revision'], 1)
        self.assertEqual(corrected['comparison_rows'][0]['review_status'], 'USER_CONFIRMED')
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, previous)
        restart = JobManager(root=self.workspace)
        restored = restart.recover(review['job_id'])
        self.assertEqual(restored['draft_revision'], 1)
        self.assertEqual(restored['comparison_rows'][0]['review_status'], 'USER_CONFIRMED')
        with patch('svp_alignment.audio.alignment.align_words') as model:
            result = restart.export(review['job_id'])
        model.assert_not_called()
        self.assertEqual(result['status'], 'COMPLETED', result['error'])
        original = read_project(self.paths[0], uploaded=True)
        self.assertTrue(verify_lyrics_only(original, read_project(result['files'][0], uploaded=True).data))
        self.assertEqual(len(result['files']), 4)
        with self.assertRaisesRegex(ValueError, '완료'):
            restart.correct_lyrics(review['job_id'], 1, 'CONFIRM', confirmed=True, expected_revision=1)

    def test_stale_or_unconfirmed_requests_preserve_manifest_and_revision(self):
        review = self.run_review()
        manifest = self.manager.store.job_folder(review['job_id']) / 'manifest.json'
        initial = manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, '체크'):
            self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM', expected_revision=0)
        self.assertEqual(initial, manifest.read_bytes())
        with self.assertRaisesRegex(ValueError, '최신'):
            self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM', confirmed=True, expected_revision=True)
        corrected = self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM',
                                                confirmed=True, expected_revision=0)
        new_manifest = manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, '최신'):
            self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM', confirmed=True, expected_revision=0)
        self.assertEqual(new_manifest, manifest.read_bytes())
        self.assertEqual(corrected['draft_revision'], 1)
        self.assertFalse((manifest.parent / 'draft-000002').exists())

    def test_invalid_word_choice_does_not_publish_a_revision(self):
        review = self.run_review()
        job = self.manager._job(review['job_id'])
        original_manifest = (self.manager.store.job_folder(job.job_id) / 'manifest.json').read_bytes()
        with self.assertRaises(ValueError):
            self.manager.correct_lyrics(job.job_id, 1, 'WORD_START', word_index=99,
                                       expected_revision=0, end_note_number=1)
        self.assertEqual(job.draft_revision, 0)
        self.assertEqual((self.manager.store.job_folder(job.job_id) / 'manifest.json').read_bytes(),
                         original_manifest)

    def test_failed_manifest_commit_keeps_old_revision_and_retry_uses_new_folder(self):
        review = self.run_review()
        manifest = self.manager.store.job_folder(review['job_id']) / 'manifest.json'
        initial = manifest.read_bytes()
        with patch.object(self.manager.store, 'save_manifest', side_effect=OSError('commit failed')):
            with self.assertRaisesRegex(OSError, 'commit failed'):
                self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM',
                                           confirmed=True, expected_revision=0)
        self.assertEqual(initial, manifest.read_bytes())
        self.assertEqual(self.manager._job(review['job_id']).draft_revision, 0)
        result = self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM',
                                             confirmed=True, expected_revision=0)
        self.assertEqual(result['draft_revision'], 2)

    def test_tampered_context_is_not_used_for_correction(self):
        review = self.run_review()
        job = self.manager._job(review['job_id'])
        context = self.manager.store.draft_folder(job) / 'review-context.json'
        context.write_bytes(context.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, '근거'):
            self.manager.correct_lyrics(job.job_id, 1, 'CONFIRM', confirmed=True, expected_revision=0)
        self.assertEqual(job.draft_revision, 0)

    def test_other_manager_stale_correction_and_export_cannot_lose_a_confirmed_note(self):
        review = self.run_review()
        other = JobManager(root=self.workspace)
        other.recover(review['job_id'])
        self.manager.correct_lyrics(review['job_id'], 1, 'CONFIRM',
                                    confirmed=True, expected_revision=0)
        with self.assertRaisesRegex(ValueError, '최신'):
            other.correct_lyrics(review['job_id'], 2, 'CONFIRM', confirmed=True, expected_revision=0)
        with self.assertRaisesRegex(ValueError, '최신'):
            other.export(review['job_id'])
        with self.assertRaisesRegex(ValueError, '최신'):
            other.cancel(review['job_id'])
        refreshed = other.recover(review['job_id'])
        self.assertEqual(refreshed['draft_revision'], 1)
        self.assertEqual(refreshed['comparison_rows'][0]['review_status'], 'USER_CONFIRMED')
        second = other.correct_lyrics(review['job_id'], 2, 'CONFIRM',
                                       confirmed=True, expected_revision=1)
        self.assertEqual(second['summary']['confirmed_notes'], 2)

    def test_compressed_word_reports_the_last_consumed_syllable_end(self):
        self.paths[1].write_text('hello\n', encoding='utf-8')
        self.expected_input_bytes = [path.read_bytes() for path in self.paths]
        review = self.run_review()
        context = self.manager._job(review['job_id']).prepared.review_context
        alignment = context['alignment']
        ids = alignment['assignments'][0]
        self.assertGreater(len(ids), 1)
        first, last = (alignment['syllables'][ids[0]], alignment['syllables'][ids[-1]])
        self.assertGreater(last['end'], first['end'])
        self.assertEqual(review['comparison_rows'][0]['waveform_start_s'], first['onset'])
        self.assertEqual(review['comparison_rows'][0]['waveform_end_s'], last['end'])

    def test_export_still_accepts_cancellation_before_publication(self):
        review = self.run_review()
        reached, release = Event(), Event()
        outcome = []
        validate = self.manager.store.validate_bundle

        def paused_validation(*args, **kwargs):
            reached.set()
            if not release.wait(5):
                raise TimeoutError('test export validation was not released')
            return validate(*args, **kwargs)

        with patch.object(self.manager.store, 'validate_bundle', side_effect=paused_validation):
            worker = Thread(target=lambda: outcome.append(self.manager.export(review['job_id'])))
            worker.start()
            try:
                self.assertTrue(reached.wait(5))
                cancelled = self.manager.cancel(review['job_id'])
                self.assertEqual(cancelled['status'], 'CANCEL_REQUESTED')
            finally:
                release.set()
                worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome[0]['status'], 'CANCELLED')
        self.assertFalse(outcome[0]['files'])
        self.assertFalse((self.workspace / 'outputs' / review['job_id']).exists())


class ReviewDecisionTests(unittest.TestCase):
    def test_syllable_edit_does_not_confirm_other_changed_notes(self):
        words = parse_words('hello')
        spans = [{**words[0], 'start': 0., 'end': .8, 'p': .95, 'chars': [
            {'char': c, 'start': i * .15, 'end': (i + 1) * .15}
            for i, c in enumerate('hello')]}]
        notes = [{'start_s': i * .2, 'end_s': (i + 1) * .2, 'lyrics': 'la'} for i in range(4)]
        baseline = match_words_to_notes(words, spans, notes)
        group = apply_review_edit(baseline, notes, note_number=1, action='WORD_START',
                                  word_index=0, end_note_number=4, confirmed=False)
        revised = apply_review_edit(group, notes, note_number=3, action='NEXT_SYLLABLE',
                                    word_index=0, syllable_index=1, confirmed=True)
        final = [{**n, 'lyrics': revised['lyric_fields'].get(i, n['lyrics'])} for i, n in enumerate(notes)]
        verify_placement(words, revised, final)
        self.assertEqual(revised['note_actions'][2]['review_status'], 'USER_CONFIRMED')
        self.assertNotEqual(revised['note_actions'][0]['review_status'], 'USER_CONFIRMED')
        self.assertNotEqual(revised['note_actions'][1]['review_status'], 'USER_CONFIRMED')
        self.assertNotEqual(revised['note_actions'][3]['review_status'], 'USER_CONFIRMED')
        self.assertEqual(baseline['words'], words)


if __name__ == '__main__':
    unittest.main()
