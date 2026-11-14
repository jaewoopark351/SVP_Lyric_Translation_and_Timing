"""Fixed-note lyric regressions from saved observations, without model inference."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from svp_alignment.alignment.general_lyrics import parse_words, syllable_evidence
from svp_alignment.alignment.general_matching import match_words_to_notes
from svp_alignment.alignment.review_edits import apply_review_edit
from svp_alignment.project import SvpDocument
from svp_alignment.verification.general_lyrics import verify_placement
from svp_alignment.verification.general_reporting import lyric_rows, note_rows, markdown
from svp_alignment.verification.lyrics_only import verify_lyrics_only
from svp_alignment.verification.placement_quality import summarize_quality


FIXTURE = Path(__file__).with_name('fixtures') / 'lyrics_placement_run_boy_run.json'
POLICY = 'word_note_groups_v1'


def chain():
    words = parse_words('hello')
    spans = [dict(word_index=0, source='hello', start=0., end=1., p=.9, chars=[])]
    syllables = syllable_evidence(words, spans)
    notes = [dict(lyrics=text) for text in ('hello', '-', '+')]
    actions = {
        0: dict(action='WORD_START', word_index=0, syllable_ids=[0], owner_note=0,
                review_status='AUTO_CANDIDATE', reason='', text='hello',
                source_start=0, source_end=3, source_text='hel', representation='WORD_PLUS'),
        1: dict(action='CONTINUE', word_index=0, syllable_ids=[0], owner_note=0,
                review_status='NEEDS_REVIEW', reason='sustain candidate', text='-',
                source_start=None, source_end=None, representation='WORD_PLUS'),
        2: dict(action='NEXT_SYLLABLE', word_index=0, syllable_ids=[1], owner_note=0,
                review_status='NEEDS_REVIEW', reason='estimated syllable', text='+',
                source_start=3, source_end=5, source_text='lo', representation='WORD_PLUS'),
    }
    alignment = dict(words=words, syllables=syllables, assignments={0: [0], 2: [1]},
                     continuations={1: 0}, unknown={1: 'sustain', 2: 'syllable'}, unplaced={},
                     lyric_fields={0: 'hello', 1: '-', 2: '+'}, placement_policy=POLICY,
                     note_actions=actions, word_spans={0: [0, 1, 2]})
    return words, alignment, notes


class PlacementVerificationTests(unittest.TestCase):
    def test_serialized_word_minus_plus_owns_original_word(self):
        words, alignment, notes = chain()
        verified = verify_placement(words, alignment, notes)
        self.assertEqual(('PASS', 'PASS', 1),
                         (verified['symbol_chains'], verified['source_accounting'], verified['placed_words']))

    def test_unassigned_original_between_head_and_plus_is_rejected(self):
        words, alignment, notes = chain()
        alignment['continuations'] = {}
        alignment['lyric_fields'].pop(1)
        notes[1]['lyrics'] = 'la'
        alignment['note_actions'][1] = dict(action='UNASSIGNED_ORIGINAL', word_index=None,
                                           syllable_ids=[], owner_note=None,
                                           review_status='NEEDS_REVIEW', reason='no evidence')
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)

    def test_minus_cannot_claim_a_later_or_different_attack(self):
        words, alignment, notes = chain()
        alignment['note_actions'][1]['owner_note'] = 2
        alignment['continuations'][1] = 2
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)

    def test_all_notes_must_be_classified_and_all_words_accounted(self):
        words, alignment, notes = chain()
        alignment['note_actions'].pop(1)
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)
        words, alignment, notes = chain()
        alignment['unplaced'][2] = 'outside original token range'
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)

    def test_actual_serialized_string_is_checked_before_semantic_pass(self):
        words, alignment, notes = chain()
        notes[0]['lyrics'] = 'la'
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)

    def test_exact_case_and_apostrophe_fragments_reconstruct_source(self):
        words = parse_words("We're")
        alignment = dict(words=words, syllables=[dict(word=0, part=0), dict(word=0, part=1)],
                         assignments={0: [0], 1: [1]}, continuations={}, unknown={}, unplaced={},
                         lyric_fields={0: 'We', 1: "'re"}, placement_policy=POLICY,
                         word_spans={0: [0, 1]}, note_actions={})
        for index, (start, end, text) in enumerate(((0, 2, 'We'), (2, 5, "'re"))):
            alignment['note_actions'][index] = dict(
                action='WORD_START' if index == 0 else 'TEXT_FRAGMENT', word_index=0,
                syllable_ids=[index], owner_note=index, review_status='NEEDS_REVIEW',
                reason='compressed spelling', source_start=start, source_end=end,
                source_text=text, text=text, representation='TEXT_FRAGMENTS')
        notes = [dict(lyrics='We'), dict(lyrics="'re")]
        self.assertEqual(1, verify_placement(words, alignment, notes)['placed_words'])
        alignment['note_actions'][1]['source_start'] = 1
        alignment['note_actions'][1]['source_text'] = "e're"
        with self.assertRaises(ValueError):
            verify_placement(words, alignment, notes)

    def test_quality_separates_unassigned_review_and_confirmation(self):
        rows = [dict(placement_policy=POLICY, placement_action=action,
                     review_status=review, symbol_risk=False)
                for action, review in [('UNASSIGNED_ORIGINAL', 'NEEDS_REVIEW'),
                                       ('CONTINUE', 'NEEDS_REVIEW'),
                                       ('WORD_START', 'USER_CONFIRMED'),
                                       ('WORD_START', 'AUTO_CANDIDATE')]]
        quality = summarize_quality(rows, [dict(note_numbers='1')])
        self.assertEqual((1, 1, 1, 0, False),
                         tuple(quality[key] for key in ('unresolved_notes', 'review_required_notes',
                                                       'confirmed_notes', 'symbol_risks', 'placement_complete')))
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        restored = list(csv.DictReader(io.StringIO(stream.getvalue())))
        self.assertEqual(quality, summarize_quality(restored, [dict(note_numbers='1')]))
        rows[0]['symbol_risk'] = 'false'
        self.assertFalse(summarize_quality(rows, [])['quality_known'])

    def test_legacy_unknown_quality_is_not_promoted_by_lyric_strings(self):
        quality = summarize_quality([dict(new_lyrics='-', assignment='ALIGNED')],
                                    [dict(note_numbers='1')])
        self.assertFalse(quality['quality_known'])
        for key in ('unresolved_notes', 'review_required_notes', 'confirmed_notes',
                    'symbol_risks', 'placement_complete'):
            self.assertIsNone(quality[key])

    def test_complete_automatic_placement_does_not_require_false_user_confirmation(self):
        row = dict(placement_policy=POLICY, placement_action='WORD_START',
                   review_status='AUTO_CANDIDATE', symbol_risk=False)
        self.assertTrue(summarize_quality([row], [dict(note_numbers='1')])['placement_complete'])
        self.assertFalse(summarize_quality([row], [dict(note_numbers='')])['placement_complete'])

    def test_manual_placement_without_observation_leaves_model_fields_empty(self):
        words = parse_words('go')
        original = [dict(start_s=0., end_s=1., lyrics='la')]
        spans = [dict(word_index=0, source='go', start=None, end=None, p=0.,
                      chars=[], status='UNKNOWN', reason='No supported observation')]
        initial = match_words_to_notes(words, spans, original)
        self.assertIn(0, initial['unplaced'])
        edited = apply_review_edit(initial, original, note_number=1, action='WORD_START',
                                   word_index=0, confirmed=True)
        final = [dict(original[0], lyrics=edited['lyric_fields'][0])]
        self.assertEqual(1, verify_placement(words, edited, final)['placed_words'])
        for model_id in ('MMS_FA', 'WAV2VEC2_ASR_LARGE_LV60K_960H', 'Qwen/Qwen3-ForcedAligner-0.6B'):
            with self.subTest(model=model_id):
                row = lyric_rows(words, edited, final, model_id=model_id)[0]
                self.assertEqual('go', row['svp_lyrics'])
                self.assertEqual('USER_CONFIRMED', row['review_status'])
                for field in ('ctc_starts_s', 'ctc_end_s', 'ctc_p', 'mms_onsets_s',
                              'observed_word_start_s', 'observed_word_end_s'):
                    self.assertEqual('', row[field])
                self.assertFalse(row['score_available'])

    def test_report_distinguishes_cached_observations_from_new_inference(self):
        inputs = dict(operation='lyrics_only', mode='general')
        provenance = dict(model_id='WAV2VEC2_ASR_LARGE_LV60K_960H', cache_reused=True)
        reused = markdown([], [], inputs, provenance)
        self.assertIn('같은 입력·모델·설정의 저장 관측 재사용: `RUN`. 새 추론: `NOT_RUN`', reused)
        self.assertNotIn('- 새 음성 강제 정렬: `RUN`', reused)
        fresh = markdown([], [], inputs, dict(provenance, cache_reused=False))
        self.assertIn('- 새 음성 강제 정렬: `RUN`', fresh)


class RunBoyRunPlacementRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        cls.cases = {case['name']: case for case in cls.fixture['cases']}

    def match(self, name):
        case = deepcopy(self.cases[name])
        before = deepcopy(case['notes'])
        result = match_words_to_notes(case['words'], case['aligned_words'], case['notes'])
        self.assertEqual(before, case['notes'])
        return case, result

    def test_documented_short_ctc_tail_becomes_reviewable_sustain(self):
        case, result = self.match('short_ctc_run_tail')
        target = self.fixture['documented_continuation']
        index = next(index for index, note in enumerate(case['notes'])
                     if note['note_id'] == target['note_id'])
        self.assertEqual(target['expected_lyrics'], result['lyric_fields'].get(index))
        self.assertEqual('CONTINUE', result['note_actions'][index]['action'])
        self.assertEqual('NEEDS_REVIEW', result['note_actions'][index]['review_status'])

    def test_fewer_notes_than_estimated_syllables_preserves_whole_source_token(self):
        for name, source in [('compressed_victory', 'victory'), ('single_note_behind', 'behind'),
                             ('first_tomorrow', 'Tomorrow'), ('repeated_tomorrow_another', 'Tomorrow')]:
            with self.subTest(case=name):
                case, result = self.match(name)
                word_index = next(word['word_index'] for word in case['words'] if word['source'] == source)
                self.assertNotIn(word_index, result['unplaced'])
                self.assertTrue(result['word_spans'][word_index])

    def test_outro_observation_is_reported_instead_of_moved_into_note_region(self):
        case, result = self.match('outro_observation_outside_notes')
        last = case['words'][-1]['word_index']
        self.assertEqual(177, case['words'][-1]['original_word_index'])
        self.assertIn(last, result['unplaced'])
        self.assertNotIn(last, result['word_spans'])
        self.assertGreater(case['aligned_words'][-1]['start'], max(note['end_s'] for note in case['notes']) + 50)

    def test_cases_roundtrip_preserve_every_non_lyric_field_and_semantic_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in self.cases:
                with self.subTest(case=name):
                    case, result = self.match(name)
                    data = dict(time=dict(tempo=[dict(position=0, bpm=120)], meter=[]),
                                library=[dict(uuid='fixture-group', notes=[note['note'] for note in case['notes']])],
                                tracks=[dict(name='fixture', mainGroup=dict(uuid='empty', notes=[]), mainRef={},
                                             groups=[dict(groupID='fixture-group')])])
                    document = SvpDocument(data)
                    records = document.target_notes()
                    updated = document.apply({records[index]['locator']: dict(lyrics=text)
                                              for index, text in result['lyric_fields'].items()})
                    verify_lyrics_only(document, updated)
                    output = Path(folder) / f'{name}.svp'
                    document.write(output, updated)
                    restored = SvpDocument.read(output).target_notes()
                    verified = verify_placement(case['words'], result, restored)
                    self.assertEqual(len(case['words']), verified['placed_words'] + verified['unplaced_words'])
                    self.assertEqual('PASS', verified['symbol_chains'])
                    evidence = [dict(start_reference=None, end_reference=None) for _ in records]
                    rows = note_rows(records, restored, result, evidence)
                    lyrics = lyric_rows(case['words'], result, restored)
                    quality = summarize_quality(rows, lyrics)
                    self.assertTrue(quality['quality_known'])
                    self.assertEqual(0, quality['symbol_risks'])


if __name__ == '__main__':
    unittest.main()
