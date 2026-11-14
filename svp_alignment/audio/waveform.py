"""Decode WAV read-only and resample a mono inference signal."""

from math import gcd
from pathlib import Path


MODEL_RATE = 16000
FRAME_SAMPLES = 320
RECEPTIVE_SAMPLES = 400
FRAME_CENTER = 200


def load_waveform(path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    path = Path(path)
    metadata = sf.info(str(path))
    if metadata.format not in ('WAV', 'WAVEX', 'RF64'):
        raise ValueError('음성 정렬 입력은 WAV 파일이어야 합니다.')
    samples, rate = sf.read(str(path), dtype='float32', always_2d=True)
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError('WAV 파일에 유효한 오디오 샘플이 없습니다.')
    mono = samples.mean(axis=1)
    divisor = gcd(MODEL_RATE, rate)
    if rate != MODEL_RATE:
        mono = resample_poly(mono, MODEL_RATE // divisor, rate // divisor)
    mono = np.asarray(mono, dtype=np.float32)
    if len(mono) < RECEPTIVE_SAMPLES:
        raise ValueError('WAV 길이는 최소 0.025초 이상이어야 합니다.')
    return mono, {'duration': len(samples) / rate, 'sample_rate': rate,
                  'channels': samples.shape[1], 'frames': len(samples),
                  'subtype': metadata.subtype, 'model_sample_rate': MODEL_RATE}
