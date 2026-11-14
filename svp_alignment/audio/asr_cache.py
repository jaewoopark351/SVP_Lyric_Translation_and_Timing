"""Atomically publish the pinned Qwen3 ASR snapshot inside the project."""

import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request

ASR_MODEL = 'Qwen/Qwen3-ASR-1.7B'
ASR_REVISION = '7278e1e70fe206f11671096ffdd38061171dd6e5'
ASR_WEIGHTS_SHA256 = {
    'model-00001-of-00002.safetensors': 'a4cd1f1a04d90b757dc7f7dd26254e69a013b19e80efe590a83c6a3bde8608d6',
    'model-00002-of-00002.safetensors': '6e0b9d9e09e2e0238e7ef3cc8a484ab387e91b90f1900bedf88bc92d7929ccfc',
}
ASR_FILES = ('config.json', 'generation_config.json', 'preprocessor_config.json',
             'tokenizer_config.json', 'chat_template.json', 'merges.txt', 'vocab.json',
             'model.safetensors.index.json', *ASR_WEIGHTS_SHA256)
ROOT = Path(__file__).resolve().parents[2]
ASR_CACHE = ROOT / 'work' / 'models' / 'qwen-asr' / ASR_REVISION


def _digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _checked_folder():
    folder = ASR_CACHE.resolve()
    if folder != ASR_CACHE.absolute() or not folder.is_relative_to(ROOT.resolve()):
        raise ValueError('Qwen ASR 모델 캐시가 프로젝트 밖 또는 링크 경로를 가리킵니다.')
    return folder


def _run_id(run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', str(run_id)):
        raise ValueError('모델 다운로드 작업 식별자가 올바르지 않습니다.')
    return str(run_id)


def cached_asr():
    folder = _checked_folder()
    if all((folder / name).is_file() and not (folder / name).is_symlink()
           and (folder / name).stat().st_size for name in (*ASR_FILES, 'snapshot.json')):
        return folder
    return None


def asr_digest(folder):
    """Validate both weight shards and the complete published snapshot manifest."""
    folder = Path(folder)
    if folder.resolve() != folder.absolute() or not folder.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Qwen ASR 모델 검증에 프로젝트 밖 또는 링크 경로를 사용할 수 없습니다.')
    if not all((folder / name).is_file() and not (folder / name).is_symlink()
               and (folder / name).stat().st_size for name in (*ASR_FILES, 'snapshot.json')):
        raise ValueError('Qwen ASR 모델 스냅샷 파일이 없거나 비어 있습니다.')
    hashes = {name: _digest_file(folder / name) for name in ASR_FILES}
    if any(hashes[name] != expected for name, expected in ASR_WEIGHTS_SHA256.items()):
        raise ValueError('Qwen ASR 모델 가중치가 고정한 공개 SHA256과 다릅니다.')
    manifest = json.loads((folder / 'snapshot.json').read_text(encoding='utf-8'))
    if manifest != {'model_id': ASR_MODEL, 'revision': ASR_REVISION, 'files': hashes}:
        raise ValueError('Qwen ASR 모델 파일이 고정한 스냅샷 기록과 다릅니다.')
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode('utf-8')).hexdigest()


def cleanup_asr_download(run_id):
    """Remove only known files owned by this exact exited download attempt."""
    staging = _checked_folder().parent / ('.download-' + _run_id(run_id))
    if staging.resolve() != staging.absolute():
        raise ValueError('Qwen ASR 다운로드 정리에 링크 경로를 사용할 수 없습니다.')
    if staging.is_dir():
        for name in (*ASR_FILES, 'snapshot.json'):
            candidate = staging / name
            if candidate.is_file() and not candidate.is_symlink():
                candidate.unlink()
        if not any(staging.iterdir()):
            staging.rmdir()


def ensure_asr(run_id, progress=None):
    from filelock import FileLock

    run_id = _run_id(run_id)
    existing = cached_asr()
    if existing is not None:
        asr_digest(existing)
        return existing
    target = _checked_folder()
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / ('.model-' + ASR_REVISION + '.lock')
    if lock_path.resolve() != lock_path.absolute():
        raise ValueError('Qwen ASR 다운로드 잠금에 링크 경로를 사용할 수 없습니다.')
    with FileLock(str(lock_path)):
        existing = cached_asr()
        if existing is not None:
            asr_digest(existing)
            return existing
        if target.exists():
            raise ValueError('미완성 Qwen ASR 모델 폴더가 있습니다. 기존 파일을 덮어쓰지 않습니다.')
        staging = target.parent / ('.download-' + run_id)
        if staging.resolve() != staging.absolute():
            raise ValueError('Qwen ASR 다운로드에 링크 경로를 사용할 수 없습니다.')
        staging.mkdir(exist_ok=False)
        try:
            hashes = {}
            for index, name in enumerate(ASR_FILES):
                url = f'https://huggingface.co/{ASR_MODEL}/resolve/{ASR_REVISION}/{name}'
                with urllib.request.urlopen(url, timeout=60) as source, (staging / name).open('xb') as output:
                    total = int(source.headers.get('Content-Length') or 0)
                    received = 0
                    while block := source.read(1024 * 1024):
                        output.write(block)
                        received += len(block)
                        if progress is not None:
                            fraction = received / total if total else 0
                            progress(f'Qwen ASR 모델 다운로드 · {name} · {received // (1024 * 1024)} MB',
                                     0.1 + 0.1 * (index + fraction) / len(ASR_FILES))
                    output.flush()
                    os.fsync(output.fileno())
                if not received or (total and received != total):
                    raise ValueError('Qwen ASR 모델 다운로드가 완료되기 전에 연결이 종료됐습니다.')
                hashes[name] = _digest_file(staging / name)
            manifest = {'model_id': ASR_MODEL, 'revision': ASR_REVISION, 'files': hashes}
            with (staging / 'snapshot.json').open('x', encoding='utf-8') as output:
                json.dump(manifest, output, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            asr_digest(staging)
            staging.rename(target)
            return target
        finally:
            cleanup_asr_download(run_id)
