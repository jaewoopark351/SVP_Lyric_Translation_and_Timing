"""Lyric token parsing and syllable representation for the supported profile."""

import re
from collections import defaultdict
from statistics import mean

from ..profiles.counting_stars import MULTISYLLABLE, NUCLEUS, REPEATS, REPEAT_OFFSETS


def source_words(path):
    return [(line, match.start() + 1, match.group())
            for line, text in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1)
            for match in re.finditer(r"[A-Za-z']+", text)]


def syllable_evidence(en, mms):
    result = []
    by_position = defaultdict(list)
    for word_index, (word, alternative) in enumerate(zip(en, mms)):
        source = word['source']
        spelling = source.lower()
        parts = MULTISYLLABLE.get(spelling, (spelling,))
        assert ''.join(parts) == spelling
        part_start = 0
        for position, part in enumerate(parts):
            chars = word['chars'][part_start:part_start + len(part)]
            alt = alternative['chars'][part_start:part_start + len(part)]
            nucleus_letter = NUCLEUS.get(part)
            if nucleus_letter is None:
                nucleus_letter = next((letter for letter in part if letter in 'aeiouy'), part[0])
            nucleus_index = part.index(nucleus_letter)
            nucleus = chars[nucleus_index]
            alt_nucleus = alt[nucleus_index]
            probability = mean(char['p'] for char in chars)
            syllable = dict(word=word_index, line=word['line'], column=word['column'],
                            source=source, part=position, spelling=part, onset=chars[0]['start'],
                            end=chars[-1]['end'], nucleus=nucleus['start'], p=probability,
                            nucleus_p=nucleus['p'], alt_onset=alt[0]['start'],
                            alt_nucleus=alt_nucleus['start'], alt_p=mean(char['p'] for char in alt),
                            repeat_p=0.0, repeat_onset=None, repeat_nucleus=None)
            result.append(syllable)
            by_position[(word['line'], word['column'], source.lower(), position)].append(syllable)
            part_start += len(part)

    # Each line is still compared with its own CTC and waveform. A counterpart
    # only supplies a tighter prior if its local position agrees within 180 ms.
    for syllable in result:
        line = syllable['line']
        for repetitions in REPEATS:
            starts = [start for start in repetitions if 0 <= line - start <= 4]
            if not starts:
                continue
            repeat_start, = starts
            candidates = []
            for other_start in repetitions:
                if other_start == repeat_start:
                    continue
                other_line = other_start + line - repeat_start
                key = (other_line, syllable['column'], syllable['source'].lower(), syllable['part'])
                for other in by_position[key]:
                    shift = REPEAT_OFFSETS[repeat_start] - REPEAT_OFFSETS[other_start]
                    if (abs(other['onset'] + shift - syllable['onset']) <= .18
                            and other['p'] >= .50):
                        candidates.append((other['p'], other['onset'] + shift, other['nucleus'] + shift))
            if candidates:
                syllable['repeat_p'], syllable['repeat_onset'], syllable['repeat_nucleus'] = max(candidates)
    return result


def note_lyrics(assignments, syllables):
    lyrics = {}
    for note, ids in assignments.items():
        if not ids:
            continue
        items = [syllables[i] for i in ids]
        displayed = []
        for item in items:
            if item['part'] == 0:
                displayed.append(item['source'])
            elif not any(prior['word'] == item['word'] for prior in items if prior['part'] == 0):
                if not displayed or displayed[-1] != '+':
                    displayed.append('+')
        lyrics[note] = ' '.join(displayed)
    return lyrics
