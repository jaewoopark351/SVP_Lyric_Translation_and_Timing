"""Compare note placements with the two time-synchronous vocal waveforms."""

import csv
import json
import wave
from pathlib import Path

import numpy as np
import parselmouth
from scipy import signal


def load_wave(path):
    with wave.open(str(path), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        return samples.reshape(-1, wav.getnchannels()).mean(1) / 32768, wav.getframerate()


def extract_pitch(samples, sr):
    samples = signal.resample_poly(samples, 80, 441)
    sr = round(sr * 80 / 441)
    pitch = parselmouth.Sound(samples, sr).to_pitch_ac(
        time_step=.005, pitch_floor=75, pitch_ceiling=700, silence_threshold=.012,
        voicing_threshold=.45, octave_jump_cost=.32, voiced_unvoiced_cost=.13,
    )
    times = pitch.xs()
    freq = pitch.selected_array["frequency"]
    strength = pitch.selected_array["strength"]
    return times, np.where(freq > 0, 69 + 12 * np.log2(np.maximum(freq, 1) / 440), np.nan), strength


def sample_pitch(times, pitch, sample_times):
    indices = np.rint((sample_times - times[0]) / (times[1] - times[0])).astype(int)
    return pitch[np.clip(indices, 0, len(times) - 1)]


def wave_alignment(source, derived, sr):
    for start in np.arange(0, 260, 5):
        x = source[start * sr:(start + 3) * sr:8]
        y = derived[start * sr:(start + 3) * sr:8]
        if np.linalg.norm(x) == 0 or np.linalg.norm(y) == 0:
            continue
        correlation = signal.correlate(x, y, mode="full", method="fft")
        center = len(x) - 1
        band = correlation[center - 600:center + 601]
        lag = np.argmax(band) - 600
        yield float(start), lag * 8 / sr, float(band[lag + 600] / (np.linalg.norm(x) * np.linalg.norm(y)))


def best_match_offsets(notes, times, pitch):
    expected = np.array([note["pitch"] for note in notes])
    starts = np.array([note["onset"] for note in notes]) / 1411200000
    ends = starts + np.array([note["duration"] for note in notes]) / 1411200000
    center = (starts + ends) / 2
    best_lags = []
    lags = np.arange(-.75, .75, .005)
    for first in range(0, 260, 10):
        notes_here = (center >= first) & (center < first + 10)
        if not np.any(notes_here):
            continue
        observed = sample_pitch(times, pitch, center[notes_here, None] + lags)
        errors = observed - expected[notes_here, None]
        absolute = np.nan_to_num(np.abs(errors), nan=10.)
        octave = np.nan_to_num(np.abs((errors + 6) % 12 - 6), nan=10.)
        loss = np.minimum(absolute, 4.) + np.minimum(octave, 4.)
        mean_loss = loss.mean(axis=0)
        best = np.argmin(mean_loss)
        best_lags.append((first, int(notes_here.sum()), lags[best], mean_loss[best], mean_loss[150]))
    return best_lags


def write_frame_evidence(target, samples, sr, times, pitch, strength):
    # Use causal sample windows, so windows and their waveform measurements can be recovered.
    width = round(sr / 100)
    windows = samples[:len(samples) // width * width].reshape(-1, width)
    rms = np.sqrt(np.mean(windows ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-5))
    sample_times = (np.arange(len(db)) + .5) * width / sr
    detected_pitch = sample_pitch(times, pitch, sample_times)
    detected_strength = sample_pitch(times, strength, sample_times)
    rows = np.column_stack([sample_times, db, detected_pitch, detected_strength])
    np.savetxt(target, rows, delimiter=",", fmt="%.5f", comments="",
               header="wav_time_s,rms_dbfs,praat_midi_pitch,praat_strength")


def main():
    folder = next(Path("E:/").glob("*/AI_*/OneRepublic*"))
    svp = next(folder.glob("*.svp"))
    source = next(folder.glob("1_OneRepublic*Vocals*.wav"))
    derived = next(folder.glob("1_1_1_OneRepublic*No Reverb*.wav"))
    project = json.loads(svp.read_bytes().rstrip(b"\x00"))
    ref_id = project["tracks"][0]["groups"][0]["groupID"]
    notes = next(group for group in project["library"] if group["uuid"] == ref_id)["notes"]
    samples, sr = load_wave(source)
    derived_samples, derived_sr = load_wave(derived)
    assert sr == derived_sr and len(samples) == len(derived_samples)
    print("Cross-correlation across waves (chunks begin, lag s, correlation):")
    correlations = list(wave_alignment(samples, derived_samples, sr))
    print([(start, round(lag, 4), round(corr, 3)) for start, lag, corr in correlations])
    print("Calculating pitch")
    times, pitch, strength = extract_pitch(samples, sr)
    derived_times, derived_pitch, derived_strength = extract_pitch(derived_samples, sr)
    print("Independent Praat f0 match by 10 s block, each row original then no-reverb (t, n, lag, best loss, zero lag loss)")
    source_blocks = best_match_offsets(notes, times, pitch)
    derived_blocks = best_match_offsets(notes, derived_times, derived_pitch)
    for a, b in zip(source_blocks, derived_blocks):
        print(tuple(round(x, 4) for x in a), tuple(round(x, 4) for x in b))
    output = Path(__file__).resolve().parent
    write_frame_evidence(output / "source_frames.csv", samples, sr, times, pitch, strength)
    write_frame_evidence(output / "project_audio_frames.csv", derived_samples, sr, derived_times, derived_pitch, derived_strength)
    expected = np.array([note["pitch"] for note in notes])
    starts = np.array([note["onset"] for note in notes]) / 1411200000
    ends = starts + np.array([note["duration"] for note in notes]) / 1411200000
    center = (starts + ends) / 2
    observed = sample_pitch(times, pitch, center)
    reference = sample_pitch(derived_times, derived_pitch, center)
    finite = np.isfinite(observed)
    matches = finite & (np.abs(observed - expected) < .8)
    octaves = finite & (np.abs((observed - expected + 6) % 12 - 6) < .8)
    print("Notes, voiced-at-centers, absolute-pitch matches <.8 semitone, octaves allowed, derived at centers")
    print(len(notes), finite.sum(), matches.sum(), octaves.sum(), (np.abs(reference - expected) < .8).sum())
    print("Pitch diffs in semitones at voiced note centers")
    print(np.unique(np.rint(observed[finite] - expected[finite]).astype(int), return_counts=True))
    print("First/last strong pitch frames (Praat strength >= .8)")
    is_strong = (strength >= .8) & np.isfinite(pitch)
    print(times[is_strong][0], times[is_strong][-1])
    with (output / "notes_pitch.csv").open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["index_0_based", "old_onset_s", "old_end_s", "midi_pitch", "source_center_pitch", "project_audio_center_pitch"])
        for index in range(len(notes)):
            writer.writerow([index, round(starts[index], 5), round(ends[index], 5), expected[index],
                             round(observed[index], 3), round(reference[index], 3)])


if __name__ == "__main__":
    main()
