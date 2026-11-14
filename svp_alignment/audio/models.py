"""Locate and atomically download immutable public acoustic model weights."""

import os
from pathlib import Path
import urllib.request

from .model_catalog import ENGLISH_MODEL, LARGE_ENGLISH_MODEL, MULTILINGUAL_MODEL, QWEN_MODEL, HEAVY_MODEL
from .model_fingerprint import digest_file


ROOT = Path(__file__).resolve().parents[2]
MODEL_CACHE = ROOT / 'work' / 'models' / 'torchaudio'
MODELS = {
    ENGLISH_MODEL: {
        'filename': 'wav2vec2_fairseq_base_ls960_asr_ls960.pth',
        'url': 'https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_base_ls960_asr_ls960.pth',
    },
    LARGE_ENGLISH_MODEL: {
        'filename': 'wav2vec2_fairseq_large_lv60k_asr_ls960.pth',
        'url': 'https://download.pytorch.org/torchaudio/models/wav2vec2_fairseq_large_lv60k_asr_ls960.pth',
    },
    MULTILINGUAL_MODEL: {
        'filename': 'model.pt',
        'url': 'https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt',
    },
}


def checked_cache():
    resolved = MODEL_CACHE.resolve()
    if not resolved.is_relative_to(ROOT) or resolved != MODEL_CACHE.absolute():
        raise ValueError('모델 캐시가 프로젝트 밖 또는 링크 경로를 가리킵니다.')
    return resolved


def cached_model(model_id):
    if model_id == HEAVY_MODEL:
        from .heavy_bundle import cached_heavy
        return cached_heavy()
    if model_id == QWEN_MODEL:
        from .qwen_cache import cached_qwen
        return cached_qwen()
    specification = MODELS[model_id]
    torch_home = Path(os.environ.get('TORCH_HOME', Path.home() / '.cache' / 'torch'))
    candidates = (checked_cache() / specification['filename'],
                  torch_home / 'hub' / 'checkpoints' / specification['filename'],
                  ROOT / 'work' / 'acoustic' / 'torch' / 'hub' / 'checkpoints' / specification['filename'])
    return next((path.resolve() for path in candidates if path.is_file() and path.stat().st_size), None)


def get_model_status(model_id=ENGLISH_MODEL):
    if model_id == HEAVY_MODEL:
        from .heavy_bundle import heavy_status
        return heavy_status()
    if model_id == QWEN_MODEL:
        from .qwen_cache import cached_qwen, QWEN_FILES, QWEN_REVISION
        path = cached_qwen()
        return {'model_id': model_id, 'cached': path is not None,
                'path': str(path) if path is not None else None,
                'bytes': sum((path / name).stat().st_size for name in QWEN_FILES) if path else None,
                'revision': QWEN_REVISION, 'url': 'https://huggingface.co/' + QWEN_MODEL}
    if model_id not in MODELS:
        raise ValueError('지원하지 않는 음성 정렬 모델입니다.')
    path = cached_model(model_id)
    return {'model_id': model_id, 'cached': path is not None,
            'path': str(path) if path is not None else None,
            'bytes': path.stat().st_size if path is not None else None,
            'url': MODELS[model_id]['url']}


def _download_model(model_id, run_id, progress=None):
    """Download only when no existing supported cache contains these weights."""
    existing = cached_model(model_id)
    if existing is not None:
        return existing
    folder = checked_cache()
    folder.mkdir(parents=True, exist_ok=True)
    specification = MODELS[model_id]
    target = folder / specification['filename']
    temporary = folder / ('.download-' + run_id)
    try:
        with urllib.request.urlopen(specification['url'], timeout=60) as source, temporary.open('xb') as output:
            total = int(source.headers.get('Content-Length') or 0)
            received = 0
            while block := source.read(1024 * 1024):
                output.write(block)
                received += len(block)
                if progress is not None:
                    progress(f'음성 정렬 모델 다운로드 {received // (1024 * 1024)} MB',
                             0.1 + 0.1 * received / total if total else 0.1)
            output.flush()
            os.fsync(output.fileno())
        if total and received != total:
            raise ValueError('모델 다운로드가 완료되기 전에 연결이 종료됐습니다.')
        if target.exists():
            if digest_file(target) != digest_file(temporary):
                raise ValueError('동시에 저장된 모델 가중치가 다운로드 내용과 다릅니다.')
        else:
            temporary.rename(target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def ensure_model(model_id, run_id, progress=None):
    """Serialize publication of each model across workers or application instances."""
    from filelock import FileLock

    if model_id == HEAVY_MODEL:
        from .heavy_bundle import ensure_heavy
        return ensure_heavy(run_id, progress)
    if model_id == QWEN_MODEL:
        from .qwen_cache import ensure_qwen
        return ensure_qwen(run_id, progress)
    if model_id not in MODELS:
        raise ValueError('지원하지 않는 음성 정렬 모델입니다.')
    existing = cached_model(model_id)
    if existing is not None:
        return existing
    folder = checked_cache()
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / ('.model-' + model_id + '.lock')
    if lock_path.resolve() != lock_path.absolute():
        raise ValueError('모델 다운로드 잠금에 링크 경로를 사용할 수 없습니다.')
    with FileLock(str(lock_path)):
        return _download_model(model_id, run_id, progress)


def model_digest(path):
    """Fingerprint the complete backend model artifact, including its configuration."""
    if isinstance(path, dict):
        from .heavy_bundle import heavy_digest
        return heavy_digest(path)
    if Path(path).is_dir():
        from .qwen_cache import qwen_digest
        return qwen_digest(path)
    return digest_file(path)
