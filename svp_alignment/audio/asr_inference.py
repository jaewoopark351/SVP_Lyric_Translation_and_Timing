"""Recognize vocals, observe recognized-word times, and retain raw evidence."""

import gc
import hashlib
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path

from .asr_cache import ASR_MODEL
from .model_catalog import QWEN_MODEL, qwen_language
from .waveform import MODEL_RATE

ASR_MAX_NEW_TOKENS = 4096
MAX_AUDIO_SECONDS = 300.0


def _field(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _raw_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None if value is None else str(value)
    return number if math.isfinite(number) else repr(number)


def _raw_items(items):
    return [{'text': str(_field(item, 'text') or ''),
             'start_time': _raw_number(_field(item, 'start_time')),
             'end_time': _raw_number(_field(item, 'end_time'))} for item in items]


def _write_observations(path, items, duration, language, recognized_text, recognized_language):
    path = Path(path)
    work_root = Path(__file__).resolve().parents[2] / 'work'
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(work_root.resolve()):
        raise ValueError('Qwen ASR 관측 원시 자료는 프로젝트 work 내부에 저장해야 합니다.')
    payload = {'source': 'official-qwen-asr-returned-items-before-reference-mapping',
               'asr_model_id': ASR_MODEL, 'aligner_model_id': QWEN_MODEL,
               'duration': duration, 'language': language,
               'recognized_text': recognized_text, 'recognized_language': recognized_language,
               'items': items}
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    with path.open('xb') as output:
        output.write(serialized)
    return str(path), hashlib.sha256(serialized).hexdigest()


def align_asr(audio, words, model_path, aligner_path, language, duration, progress,
              observations_path=None):
    """Keep TXT authoritative; use ASR times only where reference mapping succeeds."""
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError('Qwen ASR에 제공된 WAV 재생 길이가 올바르지 않습니다.')
    if duration > MAX_AUDIO_SECONDS:
        raise ValueError('Qwen ASR 모델은 이 앱에서 최대 300초 WAV를 지원합니다. 긴 곡은 MMS FA 또는 영어 Large를 선택하세요.')
    import torch
    try:
        from qwen_asr import Qwen3ASRModel
    except ImportError as error:
        raise RuntimeError('Qwen ASR 모델에는 requirements.txt의 qwen-asr와 관련 패키지가 필요합니다.') from error
    from .asr_reference import map_recognition

    try:
        sdk_module = importlib.import_module('qwen_asr.inference.qwen3_asr')
    except ImportError:
        sdk_module = None
    chunk_seconds = getattr(sdk_module, 'MAX_FORCE_ALIGN_INPUT_SECONDS', None)
    try:
        sdk_version = version('qwen-asr')
    except PackageNotFoundError:
        sdk_version = None

    language_name = qwen_language(words, language)
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    torch.set_num_threads(min(8, max(1, torch.get_num_threads())))

    def compute(selected_device):
        model = None
        try:
            progress('Qwen3 ASR 1.7B + ForcedAligner 0.6B 읽기 · ' + selected_device, 0.22)
            dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
                     ) if selected_device.startswith('cuda') else torch.float32
            model_kwargs = {'dtype': dtype, 'device_map': selected_device,
                            'attn_implementation': 'sdpa', 'local_files_only': True}
            model = Qwen3ASRModel.from_pretrained(
                str(model_path), forced_aligner=str(aligner_path),
                forced_aligner_kwargs=model_kwargs.copy(),
                max_inference_batch_size=1, max_new_tokens=ASR_MAX_NEW_TOKENS,
                **model_kwargs)
            progress('Qwen ASR로 보컬 인식과 발음 시각 관측 · ' + language_name, 0.4)
            with torch.inference_mode():
                results = model.transcribe(audio=(audio, MODEL_RATE), language=language_name,
                                           return_time_stamps=True)
            if len(results) != 1:
                raise ValueError('Qwen ASR의 오디오 결과 개수가 입력과 다릅니다.')
            result = results[0]
            stamps = _field(result, 'time_stamps')
            items = _field(stamps, 'items') if stamps is not None else []
            if items is None:
                raise ValueError('Qwen ASR가 인식 단어의 관측 시각을 반환하지 않았습니다.')
            # Serialize values before model cleanup. A CPU retry never replaces
            # a raw observation file because publication happens only below.
            return (str(_field(result, 'text') or ''),
                    str(_field(result, 'language') or language_name), _raw_items(items))
        finally:
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    try:
        recognized_text, recognized_language, items = compute(device)
    except torch.cuda.OutOfMemoryError:
        if device == 'cpu':
            raise
        progress('GPU 메모리가 부족하여 Qwen ASR를 CPU로 다시 계산합니다.', 0.22)
        gc.collect()
        torch.cuda.empty_cache()
        device = 'cpu'
        recognized_text, recognized_language, items = compute(device)

    metadata = {'asr_model_id': ASR_MODEL, 'aligner_model_id': QWEN_MODEL,
                'recognized_text': recognized_text, 'recognized_language': recognized_language,
                'recognized_word_count': len(items), 'source_word_count': len(words),
                'max_new_tokens': ASR_MAX_NEW_TOKENS, 'max_inference_batch_size': 1,
                'backend': 'transformers', 'qwen_asr_version': sdk_version,
                'timestamp_chunk_seconds': chunk_seconds}
    if observations_path is not None:
        raw_path, raw_hash = _write_observations(observations_path, items, duration, language_name,
                                                recognized_text, recognized_language)
        metadata.update(raw_observations_path=raw_path, raw_observations_sha256=raw_hash)
    progress('ASR 인식 결과를 원본 TXT의 단어·순서·반복과 대조', 0.9)
    mapped = map_recognition(words, items, duration)
    metadata.update({name.lower() + '_word_count':
                     sum(word.get('recognition_status') == name for word in mapped)
                     for name in ('MATCHED', 'UNMATCHED', 'AMBIGUOUS', 'INVALID_OBSERVATION')})
    return mapped, device, metadata
