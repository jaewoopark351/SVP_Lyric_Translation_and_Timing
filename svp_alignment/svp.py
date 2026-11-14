"""SVP document boundary: references, format units and lossless suffix retention."""

import json
from pathlib import Path

from .profiles.counting_stars import EXPECTED_BPM, EXPECTED_NOTE_COUNT


BLICK_PER_SECOND = 1_411_200_000  # 705600000 per quarter note at 120 BPM.


def read_svp(path):
    data = Path(path).read_bytes()
    json_bytes = data.rstrip(b'\0')
    return json.loads(json_bytes.decode('utf-8-sig')), data[len(json_bytes):]


def song_notes(project):
    """Resolve the supported profile's actual referenced vocal note group."""
    try:
        if project['time']['tempo'] != [{'position': 0, 'bpm': EXPECTED_BPM}]:
            raise ValueError('Unsupported SVP tempo: Counting Stars requires constant 120 BPM.')
        if project['time']['startTimeSeconds'] != 0:
            raise ValueError('Unsupported SVP timeline: startTimeSeconds must be zero.')
        if project['time']['meter'] != [{'index': 0, 'numerator': 4, 'denominator': 4}]:
            raise ValueError('Unsupported SVP meter: Counting Stars requires 4/4.')
        if len(project['tracks']) != 2:
            raise ValueError('Counting Stars requires exactly one vocal and one audio track.')
        vocal, audio = project['tracks']
        if len(vocal['groups']) != 1:
            raise ValueError('Ambiguous vocal group: exactly one referenced group is supported.')
        reference, = vocal['groups']
        audio_ref = audio['mainRef']
        groups = [group for group in project['library'] if group['uuid'] == reference['groupID']]
        if len(groups) != 1:
            raise ValueError('The vocal group reference must resolve to one library group.')
        if reference['isInstrumental'] or not audio_ref['isInstrumental']:
            raise ValueError('The expected vocal/audio track references do not match.')
        if any(ref['blickOffset'] != 0 or ref['blickAbsoluteBegin'] != 0
               for ref in (reference, audio_ref)):
            raise ValueError('Unsupported group/audio offset: both must start at zero.')
        linked_path = Path(audio_ref['audio']['filename'])
        if not linked_path.is_absolute():
            raise ValueError('Relative linked audio paths are not supported by this profile; the reference is preserved.')
        if not linked_path.is_file():
            raise ValueError(f'The SVP linked audio file is missing: {linked_path}')
        notes = groups[0]['notes']
        if len(notes) != EXPECTED_NOTE_COUNT or len({note['uuid'] for note in notes}) != EXPECTED_NOTE_COUNT:
            raise ValueError('Counting Stars requires exactly 715 distinct notes in the referenced group.')
        return notes, reference, audio_ref['audio']
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError(f'Unsupported or malformed Counting Stars SVP structure: {error}') from error


def note_times(note):
    return (note['onset'] / BLICK_PER_SECOND,
            (note['onset'] + note['duration']) / BLICK_PER_SECOND)


def write_svp(path, project, suffix):
    encoded = json.dumps(project, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    with Path(path).open('xb') as output:
        output.write(encoded + suffix)
