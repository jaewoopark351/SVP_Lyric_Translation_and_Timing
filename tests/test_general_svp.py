"""General SVP timing/reference semantics and original-preservation contracts."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from svp_alignment.project import BLICK_PER_QUARTER as Q, SvpDocument, TempoMap, read_project

ROOT = Path(__file__).resolve().parents[1]


def note(index, onset=0, duration=Q, pitch=60):
    return dict(uuid=f'n{index}', onset=onset, duration=duration, pitch=pitch,
                detune=7, lyrics='la', phonemes='l aa', attributes={'muted': False})


def reference(group_id, offset=0, pitch_offset=0):
    return dict(uuid=f'ref-{group_id}', groupID=group_id, blickOffset=offset,
                pitchOffset=pitch_offset, blickAbsoluteBegin=-1, blickAbsoluteEnd=-1,
                isInstrumental=False, voice={'paramLoudness': -1.5})


def project():
    return dict(version=153, arbitrary={'keep': ['all', 3]},
                time=dict(tempo=[{'position': 0, 'bpm': 120}],
                          meter=[{'index': 0, 'numerator': 4, 'denominator': 4}], startTimeSeconds=0),
                library=[dict(uuid='lib', notes=[note(1, 0), note(2, Q * 2)])],
                tracks=[dict(name='Vocal', mainRef=reference('main'),
                             mainGroup=dict(uuid='main', notes=[]), groups=[reference('lib')])])


class TempoMapTests(unittest.TestCase):
    def test_piecewise_integration_inverse_and_negative_extrapolation(self):
        marks = [{'position': 0, 'bpm': 120}, {'position': 4 * Q, 'bpm': 60},
                 {'position': 6 * Q, 'bpm': 240}]
        original = deepcopy(marks)
        clock = TempoMap(marks, start_time_seconds=1.25)
        for tick, seconds in ((-Q, .75), (0, 1.25), (4 * Q, 3.25),
                              (5 * Q, 4.25), (6 * Q, 5.25), (8 * Q, 5.75)):
            self.assertAlmostEqual(clock.blick_to_seconds(tick), seconds)
            self.assertAlmostEqual(clock.seconds_to_blick(seconds), tick)
        self.assertEqual(marks, original)

    def test_bad_tempo_maps_are_rejected(self):
        invalid = ([], [{'position': 1, 'bpm': 120}], [{'position': 0, 'bpm': 0}],
                   [{'position': 0, 'bpm': float('nan')}],
                   [{'position': 0, 'bpm': 120}, {'position': 0, 'bpm': 60}])
        for marks in invalid:
            with self.subTest(marks=marks), self.assertRaises(ValueError):
                TempoMap(marks)


class GeneralSvpTests(unittest.TestCase):
    def test_library_and_main_groups_combine_without_moving_source_arrays(self):
        data = project()
        data['time']['startTimeSeconds'] = 2.0
        data['time']['tempo'].append({'position': Q * 4, 'bpm': 60})
        data['tracks'][0]['groups'][0]['blickOffset'] = Q * 4
        data['tracks'][0]['groups'][0]['pitchOffset'] = -12
        data['tracks'][0]['mainGroup']['notes'] = [note(3, Q)]
        original = deepcopy(data)
        document = SvpDocument(data)
        records = document.target_notes()
        self.assertEqual([item['locator'] for item in records],
                         [('tracks', 0, 'mainGroup', 'notes', 0), ('library', 0, 'notes', 0), ('library', 0, 'notes', 1)])
        self.assertEqual([item['globalindex'] for item in records], [0, 1, 2])
        self.assertEqual([item['start_s'] for item in records], [2.5, 4.0, 6.0])
        self.assertEqual(records[1]['effective_pitch'], 48)
        self.assertEqual(document.seconds_to_local_blick(records[1], 4.5), Q // 2)
        self.assertEqual(data, original)
        self.assertEqual(document.data, original)
        json.dumps(document.inspect())

    def test_edited_records_keep_original_correspondence_when_group_onsets_tie(self):
        data = project()
        data['tracks'][0]['mainGroup']['notes'] = [note(3)]
        data['tracks'][0]['groups'][0]['blickOffset'] = Q
        document = SvpDocument(data)
        original = document.target_notes()
        first_library = original[1]
        updated = document.apply({first_library['locator']: {'onset': -Q}})
        edited = document.target_notes(project=updated)
        self.assertEqual([row['noteID'] for row in edited], [row['noteID'] for row in original])
        self.assertEqual([row['globalindex'] for row in edited], [0, 1, 2])
        with self.assertRaisesRegex(ValueError, 'across'):
            document.apply({first_library['locator']: {'onset': -2 * Q}})

    def test_multiple_vocal_tracks_need_explicit_selection(self):
        data = project()
        data['tracks'].append(dict(name='Harmony', groups=[], mainRef=reference('harmony'),
                                   mainGroup=dict(uuid='harmony', notes=[note(5)])))
        document = SvpDocument(data)
        self.assertEqual(len(document.inspect()['vocal_tracks']), 2)
        with self.assertRaisesRegex(ValueError, 'Multiple vocal tracks'):
            document.target_notes()
        selected = document.target_notes(track_index=1)
        self.assertEqual(len(selected), 1)
        updated = document.apply({selected[0]['locator']: {'lyrics': 'new'}}, track_index=1)
        self.assertEqual(updated['library'], data['library'])
        self.assertTrue(document.verify(updated, track_index=1))

    def test_shared_library_group_is_visible_but_not_independently_editable(self):
        data = project()
        data['tracks'][0]['groups'].append(reference('lib', Q * 8))
        document = SvpDocument(data)
        self.assertEqual(document.inspect()['target_groups'][0]['reference_count'], 2)
        with self.assertRaisesRegex(ValueError, 'shared library group'):
            document.target_notes()

    def test_missing_reference_and_duplicate_group_ids_are_rejected(self):
        data = project()
        data['tracks'][0]['groups'][0]['groupID'] = 'missing'
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            SvpDocument(data)
        data = project()
        data['library'].append(deepcopy(data['library'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            SvpDocument(data)

    def test_allowed_updates_preserve_all_other_project_fields(self):
        data = project()
        document = SvpDocument(data)
        first = document.target_notes()[0]
        updated = document.apply({first['locator']: {'onset': Q // 4, 'duration': Q // 2, 'lyrics': 'hello'}})
        self.assertTrue(document.verify(updated))
        self.assertEqual(document.data, data)
        self.assertEqual(document.target_notes(project=updated)[0]['start_s'], .125)
        self.assertEqual(updated['library'][0]['notes'][0]['pitch'], 60)
        with self.assertRaisesRegex(ValueError, 'Only onset'):
            document.apply({first['locator']: {'pitch': 61}})
        for mutate in ('pitch', 'order', 'count', 'settings'):
            bad = deepcopy(updated)
            if mutate == 'pitch':
                bad['library'][0]['notes'][0]['pitch'] += 1
            elif mutate == 'order':
                bad['library'][0]['notes'].reverse()
            elif mutate == 'count':
                bad['library'][0]['notes'].append(note(6, 4 * Q))
            else:
                bad['tracks'][0]['mainRef']['voice']['paramLoudness'] = 0
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                document.verify(bad)

    def test_new_overlap_or_onset_inversion_is_rejected(self):
        document = SvpDocument(project())
        first, second = document.target_notes()
        with self.assertRaisesRegex(ValueError, 'overlap'):
            document.apply({first['locator']: {'duration': 3 * Q}})
        with self.assertRaisesRegex(ValueError, 'order'):
            document.apply({first['locator']: {'onset': 3 * Q}})
        with self.assertRaisesRegex(ValueError, 'positive'):
            document.apply({second['locator']: {'duration': 0}})

    def test_original_overlap_is_reported_and_can_only_be_preserved_or_reduced(self):
        data = project()
        data['library'][0]['notes'][0]['duration'] = 3 * Q
        document = SvpDocument(data)
        self.assertTrue(any('existing overlapping' in text for text in document.inspect()['warnings']))
        self.assertTrue(document.verify(data))
        first = document.target_notes()[0]
        self.assertTrue(document.verify(document.apply({first['locator']: {'duration': Q}})))
        with self.assertRaisesRegex(ValueError, 'overlap'):
            document.apply({first['locator']: {'duration': 4 * Q}})

    def test_clip_bounds_are_preserved_and_cropped_notes_are_not_silently_edited(self):
        data = project()
        data['tracks'][0]['groups'][0]['blickAbsoluteBegin'] = 0
        data['tracks'][0]['groups'][0]['blickAbsoluteEnd'] = 4 * Q
        document = SvpDocument(data)
        last = document.target_notes()[-1]
        with self.assertRaisesRegex(ValueError, 'clip range'):
            document.apply({last['locator']: {'duration': 3 * Q}})
        data['tracks'][0]['groups'][0]['blickAbsoluteEnd'] = Q * 2
        document = SvpDocument(data)
        document.inspect()
        with self.assertRaisesRegex(ValueError, 'clipped'):
            document.target_notes()

    def test_audio_origin_uses_tempo_and_offset_without_requiring_linked_file(self):
        data = project()
        data['time']['startTimeSeconds'] = 1.0
        data['tracks'].append(dict(name='Audio', groups=[], mainGroup=dict(uuid='audio', notes=[]),
                                   mainRef=dict(isInstrumental=True, blickOffset=4 * Q, pitchOffset=0,
                                                audio=dict(filename='Z:/missing/example.wav', duration=12.0))))
        information = SvpDocument(data, uploaded=True).inspect()
        self.assertEqual(information['audio_offset'], 3.0)
        self.assertFalse(information['linked_audio'][0]['exists'])
        self.assertTrue(any('missing' in text for text in information['warnings']))
        data['tracks'][1]['mainRef']['audio']['filename'] = '../original/example.wav'
        information = SvpDocument(data, input_path=ROOT / 'work/uploads/example.svp', uploaded=True).inspect()
        self.assertIsNone(information['linked_audio'][0]['resolved_path'])
        self.assertTrue(any('original directory' in text for text in information['warnings']))
        data['tracks'].pop()
        self.assertEqual(SvpDocument(data).inspect()['audio_offset'], 0.0)

    def test_serialization_preserves_suffix_and_refuses_source_or_existing_output(self):
        with tempfile.TemporaryDirectory(prefix='general-svp-', dir=ROOT / 'work') as temporary:
            folder = Path(temporary).resolve()
            self.assertTrue(folder.is_relative_to(ROOT.resolve()))
            source = folder / '원본 프로젝트.svp'
            data = project()
            original_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8') + b'\0\0'
            source.write_bytes(original_bytes)
            document = read_project(source, uploaded=True)
            self.assertEqual(document.suffix, b'\0\0')
            first = document.target_notes()[0]
            updated = document.apply({first['locator']: {'lyrics': 'hello'}})
            destination = folder / '새 결과.svp'
            document.write(destination, updated)
            self.assertEqual(read_project(destination).data, updated)
            self.assertEqual(read_project(destination).suffix, document.suffix)
            self.assertEqual(source.read_bytes(), original_bytes)
            with self.assertRaisesRegex(ValueError, 'read-only'):
                document.write(source, updated)
            with self.assertRaises(FileExistsError):
                document.write(destination, updated)

    def test_actual_uploaded_shooting_stars_shape_when_available(self):
        sources = list((ROOT / 'work/uploads').rglob('Shooting Stars 여자 커버.svp'))
        if not sources:
            self.skipTest('Optional user-uploaded integration sample is unavailable.')
        source = sources[0]
        original_bytes = source.read_bytes()
        document = read_project(source, uploaded=True)
        records = document.target_notes()
        self.assertEqual(len(records), 281)
        self.assertEqual(records[0]['group_kind'], 'library')
        self.assertEqual(document.inspect()['audio_offset'], 0.0)
        self.assertEqual(records[0]['start_s'], 40.775)
        self.assertEqual(records[-1]['end_s'], 208.28)
        self.assertTrue(document.verify(document.apply({})))
        self.assertEqual(source.read_bytes(), original_bytes)


if __name__ == '__main__':
    unittest.main()
