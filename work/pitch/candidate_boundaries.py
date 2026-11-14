"""Locate reproducible pitch transitions near existing note boundaries."""

from pathlib import Path

import numpy as np


def runs(mask, minimum):
    edges = np.flatnonzero(np.diff(mask, prepend=False, append=False))
    return [(int(start), int(end)) for start, end in edges.reshape(-1, 2) if end - start >= minimum]


def track(data, note):
    cents = np.abs(data["praat_midi_pitch"] - note) * 100
    return (cents <= 85) & (data["praat_strength"] >= .70) & (data["rms_dbfs"] >= -47)


def stable_near(mask, center, latest_center, is_onset):
    lower = max(0, center - 18)
    upper = min(len(mask), center + 26, latest_center)
    if upper - lower < 5:
        return []
    return [lower + (a if is_onset else b) for a, b in runs(mask[lower:upper], 4)
            if lower + a >= center - 14 and lower + a < center + 22]


def match_transition(source_track, project_track, prev_source, prev_project, center, after, index):
    if index == 0:
        return None
    for data_track, previous in [(source_track, prev_source), (project_track, prev_project)]:
        if np.count_nonzero(previous[max(0, center - 21):center + 5]) < 4:
            return None
        if np.count_nonzero(data_track[max(0, center - 22):max(0, center - 13)]) >= 4:
            return None
    source_onsets = stable_near(source_track, center, after, True)
    project_onsets = stable_near(project_track, center, after, True)
    if len(source_onsets) == 1 and len(project_onsets) == 1 and abs(source_onsets[0] - project_onsets[0]) <= 3:
        return source_onsets[0] / 100
    return None


def match_attack(source, project, source_track, project_track, center, after):
    source_onsets = stable_near(source_track, center, after, True)
    project_onsets = stable_near(project_track, center, after, True)
    if len(source_onsets) != 1 or len(project_onsets) != 1 or abs(source_onsets[0] - project_onsets[0]) > 3:
        return None
    # Require a detectable 7 dB energy increase before the pitch onset. The
    # measured time is a pitch onset and can be later than a preceding consonant.
    source_db = source["rms_dbfs"]
    project_db = project["rms_dbfs"]
    for index, energy in ((source_onsets[0], source_db), (project_onsets[0], project_db)):
        left = energy[max(0, index - 15):max(0, index - 3)]
        right = energy[index:index + 4]
        if len(left) < 4 or np.median(right) - np.median(left) < 7:
            return None
    return source_onsets[0] / 100


def match_end(source, project, source_track, project_track, center):
    measured = []
    for mask, data in ((source_track, source), (project_track, project)):
        left, right = center - 16, center + 16
        candidates = runs(mask[left:right], 4)
        if len(candidates) != 1:
            return None
        _, end = candidates[0]
        if end < 2 or end > len(mask[left:right]) - 4:
            return None
        index = left + end
        db = data["rms_dbfs"]
        if np.median(db[index-5:index]) - np.median(db[index+2:index+8]) < 5:
            return None
        measured.append(index)
    if abs(measured[0] - measured[1]) <= 4:
        return measured[0] / 100
    return None


def main():
    folder = Path(__file__).resolve().parent
    source = np.genfromtxt(folder / "source_frames.csv", delimiter=",", names=True)
    project = np.genfromtxt(folder / "project_audio_frames.csv", delimiter=",", names=True)
    notes = np.genfromtxt(folder / "notes_pitch.csv", delimiter=",", names=True)
    rows = []
    for index, note in enumerate(notes):
        pitch = note["midi_pitch"]
        start = note["old_onset_s"]
        end = note["old_end_s"]
        center = int(round(start * 100))
        after = int(round((start + end) * 50)) + 3
        start_evidence = None
        end_evidence = None
        kind = ""
        source_track = track(source, pitch)
        project_track = track(project, pitch)
        if index == 0 or start - notes[index - 1]["old_end_s"] >= .12:
            start_evidence = match_attack(source, project, source_track, project_track, center, after)
            kind = "VOICED_ATTACK"
        elif pitch != notes[index - 1]["midi_pitch"]:
            prev = notes[index - 1]["midi_pitch"]
            start_evidence = match_transition(source_track, project_track, track(source, prev),
                                              track(project, prev), center, after, index)
            kind = "PITCH_TRANSITION"
        if index + 1 == len(notes) or notes[index + 1]["old_onset_s"] - end >= .12:
            end_evidence = match_end(source, project, source_track, project_track, int(round(end * 100)))
        rows.append((index, start, end, start_evidence, kind if start_evidence is not None else "", end_evidence))
    with (folder / "pitch_boundary_candidates.csv").open("w", encoding="utf-8") as output:
        output.write("index_0_based,old_start_s,old_end_s,pitched_onset_s,onset_basis,voiced_end_s\n")
        for row in rows:
            output.write(",".join("" if value is None else str(value) for value in row) + "\n")
    shifts = np.array([onset - start for _, start, _, onset, _, _ in rows if onset is not None])
    end_shifts = np.array([evidence - end for _, _, end, _, _, evidence in rows if evidence is not None])
    print("VOICED_ATTACK", sum(kind == "VOICED_ATTACK" for _, _, _, _, kind, _ in rows))
    print("PITCH_TRANSITION", sum(kind == "PITCH_TRANSITION" for _, _, _, _, kind, _ in rows))
    print("VOICED_END", len(end_shifts))
    print("onset delta p10, p50, p90, max abs", np.percentile(shifts, [10, 50, 90]), np.max(np.abs(shifts)))
    print("end delta p10, p50, p90, max abs", np.percentile(end_shifts, [10, 50, 90]), np.max(np.abs(end_shifts)))
    print("onsets absolute shift >100 ms", np.sum(np.abs(shifts) > .1))


if __name__ == "__main__":
    main()
