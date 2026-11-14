"""General SVP document references, note locators and preservation boundary."""

from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path, PureWindowsPath

from .tempo_map import TempoMap

EDITABLE_FIELDS = frozenset({'onset', 'duration', 'lyrics'})


def _at(data, locator):
    value = data
    for part in locator:
        value = value[part]
    return value


def _integer(value, description):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f'{description} must be integer blicks.')
    return value


def _finite(value, description):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f'{description} must be a finite number.')
    return value


def _note_fields(note):
    if not isinstance(note, dict):
        raise ValueError('SVP notes must be objects.')
    onset = _integer(note.get('onset'), 'Note onset')
    duration = _integer(note.get('duration'), 'Note duration')
    if duration <= 0:
        raise ValueError('SVP note durations must be positive.')
    _finite(note.get('pitch'), 'Note pitch')
    if 'detune' in note:
        _finite(note['detune'], 'Note detune')
    if 'lyrics' in note and not isinstance(note['lyrics'], str):
        raise ValueError('SVP note lyrics must be text.')
    return onset, duration


class SvpDocument:
    """Own the original document and exclusively edit selected existing notes."""

    def __init__(self, data, suffix=b'', input_path=None, uploaded=False):
        if not isinstance(data, dict):
            raise ValueError('SVP root must be a JSON object.')
        self.data = deepcopy(data)
        self.suffix = bytes(suffix)
        self.input_path = Path(input_path).resolve() if input_path is not None else None
        self.uploaded = bool(uploaded)
        time = self.data.get('time')
        if not isinstance(time, dict):
            raise ValueError('SVP time axis is missing.')
        self.tempo = TempoMap(time.get('tempo'), time.get('startTimeSeconds', 0.0))
        if not isinstance(self.data.get('tracks'), list):
            raise ValueError('SVP tracks must be an array.')
        if not isinstance(self.data.get('library', []), list):
            raise ValueError('SVP library must be an array.')
        self._inventory()

    @classmethod
    def read(cls, path, uploaded=False):
        source = Path(path).resolve(strict=True)
        raw = source.read_bytes()
        encoded = raw.rstrip(b'\0')
        try:
            data = json.loads(encoded.decode('utf-8-sig'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'Invalid JSON number: {value}')))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f'Cannot parse SVP JSON: {error}') from error
        return cls(data, raw[len(encoded):], source, uploaded)

    def _inventory(self):
        library = self.data.get('library', [])
        by_id = {}
        for index, group in enumerate(library):
            if not isinstance(group, dict) or not isinstance(group.get('uuid'), str):
                raise ValueError('SVP library groups require string UUIDs.')
            if group['uuid'] in by_id:
                raise ValueError(f'Ambiguous duplicate library group UUID: {group["uuid"]}')
            by_id[group['uuid']] = (index, group)
        groups, audio = [], []
        for track_index, track in enumerate(self.data['tracks']):
            if not isinstance(track, dict):
                raise ValueError('SVP tracks must be objects.')
            references = track.get('groups', [])
            if not isinstance(references, list):
                raise ValueError('SVP track groups must be an array.')
            main_group = track.get('mainGroup')
            main_ref = track.get('mainRef', {})
            candidates = [(main_ref, ('tracks', track_index, 'mainRef'), main_group,
                           ('tracks', track_index, 'mainGroup'), 'main')]
            for ref_index, reference in enumerate(references):
                if not isinstance(reference, dict):
                    raise ValueError('SVP group references must be objects.')
                if reference.get('isInstrumental') or 'audio' in reference:
                    candidates.append((reference, ('tracks', track_index, 'groups', ref_index), None, None, 'audio'))
                    continue
                group_id = reference.get('groupID')
                if group_id not in by_id:
                    raise ValueError(f'Unresolved SVP group reference: {group_id}')
                library_index, group = by_id[group_id]
                candidates.append((reference, ('tracks', track_index, 'groups', ref_index), group,
                                   ('library', library_index), 'library'))
            for reference, reference_path, group, group_path, kind in candidates:
                if not isinstance(reference, dict):
                    raise ValueError('SVP mainRef must be an object.')
                offset = _integer(reference.get('blickOffset', 0), 'Reference blickOffset')
                pitch_offset = _finite(reference.get('pitchOffset', 0), 'Reference pitchOffset')
                if reference.get('isInstrumental') or 'audio' in reference:
                    linked = reference.get('audio')
                    if not isinstance(linked, dict) or not isinstance(linked.get('filename'), str):
                        raise ValueError('Instrumental SVP reference requires an audio filename.')
                    audio.append(dict(track_index=track_index, reference_path=reference_path,
                                      ref_id=reference.get('uuid', ''), audio=deepcopy(linked),
                                      blick_offset=offset, pitch_offset=pitch_offset,
                                      start_s=self.tempo.blick_to_seconds(offset)))
                    continue
                if group is None:
                    continue
                if not isinstance(group, dict) or not isinstance(group.get('notes', []), list):
                    raise ValueError('SVP groups require a notes array.')
                if kind == 'main' and reference.get('groupID') is not None and reference['groupID'] != group.get('uuid'):
                    raise ValueError('SVP mainRef does not reference its track mainGroup.')
                notes = group.get('notes', [])
                for note in notes:
                    _note_fields(note)
                if not notes:
                    continue
                begin = reference.get('blickAbsoluteBegin', -1)
                end = reference.get('blickAbsoluteEnd', -1)
                _integer(begin, 'Reference blickAbsoluteBegin')
                _integer(end, 'Reference blickAbsoluteEnd')
                if begin >= 0 and end >= 0 and end <= begin:
                    raise ValueError('SVP reference clip range must have positive duration.')
                groups.append(dict(track_index=track_index, track_name=track.get('name', ''),
                                   group_id=group.get('uuid', reference.get('groupID', '')),
                                   ref_id=reference.get('uuid', ''), group_kind=kind,
                                   group_path=group_path, reference_path=reference_path,
                                   blick_offset=offset, pitch_offset=pitch_offset,
                                   clip_begin=begin, clip_end=end, notes=notes,
                                   muted=bool(reference.get('mute', False))))
        counts = Counter(group['group_path'] for group in groups)
        for group in groups:
            group['reference_count'] = counts[group['group_path']]
        return groups, audio

    def inspect(self):
        groups, audio = self._inventory()
        warnings = []
        candidates = []
        for group in groups:
            notes = group['notes']
            onsets = [note['onset'] for note in notes]
            if onsets != sorted(onsets):
                warnings.append(f'Group {group["group_id"]} has unsorted original note onsets; automatic editing is unsupported.')
            if any(first['onset'] + first['duration'] > second['onset'] for first, second in zip(notes, notes[1:])):
                warnings.append(f'Group {group["group_id"]} has existing overlapping notes; these overlaps are preserved unless reduced.')
            if group['reference_count'] > 1:
                warnings.append(f'Group {group["group_id"]} is shared by {group["reference_count"]} references; automatic occurrence editing is unsupported.')
            candidate = {key: deepcopy(value) for key, value in group.items() if key != 'notes'}
            candidate['note_count'] = len(notes)
            candidate['start_s'] = min(self.tempo.blick_to_seconds(note['onset'] + group['blick_offset']) for note in notes)
            candidate['end_s'] = max(self.tempo.blick_to_seconds(note['onset'] + note['duration'] + group['blick_offset']) for note in notes)
            candidates.append(candidate)
        linked_audio = []
        for item in audio:
            linked = deepcopy(item)
            filename = item['audio']['filename']
            source = Path(filename)
            absolute = source.is_absolute() or PureWindowsPath(filename).is_absolute()
            linked['filename'] = filename
            linked['absolute'] = absolute
            if absolute:
                linked['resolved_path'] = str(source)
                linked['exists'] = source.is_file()
                if not linked['exists']:
                    warnings.append(f'Linked audio is missing: {filename}. The uploaded WAV can be used independently; the SVP reference is preserved.')
            elif self.uploaded or self.input_path is None:
                linked['resolved_path'] = None
                linked['exists'] = None
                warnings.append(f'Cannot recover the original directory for relative linked audio: {filename}. The reference is preserved.')
            else:
                resolved = (self.input_path.parent / source).resolve()
                linked['resolved_path'] = str(resolved)
                linked['exists'] = resolved.is_file()
                if not linked['exists']:
                    warnings.append(f'Relative linked audio is missing: {filename}. The reference is preserved.')
            linked_audio.append(linked)
        track_counts = Counter(group['track_index'] for group in groups)
        vocal_tracks = [dict(track_index=index, name=self.data['tracks'][index].get('name', ''),
                             group_count=count, note_count=sum(len(g['notes']) for g in groups if g['track_index'] == index))
                        for index, count in sorted(track_counts.items())]
        if len(vocal_tracks) > 1:
            warnings.append('Multiple vocal tracks contain notes. Select an explicit track_index before editing.')
        if len(audio) == 1:
            audio_offset = audio[0]['start_s']
            warnings.append('Uploaded WAV timing is assumed to share the single linked audio reference origin; audio_offset is applied without loading that external audio.')
        else:
            audio_offset = 0.0
            warnings.append('No single linked audio origin is available; uploaded WAV time zero is assumed to be project second zero (audio_offset=0).')
        return dict(input_path=str(self.input_path) if self.input_path is not None else None,
                    uploaded=self.uploaded, track_count=len(self.data['tracks']), vocal_tracks=vocal_tracks,
                    target_groups=candidates, note_count=sum(len(group['notes']) for group in groups),
                    tempo=deepcopy(self.data['time']['tempo']), meter=deepcopy(self.data['time'].get('meter', [])),
                    start_time_seconds=self.tempo.start_time_seconds, audio_offset=audio_offset, linked_audio=linked_audio, warnings=warnings)

    def target_notes(self, track_index=None, project=None):
        if project is not None:
            original_order = self.target_notes(track_index)
            edited = SvpDocument(project, self.suffix, self.input_path, self.uploaded).target_notes(track_index)
            by_locator = {record['locator']: record for record in edited}
            if set(by_locator) != {record['locator'] for record in original_order}:
                raise ValueError('Edited SVP target note locators differ from the original document.')
            result = [by_locator[record['locator']] for record in original_order]
            for index, record in enumerate(result):
                record['globalindex'] = record['note_index'] = index
            return result
        groups, _ = self._inventory()
        tracks = sorted({group['track_index'] for group in groups})
        if not tracks:
            raise ValueError('No referenced vocal notes were found in the SVP project.')
        if track_index is None:
            if len(tracks) != 1:
                raise ValueError(f'Multiple vocal tracks contain notes ({tracks}); select track_index explicitly.')
            track_index = tracks[0]
        if track_index not in tracks:
            raise ValueError(f'The selected track has no vocal notes: {track_index}')
        selected = [group for group in groups if group['track_index'] == track_index]
        result = []
        for group in selected:
            if group['reference_count'] != 1:
                raise ValueError(f'Cannot edit shared library group {group["group_id"]}: it has multiple references.')
            onsets = [note['onset'] for note in group['notes']]
            if onsets != sorted(onsets):
                raise ValueError(f'Cannot align unsorted original note onsets in group {group["group_id"]}.')
            for index, note in enumerate(group['notes']):
                onset, duration = _note_fields(note)
                absolute_onset = onset + group['blick_offset']
                absolute_end = absolute_onset + duration
                if (group['clip_begin'] >= 0 and absolute_onset < group['clip_begin']) or (group['clip_end'] >= 0 and absolute_end > group['clip_end']):
                    raise ValueError(f'Group {group["group_id"]} contains notes clipped by its reference range; automatic editing is unsupported.')
                locator = (*group['group_path'], 'notes', index)
                note_id = note.get('uuid', '/'.join(map(str, locator)))
                result.append(dict(locator=locator, noteID=note_id, note_id=note_id, note=deepcopy(note),
                                   track_index=track_index, group_id=group['group_id'], ref_id=group['ref_id'],
                                   group_kind=group['group_kind'], original_note_index=index,
                                   reference_path=group['reference_path'], onset=onset, duration=duration,
                                   pitch=note['pitch'], detune=note.get('detune', 0), lyrics=note.get('lyrics', ''),
                                   blick_offset=group['blick_offset'], pitch_offset=group['pitch_offset'],
                                   effective_pitch=note['pitch'] + group['pitch_offset'],
                                   clip_begin=group['clip_begin'], clip_end=group['clip_end'],
                                   start_s=self.tempo.blick_to_seconds(absolute_onset),
                                   end_s=self.tempo.blick_to_seconds(absolute_end)))
        result.sort(key=lambda item: (item['start_s'], item['track_index'], item['reference_path'], item['original_note_index']))
        for index, item in enumerate(result):
            item['globalindex'] = item['note_index'] = index
        return result

    def seconds_to_local_blick(self, record, absolute_seconds):
        return round(self.tempo.seconds_to_blick(absolute_seconds)) - record['blick_offset']

    def apply(self, changes, track_index=None):
        records = self.target_notes(track_index)
        allowed = {record['locator'] for record in records}
        if not isinstance(changes, dict):
            raise ValueError('SVP changes must map original note locators to editable fields.')
        updated = deepcopy(self.data)
        for locator, fields in changes.items():
            if locator not in allowed:
                raise ValueError(f'Cannot edit a note outside the selected target groups: {locator}')
            if not isinstance(fields, dict) or not set(fields).issubset(EDITABLE_FIELDS):
                raise ValueError('Only onset, duration and lyrics may be changed in target notes.')
            _at(updated, locator).update(deepcopy(fields))
        self.verify(updated, track_index)
        return updated

    def verify(self, updated, track_index=None):
        records = self.target_notes(track_index)
        before, after = deepcopy(self.data), deepcopy(updated)
        try:
            for record in records:
                original_note, changed_note = _at(before, record['locator']), _at(after, record['locator'])
                _note_fields(changed_note)
                for field in EDITABLE_FIELDS:
                    original_note.pop(field, None)
                    changed_note.pop(field, None)
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError('SVP target note identity or count changed.') from error
        if before != after:
            raise ValueError('Unexpected SVP metadata, group, pitch, note identity, count or order change.')
        new_absolute_onsets = [_at(updated, record['locator'])['onset'] + record['blick_offset'] for record in records]
        if any(first > second for first, second in zip(new_absolute_onsets, new_absolute_onsets[1:])):
            raise ValueError('SVP note onset order changed across the selected vocal groups.')
        by_group = {}
        for record in records:
            by_group.setdefault(record['locator'][:-2], []).append(record)
        for group_records in by_group.values():
            group_records.sort(key=lambda record: record['original_note_index'])
            for first, second in zip(group_records, group_records[1:]):
                new_first = _at(updated, first['locator'])
                new_second = _at(updated, second['locator'])
                if new_first['onset'] > new_second['onset']:
                    raise ValueError('SVP note onset order changed within a target group.')
                old_overlap = max(0, first['onset'] + first['duration'] - second['onset'])
                new_overlap = max(0, new_first['onset'] + new_first['duration'] - new_second['onset'])
                if new_overlap > old_overlap:
                    raise ValueError('SVP timing changes introduce or increase a note overlap.')
            for record in group_records:
                note = _at(updated, record['locator'])
                absolute_onset = note['onset'] + record['blick_offset']
                absolute_end = absolute_onset + note['duration']
                if (record['clip_begin'] >= 0 and absolute_onset < record['clip_begin']) or (record['clip_end'] >= 0 and absolute_end > record['clip_end']):
                    raise ValueError('SVP timing changes exceed the preserved reference clip range.')
        return True

    def write(self, path, updated=None, track_index=None):
        destination = Path(path).resolve()
        if self.input_path is not None and destination == self.input_path:
            raise ValueError('The original SVP is read-only; choose a new output path.')
        data = self.data if updated is None else updated
        self.verify(data, track_index)
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
        with destination.open('xb') as stream:
            stream.write(encoded + self.suffix)
        written = self.read(destination, uploaded=self.uploaded)
        if written.suffix != self.suffix or written.data != data:
            raise ValueError('Written SVP does not match the verified document and original suffix.')
        self.verify(written.data, track_index)
        return destination


def read_project(path, uploaded=False):
    return SvpDocument.read(path, uploaded=uploaded)
