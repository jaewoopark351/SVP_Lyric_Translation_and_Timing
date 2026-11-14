"""Input fingerprints and SVP preservation validation."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from ..svp import BLICK_PER_SECOND, read_svp, song_notes
from ..profiles.counting_stars import SOURCE_HASHES


EDITABLE = ('onset', 'duration', 'lyrics')


def file_hash(path):
    digest = sha256()
    with Path(path).open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs(paths):
    paths = tuple(Path(path) for path in paths)
    if len(paths) != len(SOURCE_HASHES):
        raise ValueError('Counting Stars requires three original files in SVP, TXT, WAV order.')
    for source, expected in zip(paths, SOURCE_HASHES):
        if not source.is_file():
            raise ValueError(f'Input file does not exist: {source}')
        actual = file_hash(source)
        if actual != expected:
            raise ValueError(f'Input does not match the verified Counting Stars profile: {source} '
                             f'(SHA-256 expected {expected}, actual {actual}). '
                             'Existing observations cannot be reused for changed inputs.')


def verify_svp(original, original_suffix, path, audio_duration):
    edited, suffix = read_svp(path)
    assert suffix == original_suffix
    original_notes, ref, original_audio = song_notes(original)
    edited_notes, _, audio = song_notes(edited)
    assert edited_notes[-1]['onset'] + edited_notes[-1]['duration'] <= ref['blickAbsoluteEnd']
    assert audio == original_audio and Path(audio['filename']).is_file()
    before = deepcopy(original)
    after = deepcopy(edited)
    for normalized in (before, after):
        for note in song_notes(normalized)[0]:
            for field in EDITABLE:
                note.pop(field)
    assert before == after, 'Unexpected project metadata, note, or note-order change'
    for index, note in enumerate(edited_notes):
        end = note['onset'] + note['duration']
        assert note['duration'] > 0 and note['onset'] >= 0 and end <= audio_duration * BLICK_PER_SECOND
        assert index == len(edited_notes) - 1 or end <= edited_notes[index + 1]['onset']
    return original_notes, edited_notes


