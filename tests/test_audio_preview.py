"""Bounded previews support PCM and float WAV while preserving source bytes."""

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
import wave

import numpy as np
import soundfile as sf

from svp_alignment.jobs.preview import create_clip


ROOT = Path(__file__).resolve().parents[1]


class AudioPreviewTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / 'work' / 'gui-validation'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='preview-', dir=base)
        self.workspace = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.assertTrue(self.workspace.is_relative_to((ROOT / 'work/gui-validation').resolve()))
        self.temporary.cleanup()

    def test_pcm24_samples_are_copied_byte_for_byte(self):
        source = self.workspace / '원본 PCM.wav'
        samples = (np.arange(16000, dtype=np.int32) - 8000) << 8
        sf.write(source, samples, 16000, subtype='PCM_24')
        before = sha256(source.read_bytes()).hexdigest()
        clip = Path(create_clip(source, self.workspace / 'clips', .25, .75, 1.0))
        with wave.open(str(source), 'rb') as original, wave.open(str(clip), 'rb') as preview:
            original.setpos(4000)
            self.assertEqual(original.readframes(8000), preview.readframes(8000))
            self.assertEqual((preview.getnframes(), preview.getsampwidth(), preview.getframerate()),
                             (8000, 3, 16000))
        self.assertEqual(before, sha256(source.read_bytes()).hexdigest())

    def test_float32_wav_preserves_samples_channels_rate_and_subtype(self):
        source = self.workspace / '원본 FLOAT.wav'
        samples = np.linspace(-.9, .9, 16000, dtype=np.float32)
        samples = np.column_stack((samples, -samples))
        sf.write(source, samples, 16000, subtype='FLOAT')
        before = source.read_bytes()
        clip = create_clip(source, self.workspace / 'clips', .125, .625, 1.0)
        actual, rate = sf.read(clip, dtype='float32', always_2d=True)
        np.testing.assert_array_equal(samples[2000:10000], actual)
        self.assertEqual((rate, sf.info(clip).subtype, actual.shape), (16000, 'FLOAT', (8000, 2)))
        self.assertEqual(before, source.read_bytes())

    def test_float64_wav_preserves_double_precision(self):
        source = self.workspace / '원본 DOUBLE.wav'
        samples = np.linspace(-.8, .8, 8000, dtype=np.float64)
        sf.write(source, samples, 8000, subtype='DOUBLE')
        before = source.read_bytes()
        clip = create_clip(source, self.workspace / 'clips', .25, .75, 1.0)
        actual, rate = sf.read(clip, dtype='float64')
        np.testing.assert_array_equal(samples[2000:6000], actual)
        self.assertEqual((rate, sf.info(clip).subtype), (8000, 'DOUBLE'))
        self.assertEqual(before, source.read_bytes())

    def test_extensible_pcm_wav_has_bounded_soundfile_fallback(self):
        source = self.workspace / '확장 WAV.wav'
        samples = np.linspace(-.75, .75, 8000, dtype=np.float64)
        sf.write(source, samples, 8000, format='WAVEX', subtype='PCM_24')
        before = source.read_bytes()
        expected, _ = sf.read(source, start=1000, frames=4000, dtype='float64')
        clip = create_clip(source, self.workspace / 'clips', .125, .625, 1.0)
        actual, _ = sf.read(clip, dtype='float64')
        np.testing.assert_array_equal(expected, actual)
        self.assertEqual(sf.info(clip).subtype, 'PCM_24')
        self.assertEqual(before, source.read_bytes())

    def test_invalid_range_creates_no_clip_folder(self):
        source = self.workspace / 'unused.wav'
        clips = self.workspace / 'clips'
        for start, end, duration in ((0, 31, 60), (-1, 1, 2), (1, 1, 2), (0, 3, 2), (0, float('nan'), 2)):
            with self.assertRaises(ValueError):
                create_clip(source, clips, start, end, duration)
        self.assertFalse(clips.exists())

    def test_invalid_wav_failure_leaves_no_partial_clip(self):
        source = self.workspace / '손상.wav'
        source.write_bytes(b'RIFF-invalid')
        before = source.read_bytes()
        clips = self.workspace / 'clips'
        with self.assertRaises(Exception):
            create_clip(source, clips, 0, 1, 2)
        self.assertEqual([], list(clips.iterdir()))
        self.assertEqual(before, source.read_bytes())


if __name__ == '__main__':
    unittest.main()
