"""Order-preserving syllable matching and uncertainty decisions."""

from collections import defaultdict
from math import inf
from statistics import mean

from ..svp import note_times
from ..profiles.counting_stars import (LINE_STARTS, LINE_STOPS, LANDMARKS, UNPLACED,
                                      UNPLACED_NOTES, REVIEW_NOTES)


def review_status(items, notes, assignments, continuations):
    unknown = {}
    for index, note in enumerate(notes):
        ordinal = index + 1
        linked = [items[item] for item in assignments.get(index, ())]
        if ordinal in UNPLACED_NOTES:
            unknown[index] = UNPLACED_NOTES[ordinal]
        elif ordinal in REVIEW_NOTES:
            unknown[index] = REVIEW_NOTES[ordinal]
        elif len({item['word'] for item in linked}) > 1:
            unknown[index] = '한 음표에 여러 TXT 단어가 표시됨. 개별 음절 경계와 합성 발음 미확인'
        elif len(linked) > 1:
            unknown[index] = '한 음표 내 여러 음절. 개별 발음 경계 미확인'
        elif linked and mean(item['p'] for item in linked) < .25:
            first = linked[0]
            supported = (first['repeat_p'] >= .50 or
                         (first['alt_p'] >= .40 and abs(first['alt_onset'] - first['onset']) <= .14))
            if not supported:
                unknown[index] = '독립 모델·반복 파형의 발음 시작 근거 부족. 문맥상 가사를 배치'
        elif index not in assignments and index not in continuations:
            unknown[index] = 'TXT 음절 대응 미확정, 기존 값 유지'
        if index in continuations and continuations[index] in unknown:
            parent = continuations[index]
            unknown[index] = f'{parent + 1}번 음표에서 이어지는 음절의 경계 미확정'
    return unknown


def point_cost(item, note, ordinal, landmark):
    if landmark is not None:
        return 0 if ordinal == landmark else inf
    start, end = note_times(note)
    if end - start < .025:
        return inf
    onset = item['onset']
    vowel = item['nucleus']
    agreed = abs(item['alt_onset'] - onset) <= .12 and item['alt_p'] >= .35
    if agreed:
        onset = (onset + item['alt_onset']) / 2
    if item['repeat_onset'] is not None:
        onset = (onset + item['repeat_onset']) / 2
    first = item['part'] == 0
    weight = .55 + .45 * max(item['p'], item['repeat_p'])
    distance = abs(start - onset) * (.8 if first else .7)
    vowel_distance = max(start - vowel - .04, vowel - end, 0)
    coda_distance = max(start - item['end'] - .04, 0)
    return weight * (4 * distance + 4 * vowel_distance + 2 * coda_distance) + (
        .13 if note['lyrics'] == '-' else 0)


def line_assignment(items, ids, notes, start, stop):
    occurrences = defaultdict(list)
    states = {start - 1: (0, ())}
    for item_id in ids:
        item = items[item_id]
        key = (item['line'], item['source'], item['part'])
        seen = occurrences[key]
        landmark = LANDMARKS.get((*key, len(seen)))
        seen.append(item_id)
        following = {}
        for candidate in range(start, stop):
            cost = point_cost(item, notes[candidate - 1], candidate, landmark)
            if cost == inf:
                continue
            for previous, (total, path) in states.items():
                if previous > candidate:
                    continue
                if previous == candidate:
                    prior = items[ids[len(path) - 1]]
                    # A shared pitch can carry consecutive syllables. Two
                    # separate words require stronger evidence and stay flagged.
                    same_word = item['word'] == prior['word']
                    extra = .38 if same_word else .68
                else:
                    skipped = notes[max(previous, start - 1):candidate - 1]
                    extra = sum(.023 if note['lyrics'] == '-' else .085 for note in skipped)
                estimate = total + cost + extra
                if candidate not in following or estimate < following[candidate][0]:
                    following[candidate] = estimate, (*path, candidate)
        states = following
    assert states, (items[ids[0]]['line'], start, stop)
    return min(states.values())[1]


def match_notes(items, notes):
    by_line = defaultdict(list)
    for item_id, item in enumerate(items):
        if (item['line'], item['source']) not in UNPLACED:
            by_line[item['line']].append(item_id)
    assignments = defaultdict(list)
    continuations = {}
    for line, (start, limit) in enumerate(zip(LINE_STARTS, LINE_STARTS[1:]), 1):
        stop = LINE_STOPS.get(line, limit)
        ids = by_line[line]
        chosen = line_assignment(items, ids, notes, start, stop)
        for note, item_id in zip(chosen, ids):
            assignments[note - 1].append(item_id)
        for current, next_note in zip(chosen, (*chosen[1:], stop)):
            for continued in range(current + 1, next_note):
                if continued not in UNPLACED_NOTES:
                    continuations[continued - 1] = current - 1
    assert len({item for ids in assignments.values() for item in ids}) == sum(map(len, by_line.values()))
    return assignments, continuations
