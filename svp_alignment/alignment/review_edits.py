"""Apply explicit user correspondence decisions without editing any note field."""

from copy import deepcopy
import math

from .lyric_symbols import render_word_group
from .general_matching import PLACEMENT_POLICY


_INDEX_MAPS = ('assignments', 'continuations', 'unknown', 'unplaced', 'lyric_fields',
               'note_actions', 'word_spans')


def restore_alignment(value):
    """Restore the integer-keyed, versioned correspondence saved in JSON."""
    result = deepcopy(value)
    if result.get('placement_policy') != PLACEMENT_POLICY:
        raise ValueError('이전 가사 배치 정책입니다. 입력을 새로 검사하세요.')
    for name in _INDEX_MAPS:
        source = result.get(name)
        if not isinstance(source, dict):
            raise ValueError('교정 근거의 대응표가 올바르지 않습니다.')
        converted = {}
        for key, item in source.items():
            index = _integer(key, name)
            if index in converted:
                raise ValueError('교정 근거의 대응 인덱스가 중복됐습니다.')
            converted[index] = item
        result[name] = converted
    return result


def _integer(value, label):
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number) or int(number) != number:
            raise ValueError
        return int(number)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f'{label}는 정수여야 합니다.') from error


def _unassigned(note, reason):
    return dict(action='UNASSIGNED_ORIGINAL', word_index=None, syllable_ids=[],
                owner_note=None, review_status='NEEDS_REVIEW', reason=reason,
                text=note.get('lyrics', ''), representation='ORIGINAL',
                source_start=None, source_end=None, source_text='')


def _clear_word(alignment, notes, word_index, reason):
    for index in alignment['word_spans'].pop(word_index, []):
        for name in ('assignments', 'continuations', 'lyric_fields'):
            alignment[name].pop(index, None)
        alignment['note_actions'][index] = _unassigned(notes[index], reason)
        alignment['unknown'][index] = reason
    alignment['unplaced'][word_index] = reason


