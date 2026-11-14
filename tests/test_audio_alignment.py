"""Acoustic normalization, CTC decoding, and real isolated-worker cancellation."""

import ctypes
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf
from filelock import FileLock

from svp_alignment.audio import align_words, get_model_status
from svp_alignment.audio import alignment
from svp_alignment.audio.inference import decode_words
from svp_alignment.audio.models import MODEL_CACHE, ROOT
from svp_alignment.audio.transcript import (
    ENGLISH_MODEL, MULTILINGUAL_MODEL, normalize_words, select_model,
)
from svp_alignment.audio.model_catalog import (
    LARGE_ENGLISH_MODEL, QWEN_MODEL, resolve_model, saved_model_choice,
)
from svp_alignment.audio.qwen_inference import map_observations, _write_observations
from svp_alignment.audio import qwen_cache
from svp_alignment.audio.waveform import load_waveform


def process_is_running(pid):
    if os.name != 'nt':
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


class AudioAlignmentTests(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT / 'work' / 'gui-validation').resolve()
        self.base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='audio-test-', dir=self.base)
        self.workspace = Path(self.temporary.name).resolve()
        self.wav = self.workspace / '원본 보컬.wav'
        self.signal = np.column_stack((np.full(4410, 0.1), np.full(4410, 0.3)))
        sf.write(self.wav, self.signal, 44100, subtype='PCM_16')
        self.original_bytes = self.wav.read_bytes()

    def tearDown(self):
        self.assertEqual(self.original_bytes, self.wav.read_bytes())
        self.assertTrue(self.workspace.resolve().is_relative_to(self.base))
        self.assertNotEqual(self.workspace.resolve(), self.base)
        self.temporary.cleanup()

    def test_normalization_preserves_original_tokens_and_marks_unsupported(self):
        original = [{'source': 'I’m', 'line': 2}, {'source': '123'}, {'source': 'Привет'}]
        words = normalize_words(original, ENGLISH_MODEL)
        self.assertEqual([word['source'] for word in original], [word['source'] for word in words])
        self.assertEqual("i'm", words[0]['normalized'])
        self.assertEqual(2, words[0]['line'])
        self.assertEqual(['AUTO', 'UNKNOWN', 'UNKNOWN'], [word['status'] for word in words])
        self.assertEqual([0, 1, 2], [word['word_index'] for word in words])
        self.assertNotIn('normalized', original[0])
        self.assertEqual(LARGE_ENGLISH_MODEL, select_model(original[:2]))
        self.assertEqual(MULTILINGUAL_MODEL, select_model(original))
        self.assertEqual(QWEN_MODEL, select_model([{'source': 'bonjour'}], 'fra'))

    def test_multilingual_romanization_keeps_original_positions(self):
        words = normalize_words([{'source': '안녕', 'column': 4}, {'source': '世界'}], MULTILINGUAL_MODEL)
        self.assertEqual(['안녕', '世界'], [word['source'] for word in words])
        self.assertEqual(4, words[0]['column'])
        self.assertTrue(all(word['normalized'].isascii() and word['normalized'] for word in words))

    def test_stereo_wav_is_read_only_and_resampled_to_model_rate(self):
        signal, metadata = load_waveform(self.wav)
        self.assertEqual(1600, len(signal))
        self.assertEqual(np.float32, signal.dtype)
        self.assertAlmostEqual(0.2, float(np.mean(signal)), places=3)
        self.assertEqual(0.1, metadata['duration'])
        self.assertEqual(2, metadata['channels'])
        self.assertEqual(44100, metadata['sample_rate'])
        self.assertEqual(16000, metadata['model_sample_rate'])

    def test_ctc_spans_keep_repeated_words_and_unknown_token_in_source_order(self):
        words = normalize_words([{'source': 'AB'}, {'source': '123'}, {'source': 'BA'}], ENGLISH_MODEL)
        path = [0, 1, 1, 0, 2, 2, 0, 3, 0, 2, 2, 0, 1, 1, 0]
        posterior = np.full((len(path), 4), np.log(0.01 / 3), dtype=np.float32)
        posterior[np.arange(len(path)), path] = np.log(0.99)
        aligned = decode_words(posterior, ('-', 'A', 'B', '|'), words, ENGLISH_MODEL, 1.0)
        self.assertEqual(['AB', '123', 'BA'], [word['source'] for word in aligned])
        self.assertEqual(['ab', '', 'ba'], [''.join(char['char'] for char in word['chars']) for word in aligned])
        self.assertIsNone(aligned[1]['start'])
        self.assertIsNone(aligned[1]['end'])
        self.assertGreater(aligned[0]['p'], 0.98)
        self.assertLess(aligned[0]['end'], aligned[2]['start'])
        self.assertEqual(0.0325, aligned[0]['start'])

    def test_ctc_rejects_a_transcript_longer_than_the_available_frames(self):
        words = normalize_words(['aaaa'], ENGLISH_MODEL)
        with self.assertRaisesRegex(ValueError, '너무 많아'):
            decode_words(np.zeros((2, 2), dtype=np.float32), ('-', 'A'), words, ENGLISH_MODEL, 0.1)

    def test_pre_cancel_does_not_start_or_create_acoustic_work(self):
        with patch.object(alignment.subprocess, 'Popen') as launch:
            with self.assertRaises(InterruptedError):
                align_words(self.wav, ['hello'], self.workspace, cancelled=lambda: True)
            launch.assert_not_called()
        self.assertFalse((self.workspace / 'audio').exists())

    def test_cancellation_while_waiting_for_another_worker_never_starts_a_process(self):
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(MODEL_CACHE.parent / '.alignment.lock'))
        waiting = {'deadline': None}
        def progress(label, fraction):
            if '종료 대기' in label:
                waiting['deadline'] = time.monotonic() + 0.15
        def cancelled():
            return waiting['deadline'] is not None and time.monotonic() >= waiting['deadline']
        with lock, patch.object(alignment.subprocess, 'Popen') as launch:
            with self.assertRaises(InterruptedError):
                align_words(self.wav, ['hello'], self.workspace, progress=progress, cancelled=cancelled)
            launch.assert_not_called()
        self.assertIsNotNone(waiting['deadline'])

    def test_real_worker_cancellation_joins_actual_interpreter_and_releases_lock(self):
        if not get_model_status()['cached']:
            self.skipTest('No cached English weights; cancellation test must not download')
        cancel = Event()
        def progress(label, fraction):
            if 'WAV 읽기' in label:
                cancel.set()
        with self.assertRaises(InterruptedError):
            align_words(self.wav, ['hello'], self.workspace, progress=progress, cancelled=cancel.is_set,
                        model_choice=ENGLISH_MODEL)
        self.assertTrue(cancel.is_set())
        attempts = list((self.workspace / 'audio').glob('attempt-*'))
        self.assertEqual(1, len(attempts))
        process = json.loads((attempts[0] / 'process.json').read_text(encoding='utf-8'))
        runtime = json.loads((attempts[0] / 'runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(process['pid'], runtime['pid'])
        self.assertFalse(process_is_running(runtime['pid']))
        self.assertFalse((self.workspace / 'audio' / 'result.json').exists())
        if os.name == 'nt':
            import sys
            self.assertEqual(Path(sys.prefix).resolve(), Path(runtime['python_prefix']).resolve())
            sites = [Path(value).resolve() for value in runtime['sys_path'] if 'site-packages' in value]
            self.assertEqual([Path(sys.prefix).resolve() / 'Lib' / 'site-packages'], sites)
        with FileLock(str(MODEL_CACHE.parent / '.alignment.lock'), timeout=0.5):
            pass

    def test_workspace_cannot_place_audio_outputs_outside_project_work(self):
        with self.assertRaisesRegex(ValueError, '개별 작업 폴더'):
            align_words(self.wav, ['hello'], ROOT)
        self.assertFalse((ROOT / 'audio').exists())

    def test_model_status_only_checks_files_and_does_not_load_an_acoustic_model(self):
        with patch.dict('sys.modules', {'torch': None, 'torchaudio': None}):
            status = get_model_status()
        self.assertEqual(ENGLISH_MODEL, status['model_id'])
        self.assertIn('cached', status)
        self.assertIn('url', status)

    def test_model_selection_defaults_to_large_and_keeps_explicit_alternatives(self):
        words = [{'source': 'Hello'}]
        self.assertEqual(LARGE_ENGLISH_MODEL, resolve_model(words))
        self.assertEqual(ENGLISH_MODEL, resolve_model(words, model_choice=ENGLISH_MODEL))
        self.assertEqual(QWEN_MODEL, resolve_model([{'source': '안녕'}], 'kor'))
        self.assertEqual(MULTILINGUAL_MODEL, resolve_model([{'source': '안녕'}]))
        self.assertEqual(MULTILINGUAL_MODEL, resolve_model(words, 'mul'))
        with self.assertRaisesRegex(ValueError, '영어 가사'):
            resolve_model(words, 'kor', LARGE_ENGLISH_MODEL)
        with self.assertRaisesRegex(ValueError, '언어를 명시'):
            resolve_model([{'source': '안녕'}], 'auto', QWEN_MODEL)
        with self.assertRaisesRegex(ValueError, '음성 모델'):
            resolve_model(words, model_choice='cached_counting_stars')
        with self.assertRaisesRegex(ValueError, '지원하지 않는'):
            resolve_model(words, model_choice='arbitrary-model')

    def test_saved_jobs_keep_their_recorded_backend(self):
        self.assertEqual('cached_counting_stars', saved_model_choice({}))
        self.assertEqual(ENGLISH_MODEL, saved_model_choice({'mode': 'general'}, {'model_id': ENGLISH_MODEL}))
        self.assertEqual(MULTILINGUAL_MODEL, saved_model_choice({'mode': 'general', 'language': 'kor'}))
        self.assertEqual('auto', saved_model_choice({'mode': 'general', 'language': 'auto'}))
        self.assertEqual(LARGE_ENGLISH_MODEL, saved_model_choice({'model_choice': LARGE_ENGLISH_MODEL}))

    def test_large_ctc_uses_english_labels_with_exact_character_times(self):
        words = normalize_words(['AB'], LARGE_ENGLISH_MODEL)
        labels = ('-', 'A', 'B')
        posterior = np.full((7, 3), np.log(0.01 / 2), dtype=np.float32)
        posterior[np.arange(7), [0, 1, 1, 0, 2, 2, 0]] = np.log(0.99)
        actual = decode_words(posterior, labels, words, LARGE_ENGLISH_MODEL, 1.0)
        self.assertEqual('ab', ''.join(character['char'] for character in actual[0]['chars']))
        self.assertGreater(actual[0]['p'], 0.98)

    def test_qwen_keeps_word_times_without_fabricating_character_spans_or_scores(self):
        words = normalize_words([{'source': 'Hello,', 'line': 1}, {'source': '123'}, {'source': 'world!'}], QWEN_MODEL)
        aligned = map_observations(words, [
            {'text': 'Hello', 'start_time': 0.1, 'end_time': 0.3},
            {'text': 'world', 'start_time': 0.4, 'end_time': 0.8}], 1.0)
        self.assertEqual(['Hello,', '123', 'world!'], [word['source'] for word in aligned])
        self.assertEqual([0.1, None, 0.4], [word['start'] for word in aligned])
        self.assertTrue(all(word['chars'] == [] and word['p'] is None
                            and word['score_unavailable'] and word['alignment_unit'] == 'word' for word in aligned))
        self.assertEqual(1, aligned[0]['line'])
        self.assertEqual([{'text': 'hello', 'start': 0.1, 'end': 0.3}], aligned[0]['observed_units'])

    def test_qwen_aggregates_only_real_subunits_whose_boundaries_match_source_word(self):
        words = normalize_words(['你好', '你好'], QWEN_MODEL)
        aligned = map_observations(words, [
            {'text': text, 'start_time': start, 'end_time': end} for text, start, end in
            [('你', 0.1, 0.2), ('好', 0.2, 0.4), ('你', 0.6, 0.7), ('好', 0.8, 0.9)]], 1.0)
        self.assertEqual([(0.1, 0.4), (0.6, 0.9)], [(word['start'], word['end']) for word in aligned])
        self.assertEqual([0, 1], [word['word_index'] for word in aligned])
        self.assertTrue(all(not word['chars'] for word in aligned))
        crossing = map_observations(normalize_words(['a', 'b'], QWEN_MODEL),
                                    [{'text': 'ab', 'start_time': 0.1, 'end_time': 0.3}], 1.0)
        self.assertTrue(all(word['status'] == 'UNKNOWN' and word['start'] is None for word in crossing))

    def test_qwen_rejects_text_reordering_but_invalid_times_become_unknown(self):
        words = normalize_words(['a', 'b'], QWEN_MODEL)
        with self.assertRaisesRegex(ValueError, '문자·순서·반복'):
            map_observations(words, [{'text': 'ba', 'start_time': 0.0, 'end_time': 0.5}], 1.0)
        outside = map_observations(normalize_words(['ab'], QWEN_MODEL),
                                   [{'text': 'ab', 'start_time': 0.0, 'end_time': 2.0}], 1.0)
        self.assertIsNone(outside[0]['start'])
        self.assertEqual('UNKNOWN', outside[0]['status'])
        self.assertIn('WAV 범위', outside[0]['reason'])
        invalid = map_observations(normalize_words(['ab'], QWEN_MODEL),
                                   [{'text': 'ab', 'start_time': float('nan'), 'end_time': 0.5}], 1.0)
        self.assertIsNone(invalid[0]['start'])
        self.assertIn('유한한 수', invalid[0]['reason'])
        zero = map_observations(normalize_words(['ab'], QWEN_MODEL),
                                [{'text': 'ab', 'start_time': 0.5, 'end_time': 0.5}], 1.0)
        self.assertIsNone(zero[0]['start'])
        self.assertEqual('UNKNOWN', zero[0]['status'])

    def test_qwen_invalid_unit_does_not_change_or_discard_unrelated_observations(self):
        words = normalize_words(['a', 'b', 'c', 'd', 'e'], QWEN_MODEL)
        items = [{'text': text, 'start_time': start, 'end_time': end} for text, start, end in
                 [('a', 0.1, 0.2), ('b', 0.3, 0.6), ('c', 0.5, 0.7),
                  ('d', 0.8, 0.9), ('e', 0.95, 1.001)]]
        actual = map_observations(words, items, 1.0)
        self.assertEqual([(0.1, 0.2), (None, None), (None, None), (0.8, 0.9), (None, None)],
                         [(word['start'], word['end']) for word in actual])
        self.assertIn('겹치거나', actual[1]['reason'])
        self.assertIn('WAV 범위', actual[4]['reason'])
        self.assertEqual(1.001, items[-1]['end_time'])
        self.assertTrue(all(not word['chars'] and word['p'] is None for word in actual))
        result = {'signature': 'test', 'words': actual, 'provenance': {
            'request_signature': 'test', 'model_id': QWEN_MODEL, 'audio': {'duration': 1.0}}}
        alignment._validate_result(result, 'test', words)

    def test_qwen_rechecks_survivors_after_a_wider_timestamp_inversion(self):
        words = normalize_words(['a', 'b', 'c', 'd', 'e'], QWEN_MODEL)
        items = [{'text': text, 'start_time': start, 'end_time': end} for text, start, end in
                 [('a', 5, 6), ('b', 10, 11), ('c', 0, 1), ('d', 2, 3), ('e', 12, 13)]]
        actual = map_observations(words, items, 14)
        self.assertEqual([None, None, None, None, 12], [word['start'] for word in actual])
        self.assertEqual(13, actual[-1]['end'])

    def test_qwen_raw_observations_preserve_unmodified_official_times_exclusively(self):
        destination = self.workspace / 'qwen-observations.json'
        items = [SimpleNamespace(text='a', start_time=0.1, end_time=1.001),
                 SimpleNamespace(text='b', start_time=float('nan'), end_time=0.2)]
        _write_observations(destination, items, 1.0, 'English')
        saved = json.loads(destination.read_text(encoding='utf-8'))
        self.assertEqual(1.001, saved['items'][0]['end_time'])
        self.assertEqual('nan', saved['items'][1]['start_time'])
        original_bytes = destination.read_bytes()
        with self.assertRaises(FileExistsError):
            _write_observations(destination, [], 1.0, 'English')
        self.assertEqual(original_bytes, destination.read_bytes())

    def test_qwen_result_validation_rejects_invented_characters_and_probabilities(self):
        words = normalize_words(['hello'], QWEN_MODEL)
        actual = map_observations(words, [{'text': 'hello', 'start_time': 0.1, 'end_time': 0.4}], 1.0)
        result = {'signature': 'test', 'words': actual, 'provenance': {
            'request_signature': 'test', 'model_id': QWEN_MODEL, 'audio': {'duration': 1.0}}}
        alignment._validate_result(result, 'test', words)
        actual[0]['p'] = 0.99
        with self.assertRaisesRegex(ValueError, '신뢰도'):
            alignment._validate_result(result, 'test', words)

    def test_qwen_cached_status_and_catalog_do_not_import_model_runtime(self):
        with patch.dict('sys.modules', {'torch': None, 'torchaudio': None, 'qwen_asr': None}):
            status = get_model_status(QWEN_MODEL)
        self.assertEqual(QWEN_MODEL, status['model_id'])
        self.assertEqual('1c85775dfe71a2a90e6aeea682c6eb9df3d8848b', status['revision'])

    def test_changing_model_recomputes_same_job_while_same_model_reuses_observations(self):
        weights = self.workspace / 'test-weights.bin'
        weights.write_bytes(b'test weights only')
        requested = []
        class Worker:
            def __init__(worker, command, **kwargs):
                request_path = Path(command[-1])
                request = json.loads(request_path.read_text(encoding='utf-8'))
                requested.append(request)
                chars = [{'char': char, 'start': index / 100, 'end': (index + 1) / 100,
                          'p': 0.9} for index, char in enumerate(request['words'][0]['normalized'])]
                words = [{**request['words'][0], 'start': chars[0]['start'], 'end': chars[-1]['end'],
                          'p': 0.9, 'chars': chars}]
                result = {'signature': request['signature'], 'words': words, 'provenance': {
                    'request_signature': request['signature'], 'model_id': request['model_id'],
                    'model_sha256': alignment.model_digest(weights), 'audio': {'duration': 0.1},
                    'cache_reused': False}}
                (request_path.parent / 'result.json').write_text(json.dumps(result), encoding='utf-8')
                worker.pid, worker.returncode = 1, 0
            def poll(worker):
                return 0
            def wait(worker, **kwargs):
                return 0
        with patch.object(alignment, 'cached_model', return_value=weights), \
             patch.object(alignment, '_worker_command', side_effect=lambda p: ['fake-worker', str(p)]), \
             patch.object(alignment.subprocess, 'Popen', side_effect=Worker):
            _, first = align_words(self.wav, ['hello'], self.workspace, model_choice=ENGLISH_MODEL)
            _, same = align_words(self.wav, ['hello'], self.workspace, model_choice=ENGLISH_MODEL)
            _, different = align_words(self.wav, ['hello'], self.workspace, model_choice=LARGE_ENGLISH_MODEL)
        self.assertFalse(first['cache_reused'])
        self.assertTrue(same['cache_reused'])
        self.assertFalse(different['cache_reused'])
        self.assertEqual([ENGLISH_MODEL, LARGE_ENGLISH_MODEL], [item['model_id'] for item in requested])
        self.assertNotEqual(requested[0]['signature'], requested[1]['signature'])

    def test_qwen_download_publishes_only_complete_pinned_snapshot_and_checks_all_files(self):
        destination = self.workspace / 'qwen' / qwen_cache.QWEN_REVISION
        content = b'public model test fixture'
        requested = []
        class Response(io.BytesIO):
            headers = {'Content-Length': str(len(content))}
        def download(url, **kwargs):
            requested.append(url)
            return Response(content)
        with patch.object(qwen_cache, 'QWEN_CACHE', destination), \
             patch.object(qwen_cache, 'QWEN_WEIGHTS_SHA256', sha256(content).hexdigest()), \
             patch.object(qwen_cache.urllib.request, 'urlopen', side_effect=download):
            actual = qwen_cache.ensure_qwen('complete-fixture')
            self.assertEqual(destination, actual)
            first_hash = qwen_cache.qwen_digest(actual)
            self.assertEqual(actual, qwen_cache.ensure_qwen('reuse-fixture'))
            self.assertEqual(len(qwen_cache.QWEN_FILES), len(requested))
            self.assertTrue(all(qwen_cache.QWEN_REVISION in url for url in requested))
            self.assertFalse((destination.parent / '.download-complete-fixture').exists())
            (actual / 'config.json').write_bytes(b'changed config')
            with self.assertRaisesRegex(ValueError, '스냅샷 기록'):
                qwen_cache.qwen_digest(actual)
            self.assertEqual(64, len(first_hash))

    def test_qwen_failed_download_does_not_publish_or_replace_existing_snapshot(self):
        destination = self.workspace / 'qwen-failure' / qwen_cache.QWEN_REVISION
        class Response(io.BytesIO):
            headers = {'Content-Length': '100'}
        with patch.object(qwen_cache, 'QWEN_CACHE', destination), \
             patch.object(qwen_cache.urllib.request, 'urlopen', return_value=Response(b'short')):
            with self.assertRaisesRegex(ValueError, '연결이 종료'):
                qwen_cache.ensure_qwen('incomplete-fixture')
        self.assertFalse(destination.exists())
        self.assertFalse((destination.parent / '.download-incomplete-fixture').exists())
        with self.assertRaisesRegex(ValueError, '식별자'):
            qwen_cache.ensure_qwen('../outside')

    def test_qwen_cancel_cleanup_removes_only_this_attempts_known_scratch(self):
        destination = self.workspace / 'qwen-cleanup' / qwen_cache.QWEN_REVISION
        scratch = destination.parent / '.download-cancelled-worker'
        other = destination.parent / '.download-other-worker'
        scratch.mkdir(parents=True)
        other.mkdir()
        (scratch / 'model.safetensors').write_bytes(b'incomplete')
        (scratch / 'unrelated.txt').write_text('preserve', encoding='utf-8')
        (other / 'model.safetensors').write_bytes(b'other')
        with patch.object(qwen_cache, 'QWEN_CACHE', destination):
            qwen_cache.cleanup_qwen_download('cancelled-worker')
        self.assertFalse((scratch / 'model.safetensors').exists())
        self.assertEqual('preserve', (scratch / 'unrelated.txt').read_text(encoding='utf-8'))
        self.assertEqual(b'other', (other / 'model.safetensors').read_bytes())


if __name__ == '__main__':
    unittest.main()
