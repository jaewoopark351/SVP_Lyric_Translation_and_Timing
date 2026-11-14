"""Recognition evidence cannot replace lyrics or invent missing word times."""

from copy import deepcopy
import unittest

from svp_alignment.audio.asr_reference import map_recognition
from svp_alignment.audio.transcript import clean_qwen_token


def source(*tokens):
    return [dict(source=text, word_index=i, line=1, column=i + 1,
                 normalized=clean_qwen_token(text)) for i, text in enumerate(tokens)]


def observed(*tokens):
    return [dict(text=text, start_time=i + .1, end_time=i + .9)
            for i, text in enumerate(tokens)]


class AsrReferenceTests(unittest.TestCase):
    def test_exact_sequence_preserves_source_case_order_and_repeats(self):
        words = source('Run', 'boy', 'run', 'Run', 'boy', 'run')
        before = deepcopy(words)
        result = map_recognition(words, observed('Run,', 'boy', 'run!', 'Run', 'boy', 'run'), 10.)
        self.assertEqual(words, before)
        self.assertEqual([w['source'] for w in result], [w['source'] for w in words])
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED'] * 6)
        self.assertEqual([w['start'] for w in result], [i + .1 for i in range(6)])
        self.assertTrue(all(w['p'] is None and not w['chars'] for w in result))

    def test_recognizer_substitution_and_extra_text_never_replace_source(self):
        result = map_recognition(source('bright', 'blue', 'sky'),
                                 observed('bright', 'red', 'sky', 'subscribe'), 10.)
        self.assertEqual([w['source'] for w in result], ['bright', 'blue', 'sky'])
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED', 'UNMATCHED', 'MATCHED'])
        self.assertIsNone(result[1]['start'])
        self.assertFalse(result[1]['observed_units'])

    def test_missing_repeated_token_is_ambiguous_on_both_source_occurrences(self):
        result = map_recognition(source('run', 'run'), observed('run'), 10.)
        self.assertEqual([w['recognition_status'] for w in result], ['AMBIGUOUS', 'AMBIGUOUS'])
        self.assertTrue(all(w['start'] is None and w['status'] == 'UNKNOWN' for w in result))

    def test_exact_merge_is_ambiguous_when_an_optimal_path_substitutes_the_token(self):
        result = map_recognition(source('a', 'ab'), observed('a', 'b'), 10.)
        self.assertEqual([w['recognition_status'] for w in result], ['AMBIGUOUS', 'AMBIGUOUS'])
        self.assertTrue(all(w['start'] is None for w in result))

    def test_missing_final_word_keeps_the_last_source_token_unknown(self):
        result = map_recognition(source('time', 'to', 'run'), observed('time', 'to'), 10.)
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED', 'MATCHED', 'UNMATCHED'])
        self.assertIsNone(result[-1]['end'])

    def test_word_can_own_multiple_complete_observed_units(self):
        result = map_recognition(source('victory', 'now'), observed('vic', 'tory', 'now'), 10.)
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED', 'MATCHED'])
        self.assertEqual(result[0]['recognized_unit_indices'], [0, 1])
        self.assertEqual(result[0]['start'], .1)
        self.assertEqual(result[0]['end'], 1.9)
        self.assertEqual(''.join(u['text'] for u in result[0]['observed_units']), 'victory')

    def test_one_observed_unit_is_never_split_between_source_words(self):
        result = map_recognition(source('you', 'are'), observed('youare'), 10.)
        self.assertTrue(all(w['start'] is None and not w['observed_units'] for w in result))

    def test_character_units_keep_original_boundaries_without_interpolated_times(self):
        result = map_recognition(source('별빛', '아래'), observed('별', '빛', '아', '래'), 10.)
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED', 'MATCHED'])
        self.assertEqual(result[0]['observed_units'], [
            {'text': '별', 'start': .1, 'end': .9}, {'text': '빛', 'start': 1.1, 'end': 1.9}])
        self.assertEqual(result[0]['chars'], [])

    def test_invalid_timing_keeps_recognition_unknown_without_repair(self):
        for start, end in ((None, None), (float('nan'), 1.), (-1., 1.), (1., 1.),
                           (1., 12.), (True, 2.)):
            with self.subTest(start=start, end=end):
                result = map_recognition(source('run'), [dict(text='run', start_time=start, end_time=end)], 10.)
                self.assertEqual(result[0]['recognition_status'], 'INVALID_OBSERVATION')
                self.assertIsNone(result[0]['start'])
                self.assertIsNone(result[0]['p'])

    def test_overlap_invalidates_both_units_and_preserves_other_word(self):
        units = observed('run', 'boy', 'now')
        units[0]['end_time'] = 1.5
        result = map_recognition(source('run', 'boy', 'now'), units, 10.)
        self.assertEqual([w['recognition_status'] for w in result],
                         ['INVALID_OBSERVATION', 'INVALID_OBSERVATION', 'MATCHED'])
        self.assertEqual(result[2]['start'], 2.1)

    def test_unknown_unsupported_source_keeps_original_position_and_reason(self):
        words = source('run', '123', 'now')
        words[1].update(normalized='', reason='unsupported pronunciation')
        result = map_recognition(words, observed('run', 'now'), 10.)
        self.assertEqual([w['source'] for w in result], ['run', '123', 'now'])
        self.assertEqual(result[1]['reason'], 'unsupported pronunciation')
        self.assertEqual([w['recognition_status'] for w in result], ['MATCHED', 'UNMATCHED', 'MATCHED'])

    def test_empty_recognition_is_not_hallucinated_from_reference(self):
        result = map_recognition(source('Run', 'boy', 'run'), [], 10.)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(w['recognition_status'] == 'UNMATCHED' for w in result))


if __name__ == '__main__':
    unittest.main()
