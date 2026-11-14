"""Extract bounded original-vocal previews without changing analysis inputs."""

import math
import uuid
import wave
from pathlib import Path


def _frame_range(start, end, rate):
    first, last = round(start * rate), round(end * rate)
    if last <= first:
        raise ValueError('미리듣기 구간이 한 오디오 프레임보다 짧습니다.')
    return first, last


def _copy_pcm(source, destination, start, end):
    # Keep existing PCM samples byte-for-byte, including 24-bit PCM.
    with wave.open(str(source), 'rb') as audio:
        first, last = _frame_range(start, end, audio.getframerate())
        audio.setpos(first)
        data = audio.readframes(last - first)
        with destination.open('xb') as stream:
            with wave.open(stream, 'wb') as clip:
                clip.setparams(audio.getparams())
                clip.writeframes(data)


def _copy_extended_wav(source, destination, start, end):
    # Python 3.10's wave reader rejects IEEE float and WAVE_FORMAT_EXTENSIBLE.
    # SoundFile is already used by the general-song analysis boundary. Reading
    # only this bounded range leaves the original file and analysis untouched.
    import soundfile as sf

    with sf.SoundFile(str(source), mode='r') as audio:
        first, last = _frame_range(start, end, audio.samplerate)
        audio.seek(first)
        samples = audio.read(last - first, dtype='float64', always_2d=True)
        with destination.open('xb') as stream:
            with sf.SoundFile(stream, mode='w', format='WAV', subtype=audio.subtype,
                              samplerate=audio.samplerate, channels=audio.channels) as clip:
                clip.write(samples)


def create_clip(source, folder, start, end, duration):
    if not all(isinstance(value, (int, float)) and math.isfinite(value)
               for value in (start, end)):
        raise ValueError('미리듣기 시작과 끝을 초 단위 숫자로 지정하세요.')
    if start < 0 or end <= start or end - start > 30:
        raise ValueError('미리듣기는 양수 길이의 최대 30초 구간이어야 합니다.')
    if end > duration:
        raise ValueError('미리듣기 구간이 원본 WAV 길이를 벗어납니다.')
    folder = Path(folder)
    folder.mkdir(exist_ok=True)
    destination = folder / (uuid.uuid4().hex + '.wav')
    try:
        try:
            _copy_pcm(source, destination, start, end)
        except wave.Error:
            # A destination created before an error belongs to the PCM write
            # attempt. Do not turn a write failure into a second write attempt.
            if destination.exists():
                raise
            _copy_extended_wav(source, destination, start, end)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return str(destination)
