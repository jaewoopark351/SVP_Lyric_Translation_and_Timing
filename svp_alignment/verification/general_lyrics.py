"""Verify source accounting and serialized lyric ownership on fixed notes."""


PLACEMENT_POLICY = 'word_note_groups_v1'
_ATTACKS = frozenset({'WORD_START', 'NEXT_SYLLABLE', 'TEXT_FRAGMENT'})
_ACTIONS = _ATTACKS | {'CONTINUE', 'UNASSIGNED_ORIGINAL'}
_REVIEWS = frozenset({'AUTO_CANDIDATE', 'NEEDS_REVIEW', 'USER_CONFIRMED'})


def _policy_actions(words, alignment, notes):
    """Reject broken semantic chains in the actual serialized lyric fields."""
    actions = alignment.get('note_actions', {})
    if set(actions) != set(range(len(notes))):
        raise ValueError('모든 기존 음표에 배치 행동 또는 원문 유지 사유가 있어야 합니다.')
    syllables = alignment['syllables']
    assignments = alignment['assignments']
    continuations = alignment['continuations']
    fields = alignment['lyric_fields']
    if set(fields) != set(assignments) | set(continuations) or set(assignments) & set(continuations):
        raise ValueError('가사 필드와 음절 시작·지속음 기록이 일치하지 않습니다.')
    spans = alignment.get('word_spans', {})
    placed = set(range(len(words))) - set(alignment['unplaced'])
    if set(spans) != placed:
        raise ValueError('단어 구간과 배치·미배치 원문 계수가 일치하지 않습니다.')
    for word_index, indices in spans.items():
        if not indices or indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError('단어가 사용하는 음표 구간은 비어 있지 않은 연속 구간이어야 합니다.')
        if any(index not in actions or actions[index].get('word_index') != word_index for index in indices):
            raise ValueError('단어 구간과 음표 행동의 원문 소유자가 다릅니다.')
    heads, last_attack, ordinary_owner, seen_spans = {}, None, None, {}
    for index, note in enumerate(notes):
        action = actions[index]
        kind = action.get('action')
        if kind not in _ACTIONS or action.get('review_status') not in _REVIEWS:
            raise ValueError('알 수 없는 배치 행동 또는 검토 상태입니다.')
        ids = action.get('syllable_ids')
        if not isinstance(ids, list):
            raise ValueError('음표 행동의 음절 인덱스가 목록이 아닙니다.')
        word_index = action.get('word_index')
        text = str(note.get('lyrics', ''))
        if kind == 'UNASSIGNED_ORIGINAL':
            if (word_index is not None or ids or action.get('owner_note') is not None
                    or index in fields or not action.get('reason')
                    or action.get('text', text) != text):
                raise ValueError('미대응 원문 유지 행동에 배치 소유자 또는 누락된 사유가 있습니다.')
            # An unassigned original may look like a valid token or a symbol;
            # neither is evidence of ownership in the new correspondence.
            ordinary_owner, last_attack = None, None
            continue
        if (not isinstance(word_index, int) or isinstance(word_index, bool)
                or word_index not in placed or not ids
                or any(not isinstance(item, int) or isinstance(item, bool)
                       or not 0 <= item < len(syllables)
                       or syllables[item]['word'] != word_index for item in ids)):
            raise ValueError('음표 행동의 원문 토큰·음절 소유자가 유효하지 않습니다.')
        if index not in spans[word_index]:
            raise ValueError('배치 행동이 해당 단어의 연속 음표 구간 밖에 있습니다.')
        if text != fields[index] or action.get('text', text) != text:
            raise ValueError('최종 SVP의 가사와 배치 행동에 기록된 문자열이 다릅니다.')
        seen_spans.setdefault(word_index, []).append(index)
        owner = action.get('owner_note')
        if kind == 'CONTINUE':
            if (text != '-' or index not in continuations or owner != continuations[index]
                    or owner != last_attack or owner is None
                    or actions[owner].get('word_index') != word_index
                    or ids != [actions[owner]['syllable_ids'][-1]]
                    or ordinary_owner != word_index):
                raise ValueError('지속음 -의 앞 음절·원문 연결이 최종 가사 문맥과 다릅니다.')
            continue
        if assignments.get(index) != ids:
            raise ValueError('배치 행동과 음절 시작 기록이 다릅니다.')
        if kind == 'WORD_START':
            if word_index in heads or owner != index:
                raise ValueError('원문 단어 시작이 중복됐거나 시작 음표 소유자가 다릅니다.')
            heads[word_index] = index
            ordinary_owner = word_index
        elif kind == 'NEXT_SYLLABLE':
            if (text != '+' or heads.get(word_index) != owner
                    or ordinary_owner != word_index):
                raise ValueError('다음 음절 +가 다른 일반 가사 또는 단어에 연결됩니다.')
        elif kind == 'TEXT_FRAGMENT':
            if word_index not in heads or owner != index:
                raise ValueError('분할 가사에 원문 시작 또는 발음 시작 소유자가 없습니다.')
            ordinary_owner = word_index
        if kind != 'NEXT_SYLLABLE' and text in ('+', '-'):
            raise ValueError('원문 가사 시작이 기호로 직렬화됐습니다.')
        first, stop = action.get('source_start'), action.get('source_end')
        if (not isinstance(first, int) or isinstance(first, bool)
                or not isinstance(stop, int) or isinstance(stop, bool)
                or not 0 <= first < stop <= len(words[word_index]['source'])
                or action.get('source_text') != words[word_index]['source'][first:stop]):
            raise ValueError('분할 가사와 원문 문자열 위치가 일치하지 않습니다.')
        last_attack = index
    if seen_spans != spans or set(heads) != placed:
        raise ValueError('원문 단어 구간이 중복되거나 시작 음표가 누락됐습니다.')
    for word_index, indices in spans.items():
        attacks = [actions[index] for index in indices if actions[index]['action'] in _ATTACKS]
        representations = {action.get('representation') for action in attacks}
        if len(representations) != 1:
            raise ValueError('한 단어 안에서 가사 직렬화 방식이 혼합됐습니다.')
        representation = next(iter(representations))
        cursor = 0
        for action in attacks:
            if action['source_start'] != cursor:
                raise ValueError('가사 대응의 원문 범위가 겹치거나 중간에 누락됐습니다.')
            cursor = action['source_end']
        if cursor != len(words[word_index]['source']):
            raise ValueError('가사 대응을 연결해 TXT 원문 전체를 복원할 수 없습니다.')
        if representation == 'TEXT_FRAGMENTS':
            if any(action['text'] != action['source_text'] for action in attacks):
                raise ValueError('분할 가사가 원문 부분문자열과 다릅니다.')
        elif representation == 'WORD_PLUS':
            if attacks[0]['text'] != words[word_index]['source'] or any(
                    action['action'] != 'NEXT_SYLLABLE' for action in attacks[1:]):
                raise ValueError('단어와 + 가사 체인의 원문 표현이 일치하지 않습니다.')
        else:
            raise ValueError('알 수 없는 가사 직렬화 방식입니다.')
    return True


