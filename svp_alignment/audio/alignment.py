"""Own isolated acoustic worker lifetime, cancellation, and job-local result reuse."""

from copy import deepcopy
from hashlib import sha256
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from filelock import FileLock, Timeout

from .inference import CHUNK_FRAMES, CONTEXT_FRAMES
from .models import MODEL_CACHE, ROOT, cached_model, checked_cache, digest_file, get_model_status, model_digest
from .model_catalog import QWEN_MODEL, HEAVY_MODEL, WORD_OBSERVATION_MODELS
from .transcript import copy_words, normalize_words, select_model
from .waveform import FRAME_CENTER, FRAME_SAMPLES, MODEL_RATE, RECEPTIVE_SAMPLES


SETTINGS = {'algorithm_version': 2, 'sample_rate': MODEL_RATE, 'frame_samples': FRAME_SAMPLES,
            'receptive_samples': RECEPTIVE_SAMPLES, 'frame_center': FRAME_CENTER,
            'chunk_frames': CHUNK_FRAMES, 'context_frames': CONTEXT_FRAMES,
            'normalization': 'ctc-uroman-or-ascii-or-qwen-unicode-v2',
            'qwen_observation_mapping': 'exact-units-invalid-spans-unknown-no-interpolation-v2'}


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _checkpoint(cancelled):
    if cancelled is not None and cancelled():
        raise InterruptedError('음성 정렬 작업이 취소됐습니다.')


def _workspace(value):
    workspace = Path(value).absolute()
    resolved = workspace.resolve()
    work_root = (ROOT / 'work').resolve()
    if (not resolved.is_relative_to(work_root) or resolved == work_root or
            resolved != workspace or (resolved / 'audio').resolve() != resolved / 'audio'):
        raise ValueError('음성 계산 자료는 프로젝트 work의 개별 작업 폴더에 저장해야 합니다.')
    folder = resolved / 'audio'
    folder.mkdir(parents=True, exist_ok=True)
    return folder



def _worker_command(request_path):
    if os.name != 'nt':
        return [sys.executable, '-B', '-X', 'utf8', '-u', '-m',
                'svp_alignment.audio.worker', str(request_path)]
    # Windows venv python.exe is a redirector which can otherwise leave its
    # actual interpreter child alive when terminated. Run the real interpreter
    # directly, ignoring environment/user/base-site packages, then add only this
    # project's code and the current venv's installed packages explicitly.
    interpreter = getattr(sys, '_base_executable', sys.executable)
    site_packages = Path(sys.prefix) / 'Lib' / 'site-packages'
    bootstrap = (
        'import sys,site,runpy;'
        'sys.prefix=sys.exec_prefix=' + repr(sys.prefix) + ';'
        'site.ENABLE_USER_SITE=False;'
        'sys.path.insert(0,' + repr(str(ROOT)) + ');'
        'site.addsitedir(' + repr(str(site_packages)) + ');'
        'sys.argv=["svp_alignment.audio.worker",' + repr(str(request_path)) + '];'
        'runpy.run_module("svp_alignment.audio.worker",run_name="__main__")'
    )
    return [interpreter, '-I', '-S', '-B', '-X', 'utf8', '-u', '-c', bootstrap]


def _terminate(worker):
    if worker.poll() is None:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
    else:
        worker.wait()


def _progress_events(path, consumed, progress):
    lines = path.read_bytes().splitlines(keepends=True)
    for line in lines[consumed:]:
        if not line.endswith(b'\n'):
            break
        try:
            event = json.loads(line)
        except (ValueError, UnicodeError):
            consumed += 1
            continue
        if progress is not None and 'label' in event and 'fraction' in event:
            progress(event['label'], min(1.0, max(0.0, float(event['fraction']))))
        consumed += 1
    return consumed


