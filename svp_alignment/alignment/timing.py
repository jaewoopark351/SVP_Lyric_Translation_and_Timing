"""Timing decisions from verified acoustic observations."""

from bisect import bisect_left
from statistics import median

from ..svp import BLICK_PER_SECOND, note_times
from ..profiles.counting_stars import ONSET_LANDMARKS, END_LANDMARKS


def local_rms_onset(frames, times, target, pitch):
    center = bisect_left(times, target)
    attacks = []
    for idx in range(max(5, center - 6), min(len(frames) - 8, center + 9)):
        time = times[idx] - .005
        left = median(frame[1] for frame in frames[idx - 5:idx])
        right = median(frame[1] for frame in frames[idx:idx + 3])
        voiced = sum(abs(frame[2] - pitch) <= 1.35 and frame[3] >= .72
                     for frame in frames[idx:idx + 8])
        if right - left >= 6 and right >= -43 and voiced >= 3:
            attacks.append((right - left - 25 * abs(time - target), time))
    return max(attacks)[1] if attacks else None


def onset_candidate(note, index, items, boundaries, frames, times):
    ordinal = index + 1
    if ordinal in ONSET_LANDMARKS:
        return ONSET_LANDMARKS[ordinal]
    start, _ = note_times(note)
    boundary = boundaries[index]
    pitch_time = boundary['pitched_onset_s']
    if pitch_time:
        pitch_time = float(pitch_time)
        if abs(pitch_time - start) <= .130:
            if not items or min(abs(pitch_time - items[0][key]) for key in ('onset', 'nucleus')) <= .220:
                return pitch_time, boundary['onset_basis']
    if items:
        first = items[0]
        source, alt = first['onset'], first['alt_onset']
        if (abs(source - alt) <= .065 and first['p'] >= .45 and first['alt_p'] >= .33
                and abs(source - start) <= .15):
            target = (source + alt) / 2
            attack = local_rms_onset(frames, times, target, note['pitch'])
            if attack is not None and abs(attack - start) <= .125:
                return attack, 'CTC_AGREEMENT_AND_RMS_ATTACK'
    return None, ''


def time_notes(notes, assignments, continuations, syllables, boundaries, frames, audio_duration):
    times = [frame[0] for frame in frames]
    old = [note_times(note) for note in notes]
    onset = [item[0] for item in old]
    finish = [item[1] for item in old]
    evidence = [{} for _ in notes]
    for index in range(len(notes) - 1, -1, -1):
        if index not in assignments and index not in continuations:
            continue
        note = notes[index]
        items = [syllables[item_id] for item_id in assignments.get(index, ())]
        reference, kind = onset_candidate(note, index, items, boundaries, frames, times)
        evidence[index].update(start_reference=reference, start_basis=kind)
        if reference is None or abs(reference - onset[index]) < .012:
            continue
        left = 0 if index == 0 else old[index - 1][0] + .018
        if index and index - 1 not in assignments and index - 1 not in continuations:
            left = max(left, old[index - 1][1])
        right = audio_duration if index + 1 == len(notes) else onset[index + 1] - .018
        # Keep the original 10ms pitch fragments and their adjacent edges valid.
        if right < left or old[index][1] - old[index][0] < .025:
            continue
        end_limit = max(old[index][1], END_LANDMARKS.get(index + 1, (0, ''))[0])
        if left <= reference <= min(right, end_limit - .018):
            onset[index] = reference

    for index in range(len(notes) - 1, -1, -1):
        if index not in assignments and index not in continuations:
            continue
        start, end = old[index]
        end_reference, end_basis = END_LANDMARKS.get(index + 1, (None, ''))
        detected = boundaries[index]['voiced_end_s']
        if end_reference is None and detected and abs(float(detected) - end) <= .140:
            end_reference, end_basis = float(detected), 'VOICED_RELEASE'
        next_start = audio_duration if index + 1 == len(notes) else onset[index + 1]
        next_old = audio_duration if index + 1 == len(notes) else old[index + 1][0]
        # A measured new boundary also determines the prior note's release
        # when the two notes were originally adjacent (including rounding).
        if index + 1 < len(notes) and next_old - end <= .001 and next_start != next_old:
            end_reference, end_basis = next_start, 'CONTIGUOUS_NEXT_BOUNDARY'
        if end_reference is not None:
            evidence[index].update(end_reference=end_reference, end_basis=end_basis)
            if abs(end_reference - end) >= .012 and onset[index] + .018 <= end_reference <= next_start:
                finish[index] = end_reference
        if finish[index] > next_start:
            finish[index] = next_start
        if finish[index] <= onset[index]:
            onset[index] = start
        assert onset[index] < finish[index] <= next_start + 1 / BLICK_PER_SECOND
    return list(zip(onset, finish)), evidence
