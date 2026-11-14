"""Own contiguous word/note groups and jointly choose syllables and sustains."""

import math
from array import array
from statistics import median

from .general_lyrics import syllable_evidence
from .lyric_symbols import render_word_group


PLACEMENT_POLICY = 'word_note_groups_v1'


def _head_cost(item, note):
    start, end = item['word_start'], item['word_end']
    if start is None or end is None:
        return math.inf
    distance = abs(float(note['start_s']) - start)
    gap = max(0., float(note['start_s']) - end, start - float(note['end_s']))
    # This is a search/uncertainty bound, never a correction to observed time.
    if distance > .55 or gap > .35:
        return math.inf
    return distance / .18 + gap / .18


def _word_heads(by_word, syllables, notes):
    """Match source-token starts monotonically before assigning whole groups."""
    width = len(notes) + 1
    trace = bytearray((len(by_word) + 1) * width)
    previous = [0.] * width
    trace[1:width] = bytes([1]) * (width - 1)
    for row, ids in enumerate(by_word, 1):
        current = [previous[0] + 3.]
        trace[row * width] = 2
        item = syllables[ids[0]]
        for column, note in enumerate(notes, 1):
            pair = previous[column - 1] + _head_cost(item, note)
            skip_note, skip_word = current[-1], previous[column] + 3.
            best = min(pair, skip_note, skip_word)
            current.append(best)
            trace[row * width + column] = 3 if best == pair else 1 if best == skip_note else 2
        previous = current
    heads = {}
    row, column = len(by_word), len(notes)
    while row or column:
        direction = trace[row * width + column]
        if direction == 3:
            heads[row - 1] = column - 1
            row -= 1
            column -= 1
        elif direction == 1:
            column -= 1
        else:
            row -= 1
    return dict(sorted(heads.items()))


def _word_groups(by_word, syllables, notes, heads):
    """Reserve contiguous score runs without treating a CTC end as release."""
    groups, rejected = {}, {}
    ordered = list(heads)
    for position, word in enumerate(ordered):
        lead = heads[word]
        stop = heads[ordered[position + 1]] if position + 1 < len(ordered) else len(notes)
        item = syllables[by_word[word][0]]
        start, end = item['word_start'], item['word_end']
        following = syllables[by_word[word + 1][0]] if word + 1 < len(by_word) else None
        next_start = following['word_start'] if following else None
        # A skipped/unknown token is a barrier, not permission to paint its
        # notes with the preceding word's '-'. A terminal token has no following
        # onset evidence with which to propose an unobserved tail.
        has_next = next_start is not None and next_start > start
        boundary = next_start if has_next else end
        duration_scale = median(max(.02, float(note['end_s']) - float(note['start_s']))
                                for note in notes[lead:min(stop, lead + 8)])
        tail_budget = max(.5, min(1.5, 3 * duration_scale))
        group = [lead]
        for index in range(lead + 1, stop):
            note, previous = notes[index], notes[index - 1]
            onset = float(note['start_s'])
            if onset >= boundary:
                rejected[index] = '다음 원문 토큰 시작 또는 미확인 토큰 경계를 넘어 지속음을 제안하지 않습니다.'
                break
            gap = max(0., onset - float(previous['end_s']))
            score_rest = max(.18, min(.45, (float(previous['end_s']) - float(previous['start_s'])) * .6))
            if gap > score_rest and onset > end:
                rejected[index] = '악보의 공백 이후에는 앞 발음이 계속된다는 관측이 없어 원문을 유지합니다.'
                break
            if onset > end and (not has_next or onset - end > tail_budget):
                rejected[index] = '문자 관측 종료는 발음 종료가 아니지만, 추가 발음 근거가 없는 긴 꼬리 구간은 보류합니다.'
                break
            group.append(index)
        groups[word] = group
    return groups, rejected


def _attack_cost(item, note, part, count, position, note_count):
    if part == 0:
        return 0.
    if item.get('boundary_basis') == 'MODEL_CHARACTER_OBSERVATION':
        return min(4., abs(float(note['start_s']) - item['onset']) / .18)
    # Without character boundaries, use score order only as a candidate prior.
    # No estimated timestamp or probability is manufactured or returned.
    rank = part * note_count / count
    return abs(position - rank) * .3


def _syllable_layout(ids, group, syllables, notes):
    """A note can start 1+ syllables or continue the previous syllable."""
    count = len(ids)
    if (count + 1) ** 2 * (len(group) + 1) > 10_000_000:
        raise ValueError('한 단어의 음절·음표 구간 후보가 너무 많습니다. 입력 가사 토큰을 확인하세요.')
    width = count + 1
    trace = array('i', [-1]) * ((len(group) + 1) * width)
    previous = [0.] + [math.inf] * count
    for position, note_index in enumerate(group):
        current = [math.inf] * width
        for consumed, cost in enumerate(previous):
            if not math.isfinite(cost):
                continue
            choices = [(consumed, cost + .12)] if consumed else []
            for amount in range(1, count - consumed + 1):
                selection = tuple(ids[consumed:consumed + amount])
                attack = _attack_cost(syllables[selection[0]], notes[note_index],
                                      consumed, count, position, len(group))
                choices.append((consumed + amount, cost + attack + 1.4 * (amount - 1)))
            for target, candidate in choices:
                if candidate < current[target]:
                    current[target] = candidate
                    trace[(position + 1) * width + target] = consumed
        previous = current
    layout = [()] * len(group)
    consumed = count
    for position in range(len(group), 0, -1):
        before = trace[position * width + consumed]
        layout[position - 1] = tuple(ids[before:consumed])
        consumed = before
    return layout


