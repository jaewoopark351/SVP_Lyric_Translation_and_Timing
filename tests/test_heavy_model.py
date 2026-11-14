"""Composite-model selection, evidence validation, and isolated worker dispatch."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from svp_alignment.audio import alignment, asr_cache, asr_inference, heavy_bundle, models, qwen_cache, worker
from svp_alignment.audio.model_catalog import (
    HEAVY_MODEL, LARGE_ENGLISH_MODEL, MODEL_CHOICES, QWEN_MODEL,
    resolve_model, saved_model_choice,
)
from svp_alignment.audio.transcript import normalize_words
from svp_alignment.audio.model_fingerprint import digest_file


class HeavyModelTests(unittest.TestCase):
    def setUp(self):
        base = (models.ROOT / 'work' / 'gui-validation').resolve()
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='heavy-integration-', dir=base)
        self.workspace = Path(self.temporary.name).resolve()
        self.wav = self.workspace / '원본 보컬.wav'
        sf.write(self.wav, np.zeros(1600, dtype=np.float32), 16000)
        self.original = self.wav.read_bytes()

    def tearDown(self):
        self.assertEqual(self.original, self.wav.read_bytes())
        self.temporary.cleanup()

    def test_heavy_is_explicit_and_saved_without_changing_automatic_default(self):
        self.assertEqual(LARGE_ENGLISH_MODEL, resolve_model([{'source': 'Hello'}]))
        self.assertEqual(HEAVY_MODEL, resolve_model([{'source': 'Hello'}], model_choice=HEAVY_MODEL))
        self.assertIn(HEAVY_MODEL, [value for label, value in MODEL_CHOICES])
        self.assertEqual(HEAVY_MODEL, saved_model_choice({'mode': 'general', 'model_id': HEAVY_MODEL}))
        with self.assertRaisesRegex(ValueError, '언어를 명시'):
            resolve_model([{'source': '안녕'}], model_choice=HEAVY_MODEL)

    def test_model_file_fingerprints_preserve_legacy_import_and_multiblock_bytes(self):
        artifact = self.workspace / '모델 가중치.bin'
        content = b'weights\x00\xff' * 140000
        artifact.write_bytes(content)
        self.assertIs(digest_file, models.digest_file)
        self.assertIs(digest_file, qwen_cache.digest_file)
        self.assertEqual(sha256(content).hexdigest(), digest_file(artifact))

    def test_heavy_unicode_normalization_preserves_exact_original_tokens(self):
        original = [{'source': 'I’m', 'line': 2}, {'source': '안녕!'}, {'source': '123'}]
        normalized = normalize_words(original, HEAVY_MODEL)
        self.assertEqual(["i'm", '안녕', ''], [word['normalized'] for word in normalized])
        self.assertEqual([word['source'] for word in original], [word['source'] for word in normalized])
        self.assertEqual('UNKNOWN', normalized[-1]['status'])
        self.assertNotIn('normalized', original[0])

    def test_bundle_requires_both_complete_snapshots_and_binds_both_digests(self):
        bundle = {'asr': self.workspace / 'asr', 'aligner': self.workspace / 'aligner'}
        with patch.object(asr_cache, 'cached_asr', return_value=bundle['asr']), \
             patch.object(qwen_cache, 'cached_qwen', return_value=None):
            self.assertIsNone(models.cached_model(HEAVY_MODEL))
        with patch.object(asr_cache, 'asr_digest', return_value='a' * 64), \
             patch.object(qwen_cache, 'qwen_digest', return_value='b' * 64) as aligner_digest:
            first = models.model_digest(bundle)
            aligner_digest.return_value = 'c' * 64
            self.assertNotEqual(first, models.model_digest(bundle))
        with patch.object(asr_cache, 'asr_digest', return_value='d' * 64), \
             patch.object(qwen_cache, 'qwen_digest', return_value='b' * 64):
            self.assertNotEqual(first, models.model_digest(bundle))
        with self.assertRaisesRegex(ValueError, '두 스냅샷'):
            models.model_digest({'asr': bundle['asr']})

    def test_uncached_status_does_not_import_gpu_or_acoustic_runtime(self):
        with patch.object(asr_cache, 'cached_asr', return_value=None), \
             patch.dict('sys.modules', {'torch': None, 'torchaudio': None, 'qwen_asr': None}):
            status = models.get_model_status(HEAVY_MODEL)
        self.assertFalse(status['cached'])
        self.assertIsNone(status['path'])
        self.assertEqual({'asr', 'aligner'}, set(status['components']))
        json.dumps(status)

    def _word_result(self, signature='test'):
        words = normalize_words(['hello'], HEAVY_MODEL)
        actual = [{**words[0], 'start': 0.01, 'end': 0.08, 'p': None, 'chars': [],
                   'alignment_unit': 'word', 'score_unavailable': True, 'status': 'AUTO',
                   'observed_units': [{'text': 'hello', 'start': 0.01, 'end': 0.08}]}]
        result = {'signature': signature, 'words': actual, 'provenance': {
            'request_signature': signature, 'model_id': HEAVY_MODEL, 'audio': {'duration': 0.1}}}
        return words, result

    def test_validation_rejects_fabricated_character_times_scores_and_wrong_model(self):
        words, result = self._word_result()
        alignment._validate_result(result, 'test', words, HEAVY_MODEL)
        for changes in ({'p': 0.9}, {'chars': [{'char': 'h', 'start': 0.01, 'end': 0.02, 'p': 0.9}]}):
            bad = deepcopy(result)
            bad['words'][0].update(changes)
            with self.assertRaisesRegex(ValueError, '신뢰도'):
                alignment._validate_result(bad, 'test', words, HEAVY_MODEL)
        with self.assertRaisesRegex(ValueError, '모델이 선택한'):
            alignment._validate_result(result, 'test', words, QWEN_MODEL)
        result['words'][0].update(start=None, end=None, status='UNKNOWN', observed_units=[])
        alignment._validate_result(result, 'test', words, HEAVY_MODEL)

    def test_unsupported_numeric_words_cannot_carry_invented_scores_or_observations(self):
        words, result = self._word_result()
        unsupported = normalize_words(['hello', '123'], HEAVY_MODEL)[1]
        words.append(unsupported)
        result['words'].append({**unsupported, 'start': None, 'end': None, 'p': None,
                                'chars': [], 'alignment_unit': 'word', 'score_unavailable': True,
                                'observed_units': [], 'status': 'UNKNOWN'})
        alignment._validate_result(result, 'test', words, HEAVY_MODEL)
        result['words'][1]['p'] = 0.99
        with self.assertRaisesRegex(ValueError, '신뢰도'):
            alignment._validate_result(result, 'test', words, HEAVY_MODEL)
        result['words'][1]['p'] = None
        result['words'][1]['observed_units'] = [{'text': '123', 'start': 0.08, 'end': 0.09}]
        with self.assertRaisesRegex(ValueError, '미지원'):
            alignment._validate_result(result, 'test', words, HEAVY_MODEL)

    def test_worker_dispatches_both_model_paths_and_preserves_raw_evidence(self):
        folder = self.workspace / 'attempt-worker'
        folder.mkdir()
        words = normalize_words(['hello'], HEAVY_MODEL)
        request = {'model_id': HEAVY_MODEL, 'model_choice': HEAVY_MODEL, 'run_id': 'fixture',
                   'wav_path': str(self.wav), 'wav_sha256': models.digest_file(self.wav),
                   'text_sha256': 't' * 64, 'signature': 'test', 'words': words,
                   'language': 'eng', 'versions': {}, 'settings': {}}
        request_path = folder / 'request.json'
        request_path.write_text(json.dumps(request), encoding='utf-8')
        bundle = {'asr': self.workspace / 'asr', 'aligner': self.workspace / 'aligner'}
        def infer(audio, original_words, asr_path, aligner_path, language, duration, progress,
                  observations_path=None):
            self.assertEqual(bundle['asr'], asr_path)
            self.assertEqual(bundle['aligner'], aligner_path)
            observations_path.write_text('{"recognized_text":"hello"}', encoding='utf-8')
            return self._word_result()[1]['words'], 'cpu', {'recognized_text': 'hello'}
        with patch.object(worker, 'ensure_model', return_value=bundle), \
             patch.object(worker, 'model_digest', return_value='b' * 64), \
             patch.object(asr_inference, 'align_asr', side_effect=infer) as invoked:
            self.assertEqual(0, worker.main(request_path))
        invoked.assert_called_once()
        result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual('QWEN_ASR_REFERENCE_ALIGNMENT', result['provenance']['method'])
        self.assertEqual('hello', result['provenance']['recognition']['recognized_text'])
        self.assertEqual(models.digest_file(folder / 'asr-observations.json'),
                         result['provenance']['raw_observations_sha256'])
        self.assertEqual(heavy_bundle.component_specs(), result['provenance']['model_components'])
        self.assertIsNone(result['words'][0]['p'])

    def test_cache_requires_same_composite_identity_and_unmodified_recognition_evidence(self):
        requested = []
        owner = self
        class Worker:
            def __init__(self, command, **kwargs):
                path = Path(command[-1])
                request = json.loads(path.read_text(encoding='utf-8'))
                requested.append(request)
                _, result = owner._word_result(request['signature'])
                raw = path.parent / 'asr-observations.json'
                raw.write_text('{"recognized_text":"hello"}', encoding='utf-8')
                result['words'] = [{**request['words'][0], **{key: value for key, value in result['words'][0].items()
                                                           if key not in ('source', 'word_index', 'normalized')}}]
                result['provenance'].update(model_sha256='b' * 64,
                    model_components=request['model_components'], cache_reused=False,
                    raw_observations_path=str(raw), raw_observations_sha256=models.digest_file(raw))
                (path.parent / 'result.json').write_text(json.dumps(result), encoding='utf-8')
                self.pid, self.returncode = 1, 0
            def poll(self):
                return 0
            def wait(self, **kwargs):
                return 0
        with patch.object(alignment, 'cached_model', return_value={'asr': 'fake', 'aligner': 'fake'}), \
             patch.object(alignment, 'model_digest', return_value='b' * 64), \
             patch.object(alignment, '_worker_command', side_effect=lambda path: ['fake-worker', str(path)]), \
             patch.object(alignment.subprocess, 'Popen', side_effect=Worker):
            _, first = alignment.align_words(self.wav, ['hello'], self.workspace, model_choice=HEAVY_MODEL)
            _, same = alignment.align_words(self.wav, ['hello'], self.workspace, model_choice=HEAVY_MODEL)
            self.assertFalse(first['cache_reused'])
            self.assertTrue(same['cache_reused'])
            Path(first['raw_observations_path']).write_text('changed evidence', encoding='utf-8')
            _, changed_raw = alignment.align_words(self.wav, ['hello'], self.workspace, model_choice=HEAVY_MODEL)
            self.assertFalse(changed_raw['cache_reused'])
            changed_components = heavy_bundle.component_specs()
            changed_components['asr']['revision'] = 'new-pinned-revision'
            with patch.object(heavy_bundle, 'component_specs', return_value=changed_components):
                _, changed_revision = alignment.align_words(self.wav, ['hello'], self.workspace, model_choice=HEAVY_MODEL)
            self.assertFalse(changed_revision['cache_reused'])
        self.assertEqual(3, len(requested))
        self.assertEqual(requested[0]['signature'], requested[1]['signature'])
        self.assertNotEqual(requested[1]['signature'], requested[2]['signature'])
        self.assertEqual(4096, requested[0]['settings']['recognition_decoding']['max_new_tokens'])


if __name__ == '__main__':
    unittest.main()
