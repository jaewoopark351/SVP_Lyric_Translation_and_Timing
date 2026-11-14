"""Check whether repeated phrases reuse time-aligned source performances."""

from pathlib import Path
from statistics import median

import numpy as np
from scipy import signal

from analyze_pitch import load_wave


def repeated_waveform(samples, sr, origin, repeat, duration):
    chunks = np.arange(0, duration, .5)
    stats = []
    for offset in chunks:
        a = int((origin + offset) * sr)
        b = int((repeat + offset) * sr)
        x = samples[a:a + sr // 2]
        tolerance = int(sr * .24)
        y = samples[b - tolerance:b + sr // 2 + tolerance]
        corr = signal.correlate(y, x, mode="valid", method="fft")
        norm = np.sqrt(signal.fftconvolve(y ** 2, np.ones(len(x)), mode="valid") * np.sum(x ** 2))
        corr /= np.maximum(norm, 1.e-5)
        index = np.argmax(corr)
        stats.append((offset, (index - tolerance) / sr, corr[index]))
    return stats


def main():
    source = next(Path("E:/").glob("*/AI_*/OneRepublic*/1_OneRepublic*Vocals*.wav"))
    samples, sr = load_wave(source)
    samples = signal.resample_poly(samples, 80, 441)
    sr = round(sr * 80 / 441)
    # The rough offsets merely locate the search windows. Each reported lag is
    # optimized by normalized sample correlation against the actual WAV.
    groups = [
        ("intro", 13, [.60, 78.27, 94.00, 149.04, 164.77, 207.05, 222.78]),
        ("chorus_a", 15.5, [78.27, 149.04, 207.05]),
        ("chorus_b", 16.5, [94.00, 164.77, 222.78]),
        ("bridge", 3.8, [184.15, 188.08, 192.015, 195.95, 238.21, 242.14, 246.08, 250.02]),
    ]
    folder = Path(__file__).resolve().parent
    with (folder / "repeat_correlations.csv").open("w", encoding="utf-8") as output:
        output.write("phrase,reference_start_s,repeat_start_s,window_offset_s,peak_lag_s,correlation\n")
        for name, duration, starts in groups:
            for i, origin in enumerate(starts[:-1]):
                for repeat in starts[i + 1:]:
                    if name == "intro" and i != 0:
                        continue
                    stats = repeated_waveform(samples, sr, origin, repeat, duration)
                    for offset, lag, correlation in stats:
                        output.write(f"{name},{origin},{repeat},{offset:.2f},{lag:.5f},{correlation:.5f}\n")
                    high = [corr for _, _, corr in stats if corr >= .6]
                    print(name, origin, repeat, f"median {median(corr for _, _, corr in stats):.3f}",
                          f"n(corr >=.6) {len(high)}/{len(stats)}", f"peak {max(corr for _, _, corr in stats):.3f}")


if __name__ == "__main__":
    main()
