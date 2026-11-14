"""Song-independent alignment policy and source-order regression tests."""

import tempfile
import unittest
from pathlib import Path

from svp_alignment.alignment.general_lyrics import parse_words, read_words, syllable_evidence
from svp_alignment.alignment.general_matching import match_words_to_notes
from svp_alignment.alignment.lyric_symbols import render_word_group
from svp_alignment.alignment.source_lyrics import parse_words as parse_source_words
from svp_alignment.alignment.general_timing import time_notes
from svp_alignment.verification.general_lyrics import verify_placement
from svp_alignment.verification.general_reporting import note_rows, lyric_rows, markdown
from svp_alignment.project import BLICK_PER_QUARTER as Q, SvpDocument


def notes(*spans):
    return [dict(note_index=index, locator=('library', 0, 'notes', index),
                 note_id=str(index), onset=round(start * 1000), duration=round((end - start) * 1000),
                 pitch=60 + index, detune=0, lyrics='la', start_s=start, end_s=end)
            for index, (start, end) in enumerate(spans)]


def observations(words, spans, p=.95):
    return [dict(word_index=index, source=word['source'], start=start, end=end,
                 p=p, chars=[], status='AUTO') for index, (word, (start, end)) in enumerate(zip(words, spans))]


class GeneralAlignmentTests(unittest.TestCase):
    def test_word_only_model_never_invents_internal_syllable_times_or_scores(self):
        words = parse_words('hello')
        span = dict(word_index=0, source='hello', start=0.0, end=4.0,
                    p=None, chars=[], status='AUTO', alignment_unit='word', score_unavailable=True)
        evidence = syllable_evidence(words, [span])
        self.assertEqual(2, len(evidence))
        self.assertTrue(all(item['onset'] == 0.0 and item['end'] == 4.0 for item in evidence))
        self.assertTrue(all(item['p'] is None and item['alignment_unit'] == 'word' for item in evidence))
        self.assertTrue(all('단어 범위' in item['reason'] for item in evidence))

    def test_word_only_sustained_word_uses_fixed_notes_and_reports_unknown(self):
        words = parse_words('hello')
        span = dict(word_index=0, source='hello', start=0.0, end=4.0,
                    p=None, chars=[], status='AUTO', alignment_unit='word', score_unavailable=True)
        original = notes((0, 1), (3, 4))
        result = match_words_to_notes(words, [span], original)
        self.assertEqual({0: 'hello', 1: '+'}, result['lyric_fields'])
        self.assertEqual({0, 1}, set(result['unknown']))
        rows = lyric_rows(words, result, original)
        self.assertNotIn('0.000', rows[0]['ctc_p'])
        self.assertEqual('', rows[0]['ctc_starts_s'])
        self.assertEqual('', rows[0]['mms_onsets_s'])
        self.assertEqual('word', rows[0]['alignment_unit'])
        self.assertFalse(rows[0]['score_available'])
        self.assertEqual((0.0, 4.0), (rows[0]['observed_word_start_s'], rows[0]['observed_word_end_s']))
        self.assertIn('UNKNOWN', rows[0]['status'])
        self.assertTrue(all('0.55' not in reason for reason in result['unknown'].values()))
        compressed = match_words_to_notes(words, [span], notes((0, 4)))
        row = lyric_rows(words, compressed, original,
                         model_id='Qwen/Qwen3-ForcedAligner-0.6B')[0]
        self.assertEqual('1', row['note_numbers'])
        self.assertEqual('word', row['alignment_unit'])
        self.assertEqual({0: 'hello'}, compressed['lyric_fields'])
        self.assertEqual('TEXT_FRAGMENTS', compressed['note_actions'][0]['representation'])

    def test_qwen_report_explains_word_window_and_unavailable_scores(self):
        words = parse_words('Go')
        original = notes((0, .5))
        span = dict(word_index=0, source='Go', start=.05, end=.45,
                    p=None, chars=[], status='AUTO', alignment_unit='word', score_unavailable=True)
        result = match_words_to_notes(words, [span], original)
        evidence = [dict(start_reference=.05, end_reference=.45,
                         start_basis='MODEL_WORD_WINDOW_ONLY', end_basis='MODEL_WORD_WINDOW_ONLY')]
        rows = note_rows(original, original, result, evidence)
        report = markdown(rows, lyric_rows(words, result, original),
                          {'operation': 'lyrics_only'}, {'model_id': 'Qwen/Qwen3-ForcedAligner-0.6B'})
        self.assertIn('단어 시간 범위', report)
        self.assertIn('신뢰도 점수는 제공되지 않습니다', report)
        self.assertEqual('MODEL_WORD_WINDOW_ONLY', rows[0]['timing_evidence'])
        unobserved = note_rows(original, original, result,
                               [dict(start_reference=None, end_reference=None)])[0]
        self.assertEqual('NO_OBSERVATION', unobserved['timing_evidence'])

    def test_unicode_locations_apostrophes_hyphens_and_repeats(self):
        words = parse_words("Hello, I'm here!\n별빛 별빛 déjà-vu")
        self.assertEqual(['Hello', "I'm", 'here', '별빛', '별빛', 'déjà-vu'], [word['source'] for word in words])
        self.assertEqual((2, 4, 4), (words[4]['line'], words[4]['column'], words[4]['word_index']))

    def test_utf8_read_keeps_source_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '가사.txt'
            source = '별빛 Hello\n'.encode('utf-8-sig')
            path.write_bytes(source)
            self.assertEqual('별빛', read_words(path)[0]['source'])
            self.assertEqual(source, path.read_bytes())

    def test_repeated_words_map_monotonically_and_keep_case(self):
        words = parse_words('Go go GO')
        original = notes((0, .4), (1, 1.4), (2, 2.4))
        result = match_words_to_notes(words, observations(words, ((.05, .4), (1.05, 1.4), (2.05, 2.4))), original)
        self.assertEqual({0: 'Go', 1: 'go', 2: 'GO'}, result['lyric_fields'])
        after = [dict(note, lyrics=result['lyric_fields'][index]) for index, note in enumerate(original)]
        self.assertEqual(3, verify_placement(words, result, after)['placed_words'])

    def test_single_note_can_hold_whole_multisyllable_word(self):
        words = parse_words('hello')
        original = notes((0, 1))
        result = match_words_to_notes(words, observations(words, ((0, 1),)), original)
        self.assertEqual({}, result['unplaced'])
        self.assertEqual({0: [0, 1]}, result['assignments'])
        self.assertEqual({0: 'hello'}, result['lyric_fields'])
        self.assertEqual('NEEDS_REVIEW', result['note_actions'][0]['review_status'])
        after = [dict(original[0], lyrics='hello')]
        self.assertEqual(1, verify_placement(words, result, after)['placed_words'])

    def test_compressed_fragments_preserve_case_apostrophes_and_hyphens(self):
        words = parse_words("Tomo'rr-ow")
        original = notes((0, .3), (.3, .7))
        result = match_words_to_notes(words, observations(words, ((0, .7),)), original)
        actions = [result['note_actions'][index] for index in (0, 1)]
        self.assertEqual("Tomo'rr-ow", ''.join(action['text'] for action in actions))
        self.assertTrue(all(action['representation'] == 'TEXT_FRAGMENTS' for action in actions))
        self.assertEqual(['WORD_START', 'TEXT_FRAGMENT'], [action['action'] for action in actions])
        self.assertEqual(actions[0]['source_end'], actions[1]['source_start'])
        self.assertTrue(all(action['text'] == words[0]['source'][action['source_start']:action['source_end']]
                            for action in actions))

    def test_joint_syllable_and_sustain_layout_has_no_original_holes(self):
        words = parse_words('hello go')
        original = notes((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.))
        spans = observations(words, ((0, .5), (.8, 1.)))
        spans[0]['chars'] = [dict(char=char, start=start, end=start + .02)
                             for char, start in zip('hello', (0., .05, .15, .4, .45))]
        result = match_words_to_notes(words, spans, original)
        self.assertEqual({0: 'hello', 1: '-', 2: '+', 3: '-', 4: 'go'}, result['lyric_fields'])
        self.assertEqual([0, 1, 2, 3], result['word_spans'][0])
        self.assertEqual(0, result['note_actions'][2]['owner_note'])
        self.assertEqual(2, result['note_actions'][3]['owner_note'])
        after = [dict(note, lyrics=result['lyric_fields'][index]) for index, note in enumerate(original)]
        self.assertEqual(2, verify_placement(words, result, after)['placed_words'])

    def test_short_ctc_end_does_not_discard_contiguous_sustain_candidate(self):
        words = parse_words('run now')
        original = notes((0, .2), (.2, .4), (.4, .6), (.7, 1.))
        result = match_words_to_notes(words, observations(words, ((0, .12), (.7, .95))), original)
        self.assertEqual({0: 'run', 1: '-', 2: '-', 3: 'now'}, result['lyric_fields'])
        self.assertEqual('NEEDS_REVIEW', result['note_actions'][2]['review_status'])
        self.assertIn('실제 발음 종료', result['note_actions'][2]['reason'])

    def test_score_rest_does_not_bridge_unobserved_instrumental_notes(self):
        words = parse_words('go now')
        original = notes((0, .2), (1.5, 1.7), (3., 3.2))
        result = match_words_to_notes(words, observations(words, ((0, .1), (3., 3.15))), original)
        self.assertNotIn(1, result['lyric_fields'])
        self.assertEqual('UNASSIGNED_ORIGINAL', result['note_actions'][1]['action'])
        self.assertIn('공백', result['note_actions'][1]['reason'])

    def test_unknown_token_is_a_barrier_instead_of_sustain_permission(self):
        words = parse_words('go missing now')
        original = notes((0, .2), (.2, .4), (.4, .6), (1., 1.2))
        spans = observations(words, ((0, .1), (None, None), (1., 1.15)))
        spans[1].update(status='UNKNOWN', reason='unsupported')
        result = match_words_to_notes(words, spans, original)
        self.assertEqual({0: 'go', 3: 'now'}, result['lyric_fields'])
        self.assertEqual('unsupported', result['unplaced'][1])
        self.assertTrue(all(result['note_actions'][index]['action'] == 'UNASSIGNED_ORIGINAL'
                            for index in (1, 2)))

    def test_skipped_observed_token_blocks_preceding_continuations(self):
        words = parse_words('go no next')
        original = notes((0, .25), (.4, .6), (1., 1.2))
        result = match_words_to_notes(words, observations(words, ((0, .05), (.1, .15), (1., 1.1))), original)
        self.assertIn(1, result['unplaced'])
        self.assertNotIn(1, result['lyric_fields'])

    def test_terminal_unobserved_tail_is_not_filled_with_dashes(self):
        words = parse_words('go')
        original = notes((0, .2), (.2, .4), (.4, .6))
        result = match_words_to_notes(words, observations(words, ((0, .1),)), original)
        self.assertEqual({0: 'go'}, result['lyric_fields'])
        self.assertEqual({}, result['continuations'])

    def test_outside_timeline_word_is_accounted_for_without_time_clipping(self):
        words = parse_words('go run')
        original = notes((0, .2), (.2, .4))
        result = match_words_to_notes(words, observations(words, ((0, .1), (60., 61.))), original)
        self.assertIn('범위 밖', result['unplaced'][1])
        self.assertTrue(all(result['syllables'][item]['word'] == 0
                            for ids in result['assignments'].values() for item in ids))
        self.assertEqual(60., next(item['word_start'] for item in result['syllables'] if item['word'] == 1))

    def test_real_la_is_assigned_even_when_its_text_is_unchanged(self):
        words = parse_words('la')
        result = match_words_to_notes(words, observations(words, ((0, .4),)), notes((0, .5)))
        self.assertEqual({0: 'la'}, result['lyric_fields'])
        self.assertEqual('WORD_START', result['note_actions'][0]['action'])
        self.assertEqual({}, result['unplaced'])

    def test_source_reader_compatibility_and_exact_accented_boundaries(self):
        self.assertIs(parse_words, parse_source_words)
        words = parse_words('De\u0301ja\u0300-vu')
        evidence = syllable_evidence(words, observations(words, ((0, 1),)))
        self.assertEqual(words[0]['source'], ''.join(item['source_text'] for item in evidence))
        self.assertTrue(all(item['onset'] == 0 and item['end'] == 1 for item in evidence))

    def test_shared_renderer_uses_confirmed_group_without_automatic_unknown(self):
        words = parse_words('hello')
        evidence = syllable_evidence(words, observations(words, ((0, 1),)))
        rendered = render_word_group(words, evidence, 0, [1, 2, 3], {1: [0], 3: [1]},
                                     review_status='USER_CONFIRMED', reason='사용자 확인')
        self.assertEqual({1: 'hello', 2: '-', 3: '+'}, rendered['lyric_fields'])
        self.assertEqual({}, rendered['unknown'])
        self.assertTrue(all(item['review_status'] == 'USER_CONFIRMED'
                            for item in rendered['note_actions'].values()))

    def test_shared_renderer_rejects_holes_and_incomplete_source_consumption(self):
        words = parse_words('hello')
        evidence = syllable_evidence(words, observations(words, ((0, 1),)))
        with self.assertRaises(ValueError):
            render_word_group(words, evidence, 0, [0, 2], {0: [0], 2: [1]})
        with self.assertRaises(ValueError):
            render_word_group(words, evidence, 0, [0], {0: [0]})

    def test_similar_word_start_candidates_remain_review_required(self):
        words = parse_words('go')
        result = match_words_to_notes(words, observations(words, ((.2, .5),)), notes((0, .2), (.4, .6)))
        placed = [item for item in result['note_actions'].values() if item['action'] == 'WORD_START']
        self.assertEqual(1, len(placed))
        self.assertEqual('NEEDS_REVIEW', placed[0]['review_status'])
        self.assertIn('비슷한 비용', placed[0]['reason'])

    def test_multisyllable_candidates_are_unknown_and_do_not_retime(self):
        words = parse_words('hello')
        original = notes((0, .4), (.5, 1))
        result = match_words_to_notes(words, observations(words, ((.1, .9),)), original)
        self.assertEqual({0: 'hello', 1: '+'}, result['lyric_fields'])
        self.assertEqual(2, len(result['unknown']))
        times, _, _ = time_notes(original, result, 2)
        self.assertEqual([(0., .4), (.5, 1.)], times)

    def test_low_confidence_keeps_original_timing(self):
        words = parse_words('go')
        original = notes((0, .5))
        result = match_words_to_notes(words, observations(words, ((.1, .4),), p=.2), original)
        self.assertIn(0, result['unknown'])
        self.assertEqual([(0., .5)], time_notes(original, result, 1)[0])

    def test_melisma_continuation_is_reported_unknown(self):
        words = parse_words('go')
        original = notes((0, .4), (.4, .8))
        result = match_words_to_notes(words, observations(words, ((0, .8),)), original)
        self.assertEqual({1: 0}, result['continuations'])
        self.assertEqual('-', result['lyric_fields'][1])
        self.assertEqual(2, len(result['unknown']))

    def test_unsupported_word_remains_in_report(self):
        words = parse_words('123')
        spans = [dict(word_index=0, source='123', start=None, end=None,
                      p=0, chars=[], status='UNKNOWN', reason='unsupported')]
        original = notes((0, 1))
        result = match_words_to_notes(words, spans, original)
        lyrics = lyric_rows(words, result, original)
        self.assertEqual(('123', 'UNKNOWN', ''),
                         (lyrics[0]['txt_word'], lyrics[0]['status'], lyrics[0]['note_numbers']))

    def test_new_overlap_reverts_candidates_and_is_unknown(self):
        original = notes((0, .5), (.5, 1))
        result = dict(assignments={0: [0], 1: [1]}, unknown={},
                      syllables=[dict(onset=.1, end=.7), dict(onset=.6, end=.9)])
        times, _, unknown = time_notes(original, result, 1)
        self.assertEqual([(0., .5), (.5, 1.)], times)
        self.assertEqual({0, 1}, set(unknown))

    def test_reports_use_generic_counts_and_explicit_not_verified(self):
        words = parse_words('Go')
        original = notes((0, .5))
        result = match_words_to_notes(words, observations(words, ((.05, .45),)), original)
        times, evidence, result['unknown'] = time_notes(original, result, 1)
        after = [dict(original[0], lyrics='Go', start_s=times[0][0], end_s=times[0][1])]
        comparison = note_rows(original, after, result, evidence)
        lyrics = lyric_rows(words, result, after)
        report = markdown(comparison, lyrics, {'duration': 1}, {'model': 'test'})
        self.assertIn('NOT_VERIFIED', report)
        self.assertIn('NOT_RUN', report)
        self.assertNotIn('Counting Stars', report)
        self.assertEqual('Go', comparison[0]['new_lyrics'])

    def test_source_mismatch_is_rejected(self):
        words = parse_words('Go')
        spans = observations(words, ((0, .5),))
        spans[0]['source'] = 'Other'
        with self.assertRaises(ValueError):
            match_words_to_notes(words, spans, notes((0, .5)))

    def test_cp949_and_utf16_bom_decoding_keep_unicode_words(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '가사.txt'
            for encoding in ('cp949', 'utf-16'):
                path.write_bytes('별빛 반복'.encode(encoding))
                self.assertEqual(['별빛', '반복'], [word['source'] for word in read_words(path)])

    def test_invalid_ctc_span_is_unknown_without_type_error(self):
        words = parse_words('go')
        spans = observations(words, ((0, .5),))
        spans[0]['start'] = 'bad'
        result = match_words_to_notes(words, spans, notes((0, .5)))
        self.assertIn(0, result['unplaced'])

    def test_common_silent_e_suffixes_do_not_add_notes(self):
        words = parse_words('hopes wished tables waited')
        spans = observations(words, ((0, 1), (1, 2), (2, 3), (3, 4)))
        syllables = syllable_evidence(words, spans)
        self.assertEqual([1, 1, 2, 2],
                         [sum(item['word'] == index for item in syllables) for index in range(4)])

    def test_decomposed_unicode_accents_remain_exact_tokens(self):
        words = parse_words('de\u0301ja\u0300 still-here')
        self.assertEqual(['de\u0301ja\u0300', 'still-here'], [word['source'] for word in words])
        self.assertEqual(8, words[1]['column'])

    def clipped_document(self, begin=Q, end=3 * Q):
        return SvpDocument({
            'time': {'startTimeSeconds': .25,
                     'tempo': [{'position': 0, 'bpm': 120}, {'position': 2 * Q, 'bpm': 60}]},
            'library': [{'uuid': 'clipped', 'notes': [
                {'onset': 0, 'duration': 2 * Q, 'pitch': 60, 'lyrics': 'la'}]}],
            'tracks': [{'mainGroup': {'notes': []}, 'groups': [
                {'groupID': 'clipped', 'blickOffset': Q,
                 'blickAbsoluteBegin': begin, 'blickAbsoluteEnd': end}]}],
        })

    def clip_candidate(self, document, start, end, converter=True):
        original = document.target_notes()
        alignment = dict(assignments={0: [0]}, unknown={},
                         syllables=[dict(onset=start, end=end)])
        options = ({'seconds_to_local_blick': document.seconds_to_local_blick}
                   if converter else {})
        return time_notes(original, alignment, 10, **options)

    def test_clip_end_overrun_reverts_without_failing_document_apply(self):
        document = self.clipped_document()
        note = document.target_notes()[0]
        times, _, unknown = self.clip_candidate(document, note['start_s'], note['end_s'] + .1)
        self.assertEqual([(note['start_s'], note['end_s'])], times)
        self.assertIn('clip', unknown[0])
        start, end = times[0]
        onset = document.seconds_to_local_blick(note, start)
        stop = document.seconds_to_local_blick(note, end)
        updated = document.apply({note['locator']: {'onset': onset, 'duration': stop - onset}})
        self.assertTrue(document.verify(updated))

    def test_clip_begin_underrun_reverts_with_nonzero_group_offset(self):
        document = self.clipped_document()
        note = document.target_notes()[0]
        times, _, unknown = self.clip_candidate(document, note['start_s'] - .1, note['end_s'])
        self.assertEqual([(note['start_s'], note['end_s'])], times)
        self.assertIn('clip', unknown[0])

    def test_unbounded_clip_sentinels_allow_normal_candidate(self):
        document = self.clipped_document(begin=-1, end=-1)
        note = document.target_notes()[0]
        times, _, unknown = self.clip_candidate(document, note['start_s'] - .1, note['end_s'] + .1)
        self.assertEqual([(note['start_s'] - .1, note['end_s'] + .1)], times)
        self.assertEqual({}, unknown)

    def test_clip_end_uses_rounded_blick_boundary(self):
        document = self.clipped_document()
        note = document.target_notes()[0]
        tick_seconds = 1 / Q  # Final tempo segment is 60 BPM.
        within_rounding = note['end_s'] + .4 * tick_seconds
        outside_rounding = note['end_s'] + 1.1 * tick_seconds
        times, _, unknown = self.clip_candidate(document, note['start_s'], within_rounding)
        self.assertEqual({}, unknown)
        self.assertEqual(3 * Q, document.seconds_to_local_blick(note, times[0][1]) + Q)
        times, _, unknown = self.clip_candidate(document, note['start_s'], outside_rounding)
        self.assertEqual([(note['start_s'], note['end_s'])], times)
        self.assertIn('clip', unknown[0])

    def test_clip_begin_uses_rounded_blick_boundary(self):
        document = self.clipped_document()
        note = document.target_notes()[0]
        tick_seconds = .5 / Q  # Initial tempo segment is 120 BPM.
        times, _, unknown = self.clip_candidate(document, note['start_s'] - .4 * tick_seconds, note['end_s'])
        self.assertEqual({}, unknown)
        self.assertEqual(Q, document.seconds_to_local_blick(note, times[0][0]) + Q)
        times, _, unknown = self.clip_candidate(document, note['start_s'] - 1.1 * tick_seconds, note['end_s'])
        self.assertEqual([(note['start_s'], note['end_s'])], times)
        self.assertIn('clip', unknown[0])

    def test_bounded_clip_without_tempo_converter_is_conservative(self):
        document = self.clipped_document()
        note = document.target_notes()[0]
        times, _, unknown = self.clip_candidate(document, note['start_s'] + .1, note['end_s'] - .1,
                                              converter=False)
        self.assertEqual([(note['start_s'], note['end_s'])], times)
        self.assertIn('clip', unknown[0])


if __name__ == '__main__':
    unittest.main()
