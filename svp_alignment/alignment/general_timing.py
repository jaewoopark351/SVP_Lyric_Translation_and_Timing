"""Conservative automatic boundary candidates using fresh CTC observations."""


def time_notes(notes, alignment, audio_duration, audio_offset=0.0,
               seconds_to_local_blick=None):
    unknown = dict(alignment['unknown'])
    original = [(float(note['start_s']), float(note['end_s'])) for note in notes]
    times = list(original)
    evidence = [dict(start_reference=None, end_reference=None,
                     start_basis='ORIGINAL_UNCONFIRMED', end_basis='ORIGINAL_UNCONFIRMED') for _ in notes]
    for index, ids in alignment['assignments'].items():
        item = alignment['syllables'][ids[0]]
        attack, release = item['onset'], item['end']
        evidence[index] = dict(start_reference=attack, end_reference=release,
                               start_basis='FRESH_CTC_CHARACTER_CANDIDATE',
                               end_basis='FRESH_CTC_CHARACTER_CANDIDATE')
        if index in unknown:
            continue
        start, end = max(audio_offset, attack), min(audio_offset + audio_duration, release)
        if end - start < .04 or max(abs(start - original[index][0]), abs(end - original[index][1])) > .75:
            unknown[index] = '후보 길이가 40ms 미만이거나 경계 이동이 0.75초를 넘어 원래 시각을 유지합니다.'
            continue
        note = notes[index]
        begin, stop = note.get('clip_begin', -1), note.get('clip_end', -1)
        if begin >= 0 or stop >= 0:
            # Clip bounds are absolute blicks. Use the format boundary's actual
            # tempo/offset conversion and the same integer rounding as apply;
            # estimating a seconds/blick slope from this note is not safe when
            # a tempo mark lies inside it.
            if seconds_to_local_blick is None and (start, end) != original[index]:
                unknown[index] = '그룹 clip 경계의 정확한 템포 변환을 확인할 수 없어 원래 시각을 유지합니다.'
                continue
            onset = (note['onset'] if start == original[index][0]
                     else seconds_to_local_blick(note, start))
            release = (note['onset'] + note['duration'] if end == original[index][1]
                       else seconds_to_local_blick(note, end))
            absolute_start = onset + note.get('blick_offset', 0)
            absolute_end = release + note.get('blick_offset', 0)
            if (release <= onset or (begin >= 0 and absolute_start < begin)
                    or (stop >= 0 and absolute_end > stop)):
                unknown[index] = 'CTC 후보가 보존된 그룹 clip 경계를 벗어나 원래 시각을 유지합니다.'
                continue
        times[index] = (start, end)
    # Never introduce overlaps by silently clipping another note's candidate.
    # Reverting one note can uncover another conflict, so recheck to stability.
    changed = True
    while changed:
        changed = False
        for index, (left, right) in enumerate(zip(times, times[1:])):
            old_overlap = max(0.0, original[index][1] - original[index + 1][0])
            if left[1] - right[0] > old_overlap + 1e-9 or left[0] > right[0]:
                for target in (index, index + 1):
                    if times[target] != original[target]:
                        times[target] = original[target]
                        unknown[target] = 'CTC 후보 적용 시 인접 음표의 새 겹침이 생겨 원래 시각을 유지합니다.'
                        changed = True
    return times, evidence, unknown