def _validate_result(result, signature, words, model_id=None):
    if result.get('signature') != signature or len(result.get('words', [])) != len(words):
        raise ValueError('음성 정렬 자료가 현재 입력과 일치하지 않습니다.')
    if result['provenance'].get('request_signature') != signature:
        raise ValueError('음성 정렬 관측 근거의 입력 서명이 일치하지 않습니다.')
    if model_id is not None and result['provenance'].get('model_id') != model_id:
        raise ValueError('음성 정렬 자료의 모델이 선택한 모델과 다릅니다.')
    duration = float(result['provenance']['audio']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('음성 정렬 자료의 WAV 길이가 올바르지 않습니다.')
    previous = 0.0
    for actual, expected in zip(result['words'], words):
        if any(actual.get(key) != expected.get(key) for key in ('source', 'word_index', 'normalized')):
            raise ValueError('음성 정렬 자료의 가사 순서 또는 원문이 변경됐습니다.')
        chars = actual.get('chars', [])
        word_observations = result['provenance'].get('model_id') in WORD_OBSERVATION_MODELS
        if word_observations and (chars or actual.get('alignment_unit') != 'word'
                                  or actual.get('p') is not None or actual.get('score_unavailable') is not True):
            raise ValueError('Qwen 단어 관측에 생성한 문자 시각이나 신뢰도를 사용할 수 없습니다.')
        if not expected['normalized']:
            if (actual.get('start') is not None or actual.get('end') is not None or chars
                    or (word_observations and actual.get('observed_units'))):
                raise ValueError('미지원 가사에 추측한 정렬 시각을 사용할 수 없습니다.')
            continue
        if word_observations:
            if actual.get('start') is None and actual.get('end') is None and actual.get('status') == 'UNKNOWN':
                if actual.get('observed_units'):
                    raise ValueError('미확정 단어에 확정된 관측 단위를 사용할 수 없습니다.')
                continue
            start, end = float(actual['start']), float(actual['end'])
            if not all(math.isfinite(value) for value in (start, end)) or not previous <= start < end <= duration:
                raise ValueError('Qwen 단어 관측의 시각 또는 순서가 올바르지 않습니다.')
            units = actual.get('observed_units', [])
            if ''.join(unit['text'] for unit in units) != expected['normalized']:
                raise ValueError('Qwen 관측 단위와 원문 단어가 일치하지 않습니다.')
            if not units or start != units[0]['start'] or end != units[-1]['end']:
                raise ValueError('Qwen 단어 범위가 실제 관측 단위와 다릅니다.')
            unit_previous = start
            for unit in units:
                unit_start, unit_end = float(unit['start']), float(unit['end'])
                if not all(math.isfinite(value) for value in (unit_start, unit_end)) or not unit_previous <= unit_start < unit_end <= end:
                    raise ValueError('Qwen 관측 단위의 시각이 올바르지 않습니다.')
                unit_previous = unit_end
            previous = end
            continue
        if ''.join(char['char'] for char in chars) != expected['normalized']:
            raise ValueError('음성 정렬 자료의 문자 대응이 변경됐습니다.')
        for char in chars:
            start, end, probability = float(char['start']), float(char['end']), float(char['p'])
            if not (previous <= start < end <= duration and 0 <= probability <= 1):
                raise ValueError('음성 정렬 자료의 시각 또는 신뢰도가 올바르지 않습니다.')
            previous = end
        if actual['start'] != chars[0]['start'] or actual['end'] != chars[-1]['end']:
            raise ValueError('음성 정렬 단어 범위가 문자 범위와 다릅니다.')
    return result


def _validate_heavy_evidence(result, folder):
    """The larger backend's recognized text must survive cache reuse unchanged."""
    from .heavy_bundle import component_specs

    provenance = result['provenance']
    if provenance.get('model_components') != component_specs():
        raise ValueError('인식·정렬 모델 스냅샷 근거가 현재 선택과 다릅니다.')
    raw = Path(provenance.get('raw_observations_path', ''))
    resolved = raw.resolve(strict=True)
    if (raw.absolute() != resolved or raw.is_symlink() or not resolved.is_file()
            or not resolved.is_relative_to(folder.resolve())
            or resolved.name != 'asr-observations.json'
            or resolved.parent.parent != folder.resolve()
            or not resolved.parent.name.startswith('attempt-')):
        raise ValueError('음성 인식 원시 자료는 해당 작업의 관측 폴더에 있어야 합니다.')
    if digest_file(resolved) != provenance.get('raw_observations_sha256'):
        raise ValueError('음성 인식 원시 자료가 저장한 해시와 다릅니다.')


def align_words(wav_path, words, workspace, progress=None, cancelled=None, language='auto', model_choice='auto'):
    """Return (original-order word/character candidates, input/model provenance).

    A separate process owns model tensors and CUDA memory. A cross-process lock
    serializes workers until they have exited, including cancellation cleanup.
    Cached results can only be reused inside this job and for identical inputs.
    """
    _checkpoint(cancelled)
    wav_path = Path(wav_path).resolve(strict=True)
    originals = copy_words(words)
    model_id = select_model(originals, language, model_choice)
    normalized = normalize_words(originals, model_id, language)
    folder = _workspace(workspace)
    versions = {'torch': version('torch'), 'torchaudio': version('torchaudio')}
    if model_id == 'MMS_FA':
        versions['uroman'] = version('uroman')
    if model_id in WORD_OBSERVATION_MODELS:
        for dependency in ('qwen-asr', 'transformers', 'nagisa', 'soynlp', 'accelerate'):
            versions[dependency] = version(dependency)
    wav_hash = digest_file(wav_path)
    text_hash = sha256(_json_bytes(originals)).hexdigest()
    settings = SETTINGS
    components = None
    if model_id == HEAVY_MODEL:
        from .heavy_bundle import component_specs
        from .asr_inference import ASR_MAX_NEW_TOKENS
        from .asr_reference import RECOGNITION_POLICY
        components = component_specs()
        settings = {**SETTINGS, 'recognition_mapping': RECOGNITION_POLICY,
                    'recognition_decoding': {'max_new_tokens': ASR_MAX_NEW_TOKENS,
                                             'max_inference_batch_size': 1, 'timestamps': True}}
    base = {'wav_sha256': wav_hash, 'text_sha256': text_hash, 'words': normalized,
            'model_id': model_id, 'model_choice': model_choice, 'language': language,
            'settings': settings, 'versions': versions}
    if components is not None:
        base['model_components'] = components
    signature = sha256(_json_bytes(base)).hexdigest()
    cached_weights = cached_model(model_id)
    weights_hash = model_digest(cached_weights) if cached_weights is not None else None
    cache = folder / 'result.json'
    if cache.is_file() and not cache.is_symlink() and weights_hash:
        try:
            result = _validate_result(json.loads(cache.read_text(encoding='utf-8')), signature, normalized, model_id)
            if model_id == HEAVY_MODEL:
                _validate_heavy_evidence(result, folder)
            if result['provenance']['model_sha256'] == weights_hash:
                _checkpoint(cancelled)
                if digest_file(wav_path) != wav_hash:
                    raise ValueError('WAV가 캐시 검사 중 변경됐습니다.')
                provenance = {**result['provenance'], 'cache_reused': True}
                if progress is not None:
                    progress('동일 작업의 입력·모델 해시가 같은 음성 관측 자료 재사용', 1.0)
                return deepcopy(result['words']), provenance
        except (ValueError, KeyError, TypeError, OSError):
            # Unusable job-local cache is never treated as current evidence.
            pass
    _checkpoint(cancelled)
    checked_cache().mkdir(parents=True, exist_ok=True)
    lock_path = MODEL_CACHE.parent / '.alignment.lock'
    if lock_path.resolve() != lock_path.absolute():
        raise ValueError('음성 정렬 잠금에 링크 경로를 사용할 수 없습니다.')
    lock = FileLock(str(lock_path))
    if progress is not None:
        progress('다른 음성 정렬 작업 종료 대기', 0.0)
    while True:
        _checkpoint(cancelled)
        try:
            lock.acquire(timeout=0.1)
            break
        except Timeout:
            continue
    worker = None
    run_id = uuid.uuid4().hex
    attempt = folder / ('attempt-' + run_id)
    try:
        _checkpoint(cancelled)
        attempt.mkdir(exist_ok=False)
        request = {**base, 'signature': signature, 'wav_path': str(wav_path),
                   'run_id': run_id, 'model_sha256': weights_hash}
        request_path = attempt / 'request.json'
        request_path.write_bytes(_json_bytes(request))
        log_path = attempt / 'progress.jsonl'
        error_log = attempt / 'stderr.log'
        with log_path.open('xb') as output, error_log.open('xb') as errors:
            environment = os.environ.copy()
            environment['PYTHONDONTWRITEBYTECODE'] = '1'
            worker = subprocess.Popen(
                _worker_command(request_path),
                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            (attempt / 'process.json').write_text(json.dumps({'pid': worker.pid}), encoding='utf-8')
            consumed = 0
            while worker.poll() is None:
                _checkpoint(cancelled)
                consumed = _progress_events(log_path, consumed, progress)
                time.sleep(0.1)
            worker.wait()
            _checkpoint(cancelled)
            _progress_events(log_path, consumed, progress)
        if worker.returncode:
            error_file = attempt / 'error.json'
            detail = (json.loads(error_file.read_text(encoding='utf-8')).get('error') if error_file.is_file()
                      else error_log.read_text(encoding='utf-8', errors='replace')[-3000:])
            raise RuntimeError('음성 정렬을 완료하지 못했습니다: ' + str(detail))
        result = _validate_result(json.loads((attempt / 'result.json').read_text(encoding='utf-8')),
                                  signature, normalized, model_id)
        if model_id == HEAVY_MODEL:
            _validate_heavy_evidence(result, folder)
        if digest_file(wav_path) != wav_hash:
            raise ValueError('WAV가 음성 정렬 중 변경됐습니다.')
        scratch = folder / ('.result-' + run_id + '.json')
        try:
            with scratch.open('xb') as stream:
                stream.write(_json_bytes(result))
                stream.flush()
                os.fsync(stream.fileno())
            scratch.replace(cache)
        finally:
            scratch.unlink(missing_ok=True)
        return deepcopy(result['words']), deepcopy(result['provenance'])
    finally:
        if worker is not None:
            _terminate(worker)
        try:
            # Only the exact download scratch belonging to this exited worker is ours.
            (checked_cache() / ('.download-' + run_id)).unlink(missing_ok=True)
            if model_id == HEAVY_MODEL:
                from .heavy_bundle import cleanup_heavy_download
                cleanup_heavy_download(run_id)
            elif model_id == QWEN_MODEL:
                from .qwen_cache import cleanup_qwen_download
                cleanup_qwen_download(run_id)
        finally:
            lock.release()
