from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf


SOURCE = Path('E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구')
WAV = SOURCE / '1_OneRepublic - Counting Stars_(Vocals).wav'


def main():
    windows = [(117.88, 118.46), (125.74, 126.06), (127.72, 128.06),
               (184.09, 188), (188, 191.9), (191.9, 195.83), (195.83, 199.9),
               (238.18, 242.0), (242.0, 245.91), (245.91, 249.88), (249.88, 253.9), (254.0, 262.56)]
    for path in (WAV, next(SOURCE.glob('*_(No Reverb).wav'))):
        samples, sample_rate = sf.read(path, dtype='float32', always_2d=True)
        print(path.name)
        for start, stop in windows:
            x = samples[round(start * sample_rate):round(stop * sample_rate)]
            mid = x.mean(1)
            side = (x[:, 0] - x[:, 1]) / 2
            rms = lambda v: 20 * np.log10(np.sqrt(np.mean(v**2)))
            print(f'{start:7.3f}–{stop:7.3f}', f'mid={rms(mid):.1f} side={rms(side):.1f} corr={np.corrcoef(x.T)[0,1]:.3f}')


if __name__ == '__main__':
    main()
