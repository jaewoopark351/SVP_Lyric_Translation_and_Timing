"""Qwen word-unit observations with exact original-token correspondence."""

import gc
import json
import math
from pathlib import Path

from .model_catalog import qwen_language
from .transcript import clean_qwen_token
from .waveform import MODEL_RATE

MAX_AUDIO_SECONDS = 300.0


def map_observations(words, items, duration):
    """Never invent character times or split one observed unit across source words."""
    observed = []
    observed_text = ''
    for item in items:
        text = clean_qwen_token(item['text'] if isinstance(item, dict) else item.text)
        if not text:
            raise ValueError('Qwen 모델의 관측 문자가 올바르지 않습니다.')
        try:
            start = float(item['start_time'] if isinstance(item, dict) else item.start_time)
            end = float(item['end_time'] if isinstance(item, dict) else item.end_time)
        except (ValueError, TypeError):
            start = end = None
        issues = []
        if start is None or not all(math.isfinite(value) for value in (start, end)):
            issues.append('Qwen 관측 시각이 유한한 수가 아닙니다.')
        elif not 0 <= start < end <= duration:
            issues.append('Qwen 관측 시각이 WAV 범위를 벗어나거나 길이가 0 또는 음수입니다.')
        observed.append({'text': text, 'begin': len(observed_text), 'stop': len(observed_text) + len(text),
                         'start': start, 'end': end, 'issues': issues})
        observed_text += text
    expected_text = ''.join(word['normalized'] for word in words)
    if observed_text != expected_text:
        raise ValueError('Qwen 정렬 결과가 입력 가사의 문자·순서·반복을 보존하지 않습니다.')
    # Exclude both sides of a conflict; never move, trim, or choose a preferred
    # timestamp. Recheck survivors because dropping a conflicting pair can expose
    # a wider inversion across that pair. Unrelated monotonic observations remain.
    while True:
        candidates = [unit for unit in observed if not unit['issues']]
        conflicts = [(left, right) for left, right in zip(candidates, candidates[1:])
                     if right['start'] < left['end']]
        if not conflicts:
            break
        for left, right in conflicts:
            for unit in (left, right):
                issue = 'Qwen 관측 시각이 다른 가사 단위와 겹치거나 원문 순서와 반대입니다.'
                if issue not in unit['issues']:
                    unit['issues'].append(issue)
    results = []
    position = 0
    for word in words:
        begin, stop = position, position + len(word['normalized'])
        position = stop
        units = [unit for unit in observed if unit['stop'] > begin and unit['begin'] < stop]
        reason = word.get('reason', '')
        exact_boundary = bool(word['normalized'] and units and units[0]['begin'] == begin
                              and units[-1]['stop'] == stop)
        issues = list(dict.fromkeys(issue for unit in units for issue in unit['issues']))
        supported = exact_boundary and not issues
        if word['normalized']:
            if not exact_boundary:
                issues.append('Qwen 관측 단위가 원문 단어 경계를 가로질러 시각을 확정할 수 없습니다.')
            if issues:
                reason = ' '.join(issues)
        results.append({**word, 'start': units[0]['start'] if supported else None,
                        'end': units[-1]['end'] if supported else None,
                        'p': None, 'chars': [], 'alignment_unit': 'word',
                        'score_unavailable': True, 'status': 'AUTO' if supported else 'UNKNOWN',
                        'reason': reason, 'observation_issues': issues,
                        'observed_units': [{key: unit[key] for key in ('text', 'start', 'end')}
                                           for unit in units] if supported else []})
    return results


def _write_observations(path, items, duration, language):
    """Keep official returned spans before our validation, without replacing them."""
    path = Path(path)
    work_root = Path(__file__).resolve().parents[2] / 'work'
    if path.resolve() != path.absolute() or not path.resolve().is_relative_to(work_root.resolve()):
        raise ValueError('Qwen 관측 원시 자료는 프로젝트 work 내부에 저장해야 합니다.')
    def json_number(value):
        # Preserve non-finite failures explicitly without non-standard JSON NaN.
        value = float(value)
        return value if math.isfinite(value) else repr(value)
    raw = [{'text': str(item.text), 'start_time': json_number(item.start_time),
            'end_time': json_number(item.end_time)} for item in items]
    with path.open('x', encoding='utf-8', newline='\n') as output:
        json.dump({'source': 'official-qwen-returned-items-before-project-validation',
                   'duration': duration, 'language': language, 'items': raw},
                  output, ensure_ascii=False, allow_nan=False, indent=2)


def align_qwen(audio, words, model_path, language, duration, progress, observations_path=None):
    if duration > MAX_AUDIO_SECONDS:
        raise ValueError('Qwen 정렬 모델은 한 번에 최대 300초 WAV를 지원합니다. 긴 곡은 MMS FA 또는 영어 Large를 선택하세요.')
    import torch
    try:
        from qwen_asr import Qwen3ForcedAligner
    except ImportError as error:
        raise RuntimeError('Qwen 모델에는 requirements.txt의 qwen-asr와 관련 패키지가 필요합니다.') from error

    text = ' '.join(word['normalized'] for word in words if word['normalized'])
    language_name = qwen_language(words, language)
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    torch.set_num_threads(min(8, max(1, torch.get_num_threads())))

    def compute(selected_device):
        aligner = None
        try:
            progress('Qwen3 ForcedAligner 0.6B 읽기 · ' + selected_device, 0.22)
            dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
                     ) if selected_device.startswith('cuda') else torch.float32
            aligner = Qwen3ForcedAligner.from_pretrained(
                str(model_path), dtype=dtype, device_map=selected_device,
                attn_implementation='sdpa', local_files_only=True)
            progress('Qwen 가사 발음 시각 관측 · ' + language_name, 0.4)
            with torch.inference_mode():
                results = aligner.align(audio=(audio, MODEL_RATE), text=text, language=language_name)
            if len(results) != 1:
                raise ValueError('Qwen 정렬의 오디오 결과 개수가 입력과 다릅니다.')
            if observations_path is not None:
                _write_observations(observations_path, results[0].items, duration, language_name)
            progress('Qwen 관측 단위를 원문 가사 순서와 대조', 0.9)
            return map_observations(words, results[0].items, duration), selected_device
        finally:
            del aligner
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    try:
        return compute(device)
    except torch.cuda.OutOfMemoryError:
        if device == 'cpu':
            raise
        progress('GPU 메모리가 부족하여 Qwen을 CPU로 다시 계산합니다.', 0.22)
        gc.collect()
        torch.cuda.empty_cache()
        return compute('cpu')
