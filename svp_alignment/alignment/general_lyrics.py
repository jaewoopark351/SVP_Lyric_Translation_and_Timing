"""Lossless source-token locations and explicitly approximate syllable evidence."""

import math
import re
import unicodedata

# Compatibility exports: callers keep their established import path while text
# decoding/tokenization and pronunciation estimation have separate owners.
from .source_lyrics import parse_words, read_words


VOWELS = re.compile(r'[aeiouy]+')


def _latin_letters(source):
    return ''.join(char for char in unicodedata.normalize('NFKD', source).casefold()
                   if 'a' <= char <= 'z')


def _parts(source, original_count=None):
    spelling = _latin_letters(source)
    non_latin = any(char.isalpha() and not ('a' <= char.casefold() <= 'z')
                    for char in source if not unicodedata.combining(char))
    if not spelling or non_latin:
        return [(0, max(1, len(spelling)), source)], 'UNSUPPORTED_SYLLABIFICATION'
    groups = list(VOWELS.finditer(spelling))
    if len(groups) > 1 and groups[-1].group() == 'e' and groups[-1].end() == len(spelling):
        # Orthographic fallback, never a pronunciation dictionary. The common
        # consonant+le ending retains its last vowel candidate.
        consonant_le = (len(spelling) >= 3 and spelling[-2] == 'l'
                        and spelling[-3] not in 'aeiouy')
        if not consonant_le:
            groups.pop()
    elif (len(groups) > 1 and groups[-1].group() == 'e'
          and groups[-1].end() == len(spelling) - 1 and spelling[-1] in 'sd'):
        e_index = groups[-1].start()
        preceding = spelling[e_index - 1] if e_index else ''
        consonant_le = (e_index >= 2 and preceding == 'l' and spelling[e_index - 2] not in 'aeiouy')
        syllabic_suffix = (preceding in 'sxzcg' or spelling[max(0, e_index - 2):e_index] in ('sh', 'ch')) if spelling[-1] == 's' else preceding in 'td'
        if not consonant_le and not syllabic_suffix:
            groups.pop()
    count = original_count if original_count and original_count > 1 else max(1, len(groups))
    count = min(count, len(spelling))
    if count == len(groups) and groups:
        cuts = [0] + [left.end() + (right.start() - left.end() + 1) // 2
                      for left, right in zip(groups, groups[1:])] + [len(spelling)]
    else:
        cuts = [round(index * len(spelling) / count) for index in range(count + 1)]
    parts = [(start, stop, spelling[start:stop]) for start, stop in zip(cuts, cuts[1:])]
    basis = ('ORIGINAL_SVP_PLUS_COUNT' if original_count and original_count > 1 else
             'ORTHOGRAPHIC_ESTIMATE' if groups else 'NO_VOWEL_ORTHOGRAPHY')
    return parts, basis


def _source_cuts(source, parts):
    """Map spelling candidates back to exact Python source-string offsets."""
    positions = []
    for offset, char in enumerate(source):
        positions.extend(offset for letter in unicodedata.normalize('NFKD', char).casefold()
                         if 'a' <= letter <= 'z')
    cuts = [0]
    for first, _, _ in parts[1:]:
        cuts.append(positions[first] if first < len(positions) else len(source))
    return cuts + [len(source)]


def _original_count(source, span, notes, offset):
    start, end = span.get('start'), span.get('end')
    if start is None or end is None:
        return None
    for index, note in enumerate(notes):
        if str(note.get('lyrics', '')).strip().casefold() != source.casefold():
            continue
        if note['end_s'] < start + offset - .15 or note['start_s'] > end + offset + .15:
            continue
        count = 1
        for following in notes[index + 1:]:
            if following['start_s'] > end + offset + .15:
                break
            text = str(following.get('lyrics', '')).strip()
            if text == '+':
                count += 1
            elif text != '-':
                break
        return count if count > 1 else None
    return None


