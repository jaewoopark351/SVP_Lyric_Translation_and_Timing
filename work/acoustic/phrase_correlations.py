from pathlib import Path

import numpy as np
from scipy.signal import correlate, resample_poly
import soundfile as sf


SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'


def main():
    raw, sr = sf.read(WAV, dtype='float32', always_2d=True)
    raw = resample_poly(raw.mean(axis=1), 8000, sr)
    sr = 8000
    slide = 0.16
    for start, repeat in ((54.72, 62.58), (62.32, 133.14), (62.58, 133.4), (54.72, 133.4), (66.78, 137.60), (74.08, 199.805), (84.98, 155.80), (84.98, 213.834), (46.65, 125.33), (48.75, 127.43), (184.10, 238.20)):
        print(f'{start:.3f} -> {repeat:.3f}')
        for delta in np.arange(0, 3.2, 0.2):
            width = 0.2
            original = raw[round((start + delta) * sr):round((start + delta + width) * sr)]
            segment = raw[round((repeat + delta - slide) * sr):round((repeat + delta + width + slide) * sr)]
            norms = np.sqrt(np.maximum(np.convolve(segment**2, np.ones(len(original)), 'valid'), 1e-12))
            values = correlate(segment, original, mode='valid') / norms / (np.linalg.norm(original) + 1e-9)
            best = int(np.argmax(values))
            print(f'{start + delta:7.3f} {repeat + delta + best / sr - slide:7.3f} shift {repeat - start + best / sr - slide:8.4f} correlation {values[best]:.4f}')


if __name__ == '__main__':
    main()