def apply_review_edit(alignment, notes, *, note_number, action, word_index=None,
                      syllable_index=None, confirmed=False, end_note_number=None):
    """Return a new alignment; caller validates the full result before committing."""
    result = restore_alignment(alignment)
    previous_actions = deepcopy(result['note_actions'])
    previous_unknown = deepcopy(result['unknown'])
    index = _integer(note_number, '음표 번호') - 1
    if not 0 <= index < len(notes):
        raise ValueError('교정할 음표 번호가 범위를 벗어났습니다.')
    if action not in ('WORD_START', 'NEXT_SYLLABLE', 'SUSTAIN', 'CONFIRM'):
        raise ValueError('지원하는 가사 교정 방법을 선택하세요.')
    if not isinstance(confirmed, bool):
        raise ValueError('사용자 확인 여부가 올바르지 않습니다.')
    if action == 'CONFIRM':
        current = result['note_actions'][index]
        if not confirmed:
            raise ValueError('선택한 가사 대응을 확인했다는 항목을 체크하세요.')
        if current['action'] == 'UNASSIGNED_ORIGINAL':
            raise ValueError('미대응 음표는 먼저 원문 단어 또는 앞 음절에 연결하세요.')
        current['review_status'] = 'USER_CONFIRMED'
        current['reason'] = '사용자가 현재 가사 대응을 확인했습니다.'
        result['unknown'].pop(index, None)
        return result
    if word_index is None:
        current = result['note_actions'][index]
        word_index = current.get('word_index')
        if word_index is None and index:
            word_index = result['note_actions'][index - 1].get('word_index')
    word_index = _integer(word_index, 'TXT 단어 순번')
    if not 0 <= word_index < len(result['words']):
        raise ValueError('TXT 단어 순번이 범위를 벗어났습니다.')
    ids = [i for i, item in enumerate(result['syllables']) if item['word'] == word_index]
    if not ids:
        raise ValueError('선택한 단어에 대응 근거가 없습니다.')
    reason = '사용자가 고정 음표의 가사 대응을 수정했습니다. 실제 가창 검증과 구분합니다.'
    review = 'USER_CONFIRMED' if confirmed else 'NEEDS_REVIEW'
    if action == 'WORD_START':
        end = index if end_note_number is None else _integer(end_note_number, '끝 음표 번호') - 1
        if not index <= end < len(notes):
            raise ValueError('끝 음표 번호는 시작 이상이며 기존 음표 범위 안이어야 합니다.')
        indices = list(range(index, end + 1))
        others = {result['note_actions'][i].get('word_index') for i in indices} - {None, word_index}
        for other in others:
            if not set(result['word_spans'][other]).issubset(indices):
                raise ValueError('다른 단어의 일부와 겹칩니다. 해당 단어 전체 범위를 선택하세요.')
        for other in others:
            _clear_word(result, notes, other, '사용자 교정으로 다른 단어에 범위를 배정했습니다.')
        _clear_word(result, notes, word_index, '사용자가 단어의 음표 범위를 다시 지정했습니다.')
        attacks = {index: ids}
    else:
        indices = result['word_spans'].get(word_index, [])
        if not indices:
            raise ValueError('먼저 선택 단어를 음표 범위에 배치하세요.')
        current_word = result['note_actions'][index].get('word_index')
        if current_word not in (None, word_index):
            raise ValueError('다른 단어를 지속음으로 덮을 수 없습니다. 단어 범위를 다시 지정하세요.')
        indices = sorted(set(indices) | {index})
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError('해당 단어에 인접한 음표만 연결할 수 있습니다.')
        head = indices[0]
        if index == head:
            raise ValueError('단어의 첫 음표는 다음 음절이나 지속음으로 바꿀 수 없습니다.')
        starts = {note: ids.index(items[0]) for note, items in result['assignments'].items()
                  if result['note_actions'][note].get('word_index') == word_index}
        starts.pop(index, None)
        if action == 'NEXT_SYLLABLE':
            part = _integer(syllable_index, '음절 번호') if syllable_index is not None else 1
            before = max(value for note, value in starts.items() if note < index)
            after = min((value for note, value in starts.items() if note > index), default=len(ids))
            if not before < part < after:
                raise ValueError('음절 번호가 앞·뒤 음절 순서와 맞지 않습니다.')
            starts[index] = part
        ordered = sorted(starts)
        attacks = {note: ids[starts[note]:starts[ordered[pos + 1]] if pos + 1 < len(ordered) else len(ids)]
                   for pos, note in enumerate(ordered)}
        _clear_word(result, notes, word_index, '사용자가 단어 안의 음절 연결을 다시 지정했습니다.')
    rendered = render_word_group(result['words'], result['syllables'], word_index,
                                 indices, attacks, review_status=review, reason=reason)
    if action != 'WORD_START':
        identity = ('action', 'word_index', 'syllable_ids', 'owner_note', 'text',
                    'source_start', 'source_end', 'representation')
        for note in indices:
            if note == index:
                continue
            current, old = rendered['note_actions'][note], previous_actions.get(note, {})
            unchanged = all(current.get(key) == old.get(key) for key in identity)
            if unchanged:
                current['review_status'] = old['review_status']
                current['reason'] = old.get('reason', '')
                if note in previous_unknown:
                    rendered['unknown'][note] = previous_unknown[note]
                else:
                    rendered['unknown'].pop(note, None)
            else:
                current['review_status'] = 'NEEDS_REVIEW'
                current['reason'] = '음절 연결 교정으로 함께 바뀐 가사를 확인해야 합니다.'
                rendered['unknown'][note] = current['reason']
    for name in ('assignments', 'continuations', 'lyric_fields', 'note_actions', 'unknown'):
        for note in indices:
            result[name].pop(note, None)
        result[name].update(rendered[name])
    result['word_spans'][word_index] = indices
    result['unplaced'].pop(word_index, None)
    return result