def verify_placement(words, alignment, notes):
    expected_fields = alignment['lyric_fields']
    note_indices = list(expected_fields) + list(alignment['assignments']) + list(alignment['continuations'])
    if any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(notes)
           for index in note_indices):
        raise ValueError('가사 배치의 음표 인덱스가 기존 음표 범위 밖입니다.')
    for index, expected in expected_fields.items():
        if str(notes[index].get('lyrics', '')) != expected:
            raise ValueError(f'음표 {index + 1}의 가사 문자열이 대응 결과와 다릅니다.')
    syllables = alignment['syllables']
    if any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(words)
           or not reason for index, reason in alignment['unplaced'].items()):
        raise ValueError('미배치 원문 인덱스 또는 사유가 유효하지 않습니다.')
    ids = [item for note in sorted(alignment['assignments'])
           for item in alignment['assignments'][note]]
    if any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(syllables)
           for index in ids):
        raise ValueError('가사 배치의 음절 인덱스가 유효하지 않습니다.')
    if ids != sorted(set(ids)):
        raise ValueError('배치한 음절의 순서가 바뀌었거나 중복됐습니다.')
    reconstructed = [syllables[index]['word'] for index in ids if syllables[index]['part'] == 0]
    expected_words = [index for index in range(len(words)) if index not in alignment['unplaced']]
    if reconstructed != expected_words:
        raise ValueError('TXT 원문 단어 순서·반복·배치 기록이 일치하지 않습니다.')
    for word_index in expected_words:
        all_ids = [index for index, syllable in enumerate(syllables) if syllable['word'] == word_index]
        placed_ids = [index for index in ids if syllables[index]['word'] == word_index]
        if placed_ids != all_ids:
            raise ValueError('일부 음절만 배치된 단어가 있습니다.')
    policy = alignment.get('placement_policy')
    if policy:
        if policy != PLACEMENT_POLICY:
            raise ValueError('지원하지 않는 가사 배치 정책입니다.')
        _policy_actions(words, alignment, notes)
    return dict(placed_words=len(reconstructed), unplaced_words=len(alignment['unplaced']),
                source_order='PASS', pronunciation='NOT_VERIFIED',
                placement_policy=policy or '', symbol_chains='PASS' if policy else 'NOT_VERIFIED',
                source_accounting='PASS' if policy else 'NOT_VERIFIED')
