"""Read-only input inspection and alignment calculation shared by GUI and CLI."""

import wave
from copy import deepcopy
from pathlib import Path

from .alignment.evidence import read_evidence, read_pitch_data, verify_evidence
from .alignment.lyrics import note_lyrics, source_words, syllable_evidence
from .alignment.matching import match_notes, review_status
from .alignment.timing import time_notes
from .prepared_alignment import PreparedAlignment
from .profiles.counting_stars import (ROOT, CONTRACT_INPUT_NAMES, SOURCE_HASHES,
    EXPECTED_WORD_COUNT, EXPECTED_LINE_COUNT, EXPECTED_DURATION, EXPECTED_BPM,
    EXPECTED_CHANNELS, EXPECTED_SAMPLE_RATE)
from .svp import BLICK_PER_SECOND, read_svp, song_notes
from .verification.preservation import verify_inputs


def _resolve_input(value):
    if value is None or not str(value).strip():
        raise ValueError('An original SVP, TXT and WAV path must be provided.')
    source = Path(str(value).strip()).expanduser()
    if not source.is_absolute():
        source = ROOT / source
    return source.resolve()


def _inspect(svp_path, lyric_path, audio_path):
    inputs = tuple(_resolve_input(value) for value in (svp_path, lyric_path, audio_path))
    verify_inputs(inputs)
    evidence_hashes = verify_evidence()
    try:
        original, suffix = read_svp(inputs[0])
        notes, reference, linked_audio = song_notes(original)
        with wave.open(str(inputs[2]), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
            channels, rate = audio.getnchannels(), audio.getframerate()
            if channels != EXPECTED_CHANNELS or rate != EXPECTED_SAMPLE_RATE:
                raise ValueError('Counting Stars WAV must be stereo PCM at 44100 Hz.')
        if duration != EXPECTED_DURATION or linked_audio['duration'] != EXPECTED_DURATION:
            raise ValueError('Counting Stars WAV and linked audio must both be 262.56 seconds.')
        words = source_words(inputs[1])
        if len(words) != EXPECTED_WORD_COUNT or not words or words[-1][0] != EXPECTED_LINE_COUNT:
            raise ValueError('Counting Stars lyrics must contain 527 words across the expected 81 lines.')
    except (OSError, wave.Error, UnicodeError, KeyError) as error:
        raise ValueError(f'Cannot inspect the selected Counting Stars input: {error}') from error
    mismatches = [dict(actual=source.name, expected=expected)
                  for source, expected in zip(inputs, CONTRACT_INPUT_NAMES) if source.name != expected]
    warnings = ['Existing observations are reused; no new WAV analysis or listening verification is performed.']
    if mismatches:
        warnings.append('Selected filenames differ from AGENTS.md contract names. '
                        'Their contents passed the fixed profile SHA-256 check; filenames were preserved.')
    summary = dict(paths=[str(source) for source in inputs], input_hashes=list(SOURCE_HASHES),
                   evidence_hashes=evidence_hashes, note_count=len(notes), word_count=len(words),
                   duration=duration, bpm=EXPECTED_BPM, group_id=reference['groupID'],
                   linked_audio=linked_audio, channels=channels, sample_rate=rate,
                   line_count=EXPECTED_LINE_COUNT, filename_mismatches=mismatches, warnings=warnings)
    verify_inputs(inputs)
    return summary, inputs, original, suffix, notes, linked_audio, words


def inspect_paths(svp_path, lyric_path, audio_path):
    """Validate the exact fixed profile and cached evidence; return JSON-safe metadata."""
    return _inspect(svp_path, lyric_path, audio_path)[0]


def _checkpoint(label, fraction, progress, cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('Alignment was cancelled at a stage boundary.')
    if progress is not None:
        progress(label, fraction)
    if cancelled is not None and cancelled():
        raise InterruptedError('Alignment was cancelled at a stage boundary.')


def prepare_paths(svp_path, lyric_path, audio_path, progress=None, cancelled=None):
    """Calculate an alignment without creating files or mutating the original document."""
    _checkpoint('입력 검사 시작', 0.0, progress, cancelled)
    summary, inputs, original, suffix, notes, linked_audio, words = _inspect(
        svp_path, lyric_path, audio_path)
    _checkpoint('입력 및 기존 분석 자료 검사 완료', 0.2, progress, cancelled)
    acoustic = ROOT / 'work' / 'acoustic'
    en = read_evidence(acoustic / 'en_ctc_words.json', words)
    mms = read_evidence(acoustic / 'mms_ctc_words.json', words)
    syllables = syllable_evidence(en, mms)
    _checkpoint('기존 발음 관측 자료 읽기 완료', 0.4, progress, cancelled)
    assignments, continuations = match_notes(syllables, notes)
    unknown = review_status(syllables, notes, assignments, continuations)
    _checkpoint('가사와 기존 음표 대응 완료', 0.6, progress, cancelled)
    pitch, frames = read_pitch_data(ROOT / 'work' / 'pitch')
    duration = summary['duration']
    times, evidence = time_notes(notes, assignments, continuations, syllables, pitch, frames, duration)
    _checkpoint('기존 관측 자료 기준 타이밍 계산 완료', 0.8, progress, cancelled)
    updated = deepcopy(original)
    new_notes, _, _ = song_notes(updated)
    display = note_lyrics(assignments, syllables)
    for index, (note, (start, end)) in enumerate(zip(new_notes, times)):
        note['onset'] = round(start * BLICK_PER_SECOND)
        note['duration'] = round(end * BLICK_PER_SECOND) - note['onset']
        if index in display:
            note['lyrics'] = display[index]
        elif index in continuations:
            note['lyrics'] = '-'
    verify_inputs(inputs)
    verify_evidence()
    _checkpoint('수정본 계산과 입력 보존 확인 완료', 1.0, progress, cancelled)
    return PreparedAlignment(inputs, original, updated, suffix, duration, linked_audio, words,
                             syllables, assignments, continuations, unknown, evidence)
