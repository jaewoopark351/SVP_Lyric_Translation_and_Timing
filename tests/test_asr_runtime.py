"""Pinned ASR publication and GPU retry retain immutable recognition evidence."""

from contextlib import nullcontext
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from svp_alignment.audio import asr_cache, asr_inference


class ASRRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        base = self.root / 'work' / 'gui-validation'
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='asr-runtime-', dir=base)
        self.workspace = Path(self.temporary.name).resolve()
        self.cache = self.workspace / 'work' / 'models' / 'qwen-asr' / asr_cache.ASR_REVISION
        self.files = {'config.json': b'{"model_type":"qwen3_asr"}',
                      'model-a.safetensors': b'first-weight-shard',
                      'model-b.safetensors': b'second-weight-shard'}
        self.weights = {name: sha256(content).hexdigest() for name, content in self.files.items()
                        if name.endswith('.safetensors')}
        self.words = [{'source': 'Hello', 'normalized': 'hello', 'word_index': 0}]
        self.mapped = [{**self.words[0], 'start': 0.1, 'end': 0.8,
                        'recognition_status': 'MATCHED', 'status': 'AUTO'}]

    def tearDown(self):
        self.assertTrue(self.workspace.is_relative_to(self.root / 'work'))
        self.temporary.cleanup()

    def cache_patches(self):
        return patch.multiple(asr_cache, ROOT=self.workspace, ASR_CACHE=self.cache,
                              ASR_FILES=tuple(self.files), ASR_WEIGHTS_SHA256=self.weights)

    def response(self, url, timeout):
        content = self.files[url.rsplit('/', 1)[-1]]
        source = io.BytesIO(content)
        source.headers = {'Content-Length': str(len(content))}
        return source

    def test_download_publishes_complete_snapshot_and_reuses_without_network(self):
        with self.cache_patches(), patch.object(asr_cache.urllib.request, 'urlopen', self.response):
            self.assertIsNone(asr_cache.cached_asr())
            target = asr_cache.ensure_asr('first')
            digest = asr_cache.asr_digest(target)
            self.assertEqual(target, asr_cache.cached_asr())
            self.assertEqual(64, len(digest))
            self.assertFalse((target.parent / '.download-first').exists())
            with patch.object(asr_cache.urllib.request, 'urlopen', side_effect=AssertionError('network')):
                self.assertEqual(target, asr_cache.ensure_asr('second'))
            manifest = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
            self.assertEqual(asr_cache.ASR_REVISION, manifest['revision'])
            self.assertEqual(set(self.files), set(manifest['files']))

    def test_weight_tampering_even_with_rewritten_manifest_is_rejected(self):
        with self.cache_patches(), patch.object(asr_cache.urllib.request, 'urlopen', self.response):
            target = asr_cache.ensure_asr('weights')
            (target / 'model-a.safetensors').write_bytes(b'tampered')
            manifest = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
            manifest['files']['model-a.safetensors'] = sha256(b'tampered').hexdigest()
            (target / 'snapshot.json').write_text(json.dumps(manifest), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '공개 SHA256'):
                asr_cache.ensure_asr('retry')
            self.assertEqual(b'tampered', (target / 'model-a.safetensors').read_bytes())

    def test_truncated_download_cleans_own_scratch_without_publishing(self):
        def response(url, timeout):
            source = self.response(url, timeout)
            source.headers['Content-Length'] = str(len(source.getvalue()) + 1)
            return source
        with self.cache_patches(), patch.object(asr_cache.urllib.request, 'urlopen', response):
            with self.assertRaisesRegex(ValueError, '연결이 종료'):
                asr_cache.ensure_asr('truncated')
            self.assertFalse(self.cache.exists())
            self.assertFalse((self.cache.parent / '.download-truncated').exists())

    def test_existing_target_or_staging_files_are_never_overwritten(self):
        with self.cache_patches(), patch.object(asr_cache.urllib.request, 'urlopen') as download:
            staging = self.cache.parent / '.download-collision'
            staging.mkdir(parents=True)
            (staging / 'config.json').write_bytes(b'prior-evidence')
            with self.assertRaises(FileExistsError):
                asr_cache.ensure_asr('collision')
            self.assertEqual(b'prior-evidence', (staging / 'config.json').read_bytes())
            self.cache.mkdir()
            (self.cache / 'unrelated.txt').write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError, '덮어쓰지'):
                asr_cache.ensure_asr('new-attempt')
            self.assertEqual(b'keep', (self.cache / 'unrelated.txt').read_bytes())
            download.assert_not_called()

    def test_cleanup_leaves_unknown_files_and_rejects_traversal(self):
        with self.cache_patches():
            staging = self.cache.parent / '.download-owner'
            staging.mkdir(parents=True)
            (staging / 'config.json').write_bytes(b'ours')
            (staging / 'unrelated.txt').write_bytes(b'keep')
            asr_cache.cleanup_asr_download('owner')
            self.assertFalse((staging / 'config.json').exists())
            self.assertEqual(b'keep', (staging / 'unrelated.txt').read_bytes())
            for run_id in ('../outside', '', 'a/b', 'x' * 81):
                with self.assertRaises(ValueError):
                    asr_cache.cleanup_asr_download(run_id)

    def fake_modules(self, *, gpu=False, outcomes=None):
        class OOM(RuntimeError):
            pass
        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=Mock(return_value=gpu),
                                 is_bf16_supported=Mock(return_value=True), empty_cache=Mock()),
            get_num_threads=lambda: 16, set_num_threads=Mock(), inference_mode=nullcontext,
            bfloat16='bf16', float16='fp16', float32='fp32')
        torch.cuda.OutOfMemoryError = OOM
        item = SimpleNamespace(text='Hello', start_time=0.1, end_time=0.8)
        result = SimpleNamespace(text='Hello', language='English',
                                 time_stamps=SimpleNamespace(items=[item]))
        transcription = Mock(side_effect=outcomes or [[result]])
        loader = Mock(return_value=SimpleNamespace(transcribe=transcription))
        mapper = Mock(return_value=self.mapped)
        modules = {'torch': torch, 'qwen_asr': SimpleNamespace(
                       Qwen3ASRModel=SimpleNamespace(from_pretrained=loader)),
                   'qwen_asr.inference.qwen3_asr': SimpleNamespace(MAX_FORCE_ALIGN_INPUT_SECONDS=180),
                   'svp_alignment.audio.asr_reference': SimpleNamespace(map_recognition=mapper)}
        return modules, torch, loader, transcription, mapper, result

    def test_cpu_inference_preserves_raw_evidence_and_maps_only_after_publication(self):
        modules, torch, loader, transcription, mapper, result = self.fake_modules()
        raw = self.workspace / 'asr 관측.json'
        def mapped_after_saved(words, items, duration):
            self.assertTrue(raw.is_file())
            self.assertEqual('Hello', json.loads(raw.read_text(encoding='utf-8'))['recognized_text'])
            self.assertEqual([{'text': 'Hello', 'start_time': 0.1, 'end_time': 0.8}], items)
            return self.mapped
        mapper.side_effect = mapped_after_saved
        with patch.dict('sys.modules', modules):
            actual, device, meta = asr_inference.align_asr(
                b'waveform', self.words, 'asr-model', 'aligner-model', 'eng', 1.0, Mock(), raw)
        self.assertEqual(self.mapped, actual)
        self.assertEqual('cpu', device)
        self.assertEqual(1, meta['matched_word_count'])
        self.assertEqual(180, meta['timestamp_chunk_seconds'])
        self.assertEqual('transformers', meta['backend'])
        self.assertEqual(0, meta['invalid_observation_word_count'])
        self.assertEqual(sha256(raw.read_bytes()).hexdigest(), meta['raw_observations_sha256'])
        kwargs = loader.call_args.kwargs
        self.assertEqual('aligner-model', kwargs['forced_aligner'])
        self.assertEqual('fp32', kwargs['dtype'])
        self.assertEqual('sdpa', kwargs['attn_implementation'])
        self.assertTrue(kwargs['local_files_only'])
        self.assertTrue(kwargs['forced_aligner_kwargs']['local_files_only'])
        self.assertEqual(1, kwargs['max_inference_batch_size'])
        self.assertGreaterEqual(kwargs['max_new_tokens'], 2048)
        self.assertEqual(16000, transcription.call_args.kwargs['audio'][1])
        self.assertTrue(transcription.call_args.kwargs['return_time_stamps'])

    def test_gpu_oom_retries_cpu_without_overwriting_or_losing_raw_observations(self):
        modules, torch, loader, transcription, mapper, result = self.fake_modules(gpu=True)
        transcription.side_effect = [torch.cuda.OutOfMemoryError('memory'), [result]]
        raw = self.workspace / 'retry.json'
        with patch.dict('sys.modules', modules):
            actual, device, meta = asr_inference.align_asr(
                b'waveform', self.words, 'asr', 'aligner', 'eng', 1.0, Mock(), raw)
        self.assertEqual('cpu', device)
        self.assertEqual(['cuda:0', 'cpu'], [call.kwargs['device_map'] for call in loader.call_args_list])
        self.assertEqual(['bf16', 'fp32'], [call.kwargs['dtype'] for call in loader.call_args_list])
        self.assertEqual(1, mapper.call_count)
        self.assertEqual(sha256(raw.read_bytes()).hexdigest(), meta['raw_observations_sha256'])

    def test_existing_raw_observations_are_not_replaced_and_mapping_does_not_run(self):
        modules, torch, loader, transcription, mapper, result = self.fake_modules()
        raw = self.workspace / 'existing.json'
        raw.write_bytes(b'previous-evidence')
        with patch.dict('sys.modules', modules):
            with self.assertRaises(FileExistsError):
                asr_inference.align_asr(b'audio', self.words, 'asr', 'aligner', 'eng', 1.0, Mock(), raw)
        self.assertEqual(b'previous-evidence', raw.read_bytes())
        mapper.assert_not_called()

    def test_mapping_failure_still_leaves_original_model_observations(self):
        modules, torch, loader, transcription, mapper, result = self.fake_modules()
        mapper.side_effect = ValueError('reference mapping failed')
        raw = self.workspace / 'mapping-failed.json'
        with patch.dict('sys.modules', modules):
            with self.assertRaisesRegex(ValueError, 'reference mapping failed'):
                asr_inference.align_asr(b'audio', self.words, 'asr', 'aligner', 'eng', 1.0, Mock(), raw)
        self.assertEqual('Hello', json.loads(raw.read_text(encoding='utf-8'))['items'][0]['text'])

    def test_invalid_duration_or_outside_raw_path_are_rejected(self):
        for duration in (0, -1, float('nan'), float('inf'), True, '1'):
            with self.assertRaisesRegex(ValueError, '재생 길이'):
                asr_inference.align_asr(b'audio', self.words, 'asr', 'aligner', 'eng', duration, Mock())
        with self.assertRaisesRegex(ValueError, '최대 300초'):
            asr_inference.align_asr(b'audio', self.words, 'asr', 'aligner', 'eng', 300.001, Mock())
        outside = self.root / 'must-not-write-asr.json'
        self.assertFalse(outside.exists())
        with self.assertRaisesRegex(ValueError, 'work 내부'):
            asr_inference._write_observations(outside, [], 1.0, 'English', '', 'English')
        self.assertFalse(outside.exists())


if __name__ == '__main__':
    unittest.main()