def syllable_evidence(words, aligned_words, notes=(), audio_offset=0.0):
    """Keep token identity exact; heuristic internal boundaries remain UNKNOWN."""
    if len(words) != len(aligned_words):
        raise ValueError('CTC 단어 수와 TXT 단어 수가 다릅니다.')
    result = []
    for index, (word, span) in enumerate(zip(words, aligned_words)):
        if span.get('word_index', index) != index or span.get('source', word['source']) != word['source']:
            raise ValueError('CTC 단어 순서 또는 원문이 TXT와 다릅니다.')
        start, end = span.get('start'), span.get('end')
        valid = (span.get('status') != 'UNKNOWN' and
                 isinstance(start, (int, float)) and isinstance(end, (int, float)) and
                 math.isfinite(start) and math.isfinite(end) and 0 <= start < end)
        original_count = _original_count(word['source'], span, notes, audio_offset) if valid else None
        parts, basis = _parts(word['source'], original_count)
        source_cuts = _source_cuts(word['source'], parts)
        chars = span.get('chars', [])
        # Apostrophes and other normalizer labels may be present in CTC output.
        # Only use exact Latin character correspondence for internal boundaries.
        letters = [char for char in chars
                   if str(char.get('char', char.get('label', ''))).lower() in 'abcdefghijklmnopqrstuvwxyz'
                   and len(str(char.get('char', char.get('label', '')))) == 1]
        corresponding = ''.join(str(char.get('char', char.get('label', ''))).lower()
                                for char in letters) == _latin_letters(word['source'])
        probability = span.get('p')
        word_only = span.get('alignment_unit') == 'word'
        probability = (float(probability) if isinstance(probability, (int, float))
                       and math.isfinite(probability) else None)
        for part, (first, last, spelling) in enumerate(parts):
            selected = letters[first:last] if corresponding else []
            # A word-only model supplies one observed window, not individual
            # syllable boundaries. Share that window as a matching constraint;
            # never interpolate unobserved character/phoneme timestamps.
            character_window = bool(selected) and not word_only
            onset = (selected[0]['start'] if character_window else start) if valid else None
            release = (selected[-1]['end'] if character_window else end) if valid else None
            reason = ''
            if not valid:
                reason = span.get('reason') or 'CTC에서 유효한 발음 구간을 얻지 못했습니다.'
            elif basis in ('UNSUPPORTED_SYLLABIFICATION', 'NO_VOWEL_ORTHOGRAPHY'):
                reason = '이 토큰의 실제 음절 수·발음을 자동으로 확인할 수 없습니다.'
            elif len(parts) > 1:
                reason = '여러 음절의 내부 경계는 철자/기존 SVP 추정이며 실제 가창 확인이 필요합니다.'
            if valid and word_only:
                reason = (reason + ' 이 모델은 단어 범위만 제공하며 개별 음절·문자 시각과 '
                          '신뢰도 점수를 제공하지 않습니다. 단어 범위 안의 가사 대응은 UNKNOWN입니다.').strip()
            elif valid and not character_window and len(parts) > 1:
                reason = (reason + ' 문자 대응이 없어 단어 관측 범위만 사용합니다. '
                          '개별 음절 시각을 보간하지 않습니다.').strip()
            result.append(dict(word=index, line=word['line'], column=word['column'], source=word['source'],
                               part=part, spelling=spelling, onset=onset + audio_offset if valid else None,
                               end=release + audio_offset if valid else None, p=probability,
                               alignment_unit='character' if character_window else 'word',
                               boundary_basis=('MODEL_CHARACTER_OBSERVATION' if character_window
                                               else 'MODEL_WORD_WINDOW'),
                               source_start=source_cuts[part], source_end=source_cuts[part + 1],
                               source_text=word['source'][source_cuts[part]:source_cuts[part + 1]],
                               basis=basis, reason=reason, word_start=start + audio_offset if valid else None,
                               word_end=end + audio_offset if valid else None))
    return result