def _review_reason(item, note, compressed=False):
    reasons = [item['reason']] if item['reason'] else []
    if item['p'] is not None and item['p'] < .55:
        reasons.append('CTC 평균 점수가 0.55 미만입니다. 점수는 발음 정확도의 확률이 아닙니다.')
    if abs(item['word_start'] - float(note['start_s'])) > .5 and item['part'] == 0:
        reasons.append('모델 후보와 기존 음표 시작의 차이가 0.5초를 넘습니다.')
    if compressed:
        reasons.append('추정한 여러 음절을 기존 음표에 압축했습니다. 원문 조각의 실제 가창·발음을 확인해야 합니다.')
    return ' '.join(dict.fromkeys(reasons))


def match_words_to_notes(words, aligned_words, notes, audio_offset=0.0):
    """Return lyrics-only proposals with explicit token and syllable ownership."""
    if not notes:
        raise ValueError('선택한 보컬 그룹에 음표가 없습니다.')
    if any(note['start_s'] > note['end_s'] or not math.isfinite(note['start_s'])
           or not math.isfinite(note['end_s']) for note in notes):
        raise ValueError('SVP 음표 시각이 유효하지 않습니다.')
    if any(left['start_s'] > right['start_s'] for left, right in zip(notes, notes[1:])):
        raise ValueError('보컬 음표는 시간 순서로 전달해야 합니다.')
    syllables = syllable_evidence(words, aligned_words, notes, audio_offset)
    if (len(syllables) + 1) * (len(notes) + 1) > 10_000_000:
        raise ValueError('가사·음표 대응 후보가 너무 많습니다. 처리할 보컬 트랙이나 곡 구간을 나누세요.')
    by_word = [[] for _ in words]
    for index, item in enumerate(syllables):
        by_word[item['word']].append(index)
    heads = _word_heads(by_word, syllables, notes)
    groups, rejected = _word_groups(by_word, syllables, notes, heads)
    assignments, continuations, unknown, unplaced, lyric_fields, actions = {}, {}, {}, {}, {}, {}
    for word, ids in enumerate(by_word):
        if word in groups:
            continue
        item = syllables[ids[0]]
        if item['word_start'] is not None and (item['word_start'] > notes[-1]['end_s'] + .55
                                              or item['word_end'] < notes[0]['start_s'] - .55):
            reason = '모델 단어 관측이 선택한 보컬 음표 범위 밖입니다. 입력 적용 범위·모델 오정렬을 확인해야 합니다.'
        else:
            reason = item['reason'] or '단어 시작과 안전하게 대응하는 기존 음표가 없거나 다른 원문 토큰과 충돌합니다.'
        unplaced[word] = reason
    for word, group in groups.items():
        layout = _syllable_layout(by_word[word], group, syllables, notes)
        compressed = any(len(selection) > 1 for selection in layout)
        attacks = {note: list(selection) for note, selection in zip(group, layout) if selection}
        reasons = {note: _review_reason(syllables[ids[0]], notes[note], compressed)
                   for note, ids in attacks.items()}
        item = syllables[by_word[word][0]]
        chosen_cost = _head_cost(item, notes[group[0]])
        ambiguous = any(index != group[0] and _head_cost(item, note) <= chosen_cost + .25
                        for index, note in enumerate(notes))
        ambiguity_reason = ('단어 시작과 비슷한 비용의 다른 음표 후보가 있습니다. '
                            '원문 순서를 유지해 제안했으며 실제 발음 확인이 필요합니다.') if ambiguous else ''
        rendered = render_word_group(words, syllables, word, group, attacks,
                                     reason=ambiguity_reason, reasons=reasons)
        assignments.update(rendered['assignments'])
        continuations.update(rendered['continuations'])
        lyric_fields.update(rendered['lyric_fields'])
        actions.update(rendered['note_actions'])
        unknown.update(rendered['unknown'])
    for index, note in enumerate(notes):
        if index in actions:
            # A lead may have gained a sustain reason after its action was built.
            if index in unknown:
                actions[index].update(reason=unknown[index], review_status='NEEDS_REVIEW')
            continue
        reason = rejected.get(index, 'TXT와 안전하게 대응하지 못해 원래 가사·시각을 유지합니다.')
        unknown[index] = reason
        actions[index] = dict(action='UNASSIGNED_ORIGINAL', word_index=None, syllable_ids=[],
                              owner_note=None, representation='ORIGINAL', source_start=None,
                              source_end=None, source_text='', text=str(note.get('lyrics', '')),
                              reason=reason, review_status='NEEDS_REVIEW')
    return dict(words=words, syllables=syllables, assignments=dict(sorted(assignments.items())),
                continuations=dict(sorted(continuations.items())), unknown=unknown, unplaced=unplaced,
                lyric_fields=lyric_fields, placement_policy=PLACEMENT_POLICY,
                note_actions=actions, word_spans=groups)
