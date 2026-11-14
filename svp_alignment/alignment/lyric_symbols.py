"""Render one owned source-token group as coherent Synthesizer V lyrics."""


def render_word_group(words, syllables, word_index, note_indices, attacks,
                      review_status='AUTO_CANDIDATE', reason='', reasons=None):
    """Share exact symbol/source ownership between automatic and user layouts."""
    group = list(note_indices)
    if (not group or group != list(range(group[0], group[-1] + 1))
            or group[0] not in attacks or not set(attacks).issubset(group)):
        raise ValueError('단어가 소유하는 음표는 첫 발음부터 시작하는 연속 구간이어야 합니다.')
    expected = [index for index, item in enumerate(syllables) if item['word'] == word_index]
    actual = [item for index in sorted(attacks) for item in attacks[index]]
    if actual != expected or any(not ids for ids in attacks.values()):
        raise ValueError('단어의 모든 음절 후보를 원문 순서대로 한 번씩 배치해야 합니다.')
    if review_status not in ('AUTO_CANDIDATE', 'NEEDS_REVIEW', 'USER_CONFIRMED'):
        raise ValueError('가사 검토 상태가 유효하지 않습니다.')
    compressed = any(len(ids) > 1 for ids in attacks.values())
    representation = 'TEXT_FRAGMENTS' if compressed else 'WORD_PLUS'
    source = words[word_index]['source']
    assignments, continuations, fields, actions, unknown = {}, {}, {}, {}, {}
    owner = None
    for note in group:
        if note in attacks:
            ids = list(attacks[note])
            first, last = syllables[ids[0]], syllables[ids[-1]]
            assignments[note] = ids
            source_start, source_end = first['source_start'], last['source_end']
            fragment = source[source_start:source_end]
            head = note == group[0]
            action = 'WORD_START' if head else 'TEXT_FRAGMENT' if compressed else 'NEXT_SYLLABLE'
            text = fragment if compressed else source if head else '+'
            owner = note
            action_owner = note if head or compressed else group[0]
            local_reason = (reasons or {}).get(note, '')
        else:
            ids = [assignments[owner][-1]]
            first = syllables[ids[0]]
            source_start, source_end = first['source_start'], first['source_end']
            fragment = source[source_start:source_end]
            continuations[note] = owner
            action, action_owner, text = 'CONTINUE', owner, '-'
            local_reason = (reasons or {}).get(note, '')
            if review_status != 'USER_CONFIRMED':
                local_reason = (local_reason + ' 같은 원문 단어가 소유한 연속 음표의 지속음 후보입니다. '
                                'CTC 문자 종료를 실제 발음 종료로 사용하지 않았으며 '
                                '실제 지속 발음·공백·새 자음 확인이 필요합니다.').strip()
                unknown[owner] = (unknown.get(owner, '') + ' ' + local_reason).strip()
        details = ' '.join(value for value in (reason, local_reason) if value)
        status = review_status
        if details and review_status == 'AUTO_CANDIDATE':
            status = 'NEEDS_REVIEW'
        if status == 'NEEDS_REVIEW':
            unknown[note] = (unknown.get(note, '') + ' ' + details).strip()
        fields[note] = text
        actions[note] = dict(action=action, word_index=word_index, syllable_ids=ids,
                             owner_note=action_owner, representation=representation,
                             source_start=source_start, source_end=source_end,
                             source_text=fragment, text=text, reason=details,
                             review_status=status)
    for note, details in unknown.items():
        actions[note].update(reason=details, review_status='NEEDS_REVIEW')
    return dict(assignments=assignments, continuations=continuations,
                lyric_fields=fields, note_actions=actions, unknown=unknown)
