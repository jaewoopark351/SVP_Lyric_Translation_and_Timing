"""Map uniquely recognized, timed units to authoritative source lyric tokens."""

from copy import deepcopy
import math

from .transcript import clean_qwen_token


RECOGNITION_POLICY = 'global_exact_unique_min_edit_v1'


def _field(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _observations(items, duration):
    observations = []
    for index, item in enumerate(items):
        text = _field(item, 'text')
        if not isinstance(text, str):
            raise ValueError('음성 인식 관측에 문자열이 필요합니다.')
        normalized = clean_qwen_token(text)
        if not normalized:
            continue
        start, end = _field(item, 'start_time'), _field(item, 'end_time')
        issue = ''
        try:
            if isinstance(start, bool) or isinstance(end, bool):
                raise ValueError
            start, end = float(start), float(end)
            if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= duration:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            start = end = None
            issue = '음성 인식 단위의 시각이 없거나 WAV 범위에서 유효하지 않습니다.'
        observations.append(dict(index=index, text=normalized, start=start, end=end, issue=issue))
    # A conflict invalidates both observations, rather than silently selecting
    # one or trimming a model span. Repeat after exclusions to catch wider inversions.
    while True:
        valid = [item for item in observations if not item['issue']]
        conflicts = [(a, b) for a, b in zip(valid, valid[1:]) if a['end'] > b['start']]
        if not conflicts:
            return observations
        for a, b in conflicts:
            a['issue'] = b['issue'] = '음성 인식 단위의 시간이 겹치거나 가사 순서와 반대입니다.'


def _exact_ranges(source, observed):
    matches = {}
    for i, text in enumerate(source):
        if not text:
            continue
        for j in range(len(observed)):
            merged = ''
            for k in range(j, len(observed)):
                merged += observed[k]['text']
                if not text.startswith(merged):
                    break
                if merged == text:
                    matches[i, j] = k + 1
                    break
    return matches


def _edit_costs(source, observed, matches):
    n, m = len(source), len(observed)
    if (n + 1) * (m + 1) > 4_000_000:
        raise ValueError('음성 인식과 TXT 대응이 너무 큽니다. 가사와 오디오 범위를 확인하세요.')
    infinity = n + m + 1
    forward = [[infinity] * (m + 1) for _ in range(n + 1)]
    forward[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            cost = forward[i][j]
            if i < n:
                forward[i + 1][j] = min(forward[i + 1][j], cost + bool(source[i]))
            if j < m:
                forward[i][j + 1] = min(forward[i][j + 1], cost + 1)
            if i < n and j < m:
                forward[i + 1][j + 1] = min(forward[i + 1][j + 1], cost + 1)
                end = matches.get((i, j))
                if end is not None:
                    forward[i + 1][end] = min(forward[i + 1][end], cost)
    backward = [[infinity] * (m + 1) for _ in range(n + 1)]
    backward[n][m] = 0
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i < n:
                backward[i][j] = min(backward[i][j], backward[i + 1][j] + bool(source[i]))
            if j < m:
                backward[i][j] = min(backward[i][j], backward[i][j + 1] + 1)
            if i < n and j < m:
                backward[i][j] = min(backward[i][j], backward[i + 1][j + 1] + 1)
                end = matches.get((i, j))
                if end is not None:
                    backward[i][j] = min(backward[i][j], backward[i + 1][end])
    return forward, backward, forward[n][m]


def map_recognition(words, items, duration):
    """Keep every TXT token; only unique exact recognition owns model timings.

    Optimal global edit paths preserve order and repetitions. A source token
    whose exact match differs between equally good paths is UNKNOWN. Multiple
    observed units can form one source token, but an observed unit is never
    divided into invented source-word or character timestamps.
    """
    try:
        if isinstance(duration, bool):
            raise ValueError
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError('음성 인식 WAV 길이가 올바르지 않습니다.') from error
    if (len(words) + 1) * (len(items) + 1) > 4_000_000:
        # Bound work before constructing candidate ranges or edit matrices.
        raise ValueError('음성 인식과 TXT 대응이 너무 큽니다. 가사와 오디오 범위를 확인하세요.')
    originals = deepcopy(words)
    source = [word['normalized'] for word in originals]
    if any(not isinstance(text, str) for text in source):
        raise ValueError('정규화한 TXT 토큰 문자열이 필요합니다.')
    observed = _observations(items, float(duration))
    matches = _exact_ranges(source, observed)
    forward, backward, best = _edit_costs(source, observed, matches)
    result = []
    for i, word in enumerate(originals):
        candidates = [(j, end) for (index, j), end in matches.items() if index == i
                      and forward[i][j] + backward[i + 1][end] == best]
        can_omit = any(forward[i][j] + bool(source[i]) + backward[i + 1][j] == best
                       for j in range(len(observed) + 1))
        can_substitute = any(forward[i][j] + 1 + backward[i + 1][j + 1] == best
                             for j in range(len(observed)))
        units = []
        recognition = 'UNMATCHED'
        reason = word.get('reason') or 'TXT 단어가 실제 음성 인식 결과와 정확히 대응하지 않습니다.'
        if candidates:
            recognition = 'AMBIGUOUS'
            reason = '반복·누락 때문에 같은 비용의 다른 원문 대응이 있습니다. 인식 시각을 확정하지 않습니다.'
            if len(candidates) == 1 and not can_omit and not can_substitute:
                begin, end = candidates[0]
                units = observed[begin:end]
                issues = list(dict.fromkeys(unit['issue'] for unit in units if unit['issue']))
                if issues:
                    recognition, reason = 'INVALID_OBSERVATION', ' '.join(issues)
                else:
                    recognition = 'MATCHED'
                    reason = ''
        supported = recognition == 'MATCHED'
        result.append({**word, 'start': units[0]['start'] if supported else None,
                       'end': units[-1]['end'] if supported else None,
                       'p': None, 'chars': [], 'alignment_unit': 'word',
                       'score_unavailable': True, 'status': 'AUTO' if supported else 'UNKNOWN',
                       'reason': reason, 'recognition_status': recognition,
                       'recognition_policy': RECOGNITION_POLICY,
                       'recognized_unit_indices': [unit['index'] for unit in units] if supported else [],
                       'observed_units': [{key: unit[key] for key in ('text', 'start', 'end')}
                                          for unit in units] if supported else []})
    return result
