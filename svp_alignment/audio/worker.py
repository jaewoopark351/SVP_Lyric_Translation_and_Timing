"""Isolated acoustic worker: model/GPU lifetime ends with this process."""

import json
import os
from pathlib import Path
import sys
import traceback

from .inference import CONTEXT_FRAMES, CHUNK_FRAMES, decode_words, infer_emissions
from .models import digest_file, ensure_model, model_digest
from .model_catalog import QWEN_MODEL, HEAVY_MODEL
from .waveform import FRAME_CENTER, FRAME_SAMPLES, MODEL_RATE, RECEPTIVE_SAMPLES, load_waveform


def main(request_path):
    request_path = Path(request_path).resolve(strict=True)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    folder = request_path.parent
    (folder / 'runtime.json').write_text(json.dumps({
        'pid': os.getpid(), 'parent_pid': os.getppid(),
        'python_executable': sys.executable, 'python_prefix': sys.prefix,
        'sys_path': sys.path,
    }, ensure_ascii=False), encoding='utf-8')
    def progress(label, fraction):
        print(json.dumps({'label': label, 'fraction': fraction}, ensure_ascii=False), flush=True)
    try:
        progress('WAV 읽기 및 16 kHz 모노 변환', 0.05)
        if digest_file(request['wav_path']) != request['wav_sha256']:
            raise ValueError('계산 시작 전에 WAV가 변경됐습니다.')
        audio, metadata = load_waveform(request['wav_path'])
        progress('음성 정렬 모델 캐시 확인', 0.1)
        model_path = ensure_model(request['model_id'], request['run_id'], progress)
        model_hash = model_digest(model_path)
        if request.get('model_sha256') and model_hash != request['model_sha256']:
            raise ValueError('검사한 모델 가중치가 변경됐습니다.')
        recognition = None
        if request['model_id'] == HEAVY_MODEL:
            from .asr_inference import align_asr
            words, device, recognition = align_asr(
                audio, request['words'], model_path['asr'], model_path['aligner'],
                request['language'], metadata['duration'], progress,
                observations_path=folder / 'asr-observations.json')
        elif request['model_id'] == QWEN_MODEL:
            from .qwen_inference import align_qwen
            words, device = align_qwen(audio, request['words'], model_path, request['language'],
                                      metadata['duration'], progress,
                                      observations_path=folder / 'qwen-observations.json')
        else:
            posterior, labels, device = infer_emissions(audio, request['model_id'], model_path, progress)
            progress('관측된 음성과 가사 문자 정렬', 0.9)
            words = decode_words(posterior, labels, request['words'], request['model_id'], metadata['duration'])
        if model_digest(model_path) != model_hash:
            raise ValueError('음성 모델 가중치가 계산 중 변경됐습니다.')
        if digest_file(request['wav_path']) != request['wav_sha256']:
            raise ValueError('음성 계산 중 WAV가 변경됐습니다.')
        provenance = {
            'method': ('QWEN_ASR_REFERENCE_ALIGNMENT' if request['model_id'] == HEAVY_MODEL else
                       'QWEN_FORCED_ALIGNMENT' if request['model_id'] == QWEN_MODEL else 'CTC_FORCED_ALIGNMENT'),
            'model_id': request['model_id'], 'model_choice': request.get('model_choice', request['model_id']),
            'model_sha256': model_hash, 'wav_sha256': request['wav_sha256'],
            'text_sha256': request['text_sha256'], 'request_signature': request['signature'],
            'language': request['language'], 'versions': request['versions'],
            'settings': request['settings'], 'audio': metadata, 'device': device,
            'cache_reused': False, 'listening': 'NOT_RUN', 'overall': 'NOT_VERIFIED',
            'word_count': len(words), 'unsupported_words': sum(word.get('start') is None for word in words),
        }
        if request['model_id'] == HEAVY_MODEL:
            from .heavy_bundle import component_specs
            provenance.update(model_components=component_specs(), alignment_unit='word',
                              score_unavailable=True, recognition=recognition,
                              timestamp_postprocessing='official-qwen-monotonic-fix; exact-recognition-reference-unknown-only',
                              raw_observations_path=str(folder / 'asr-observations.json'),
                              raw_observations_sha256=digest_file(folder / 'asr-observations.json'))
        elif request['model_id'] == QWEN_MODEL:
            from .qwen_cache import QWEN_REVISION, QWEN_WEIGHTS_SHA256
            provenance.update(model_revision=QWEN_REVISION, weights_sha256=QWEN_WEIGHTS_SHA256,
                              alignment_unit='word', score_unavailable=True,
                              timestamp_postprocessing='official-qwen-monotonic-fix; project-invalid-spans-unknown-only',
                              raw_observations_path=str(folder / 'qwen-observations.json'),
                              raw_observations_sha256=digest_file(folder / 'qwen-observations.json'))
        result = {'signature': request['signature'], 'words': words, 'provenance': provenance}
        with (folder / 'result.json').open('x', encoding='utf-8', newline='\n') as output:
            json.dump(result, output, ensure_ascii=False, allow_nan=False, indent=2)
        progress('새 음성 정렬 관측 완료 · 자동 후보 검토 필요', 1.0)
    except BaseException as error:
        (folder / 'error.json').write_text(json.dumps({'error': str(error)}, ensure_ascii=False), encoding='utf-8')
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
