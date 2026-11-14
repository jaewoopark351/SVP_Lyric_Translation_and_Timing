"""Verify lyric spelling, order, repetitions and syllable coverage."""

def verify_lyrics(notes, assignments, continuations, syllables, words, unplaced):
    seen = []
    for index, note in enumerate(notes):
        if index in assignments:
            expected = [syllables[item_id]['source'] for item_id in assignments[index]
                        if syllables[item_id]['part'] == 0]
            assert note['lyrics'].split() == expected or (not expected and note['lyrics'] == '+')
            seen.extend(note['lyrics'].split() if expected else ())
        elif index in continuations:
            assert note['lyrics'] == '-'
    expected = [word for line, _, word in words if (line, word) not in unplaced]
    assert seen == expected
    all_syllables = [item for index in sorted(assignments) for item in assignments[index]]
    assert all_syllables == [i for i, s in enumerate(syllables) if (s['line'], s['source']) not in unplaced]
    return len(seen)


