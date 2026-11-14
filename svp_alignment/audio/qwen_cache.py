"""Pinned Qwen public model snapshot, published atomically inside the project."""

import json
import os
from pathlib import Path
import re
import urllib.request

from .model_catalog import QWEN_MODEL
from .model_fingerprint import digest_file

QWEN_REVISION = '1c85775dfe71a2a90e6aeea682c6eb9df3d8848b'
QWEN_FILES = ('config.json', 'generation_config.json', 'preprocessor_config.json',
              'tokenizer_config.json', 'chat_template.json', 'merges.txt', 'vocab.json',
              'model.safetensors')
QWEN_WEIGHTS_SHA256 = '47831d0e82f96b20e9034dba01a075ee06436654719f6a68289e49f1b65ce0e7'
ROOT = Path(__file__).resolve().parents[2]
QWEN_CACHE = ROOT / 'work' / 'models' / 'qwen' / QWEN_REVISION


def _checked_folder():
    folder = QWEN_CACHE.resolve()
    if folder != QWEN_CACHE.absolute() or not folder.is_relative_to(ROOT):
        raise ValueError('Qwen 모델 캐시가 프로젝트 밖 또는 링크 경로를 가리킵니다.')
    return folder


def cached_qwen():
    folder = _checked_folder()
    if all((folder / name).is_file() and not (folder / name).is_symlink()
           and (folder / name).stat().st_size for name in (*QWEN_FILES, 'snapshot.json')):
        return folder
    return None


def qwen_digest(folder):
    from hashlib import sha256

    folder = Path(folder)
    hashes = {name: digest_file(folder / name) for name in QWEN_FILES}
    if hashes['model.safetensors'] != QWEN_WEIGHTS_SHA256:
        raise ValueError('Qwen 모델 가중치가 고정한 공개 SHA256과 다릅니다.')
    manifest = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    if manifest != {'model_id': QWEN_MODEL, 'revision': QWEN_REVISION, 'files': hashes}:
        raise ValueError('Qwen 모델 파일이 고정한 스냅샷 기록과 다릅니다.')
    return sha256(json.dumps(manifest, sort_keys=True).encode('utf-8')).hexdigest()


def cleanup_qwen_download(run_id):
    """Remove only this worker's known scratch files after the worker has exited."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(run_id)):
        raise ValueError('모델 다운로드 작업 식별자가 올바르지 않습니다.')
    staging = _checked_folder().parent / ('.download-' + str(run_id))
    if staging.resolve() != staging.absolute():
        raise ValueError('Qwen 다운로드 정리에 링크 경로를 사용할 수 없습니다.')
    if staging.is_dir():
        for name in (*QWEN_FILES, 'snapshot.json'):
            candidate = staging / name
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
        # Unknown contents are never ours to remove.
        if not any(staging.iterdir()):
            staging.rmdir()


def ensure_qwen(run_id, progress=None):
    from filelock import FileLock

    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(run_id)):
        raise ValueError('모델 다운로드 작업 식별자가 올바르지 않습니다.')
    existing = cached_qwen()
    if existing is not None:
        qwen_digest(existing)
        return existing
    target = _checked_folder()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / ('.model-' + QWEN_REVISION + '.lock')
    if lock_path.resolve() != lock_path.absolute():
        raise ValueError('Qwen 모델 다운로드 잠금에 링크 경로를 사용할 수 없습니다.')
    with FileLock(str(lock_path)):
        existing = cached_qwen()
        if existing is not None:
            qwen_digest(existing)
            return existing
        if target.exists():
            raise ValueError('미완성 Qwen 모델 폴더가 있습니다. 기존 파일을 덮어쓰지 않습니다.')
        staging = target.parent / ('.download-' + str(run_id))
        if staging.resolve() != staging.absolute():
            raise ValueError('Qwen 다운로드에 링크 경로를 사용할 수 없습니다.')
        staging.mkdir(exist_ok=False)
        hashes = {}
        try:
            for index, name in enumerate(QWEN_FILES):
                url = f'https://huggingface.co/{QWEN_MODEL}/resolve/{QWEN_REVISION}/{name}'
                with urllib.request.urlopen(url, timeout=60) as source, (staging / name).open('xb') as output:
                    total = int(source.headers.get('Content-Length') or 0)
                    received = 0
                    while block := source.read(1024 * 1024):
                        output.write(block)
                        received += len(block)
                        if progress is not None:
                            progress(f'Qwen 모델 다운로드 · {name} · {received // (1024 * 1024)} MB',
                                     0.1 + 0.1 * (index + (received / total if total else 0)) / len(QWEN_FILES))
                    output.flush()
                    os.fsync(output.fileno())
                if not received or (total and received != total):
                    raise ValueError('Qwen 모델 다운로드가 완료되기 전에 연결이 종료됐습니다.')
                hashes[name] = digest_file(staging / name)
            manifest = {'model_id': QWEN_MODEL, 'revision': QWEN_REVISION, 'files': hashes}
            (staging / 'snapshot.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
            qwen_digest(staging)
            staging.rename(target)
            return target
        finally:
            # A cancelled worker may leave staging evidence; completed/failed calls
            # remove only files this exact attempt created, never existing snapshots.
            cleanup_qwen_download(run_id)
