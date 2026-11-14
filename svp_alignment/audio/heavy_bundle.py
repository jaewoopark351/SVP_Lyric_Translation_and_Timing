"""Bind the two immutable snapshots used by recognition-assisted alignment."""

from hashlib import sha256
import json
from pathlib import Path

from .model_catalog import HEAVY_MODEL, QWEN_MODEL


def component_specs():
    """Pinned identities also enter the request signature before downloading."""
    from .asr_cache import ASR_MODEL, ASR_REVISION, ASR_WEIGHTS_SHA256
    from .qwen_cache import QWEN_REVISION, QWEN_WEIGHTS_SHA256

    return {
        'asr': {'model_id': ASR_MODEL, 'revision': ASR_REVISION,
                'weights_sha256': dict(ASR_WEIGHTS_SHA256)},
        'aligner': {'model_id': QWEN_MODEL, 'revision': QWEN_REVISION,
                    'weights_sha256': QWEN_WEIGHTS_SHA256},
    }


def cached_heavy():
    from .asr_cache import cached_asr
    from .qwen_cache import cached_qwen

    asr, aligner = cached_asr(), cached_qwen()
    return {'asr': asr, 'aligner': aligner} if asr is not None and aligner is not None else None


def ensure_heavy(run_id, progress=None):
    from .asr_cache import ensure_asr
    from .qwen_cache import ensure_qwen

    return {'asr': ensure_asr(run_id, progress), 'aligner': ensure_qwen(run_id, progress)}


def heavy_digest(bundle):
    """Hash both complete configurations and weights, never just the ASR file."""
    from .asr_cache import asr_digest
    from .qwen_cache import qwen_digest

    if not isinstance(bundle, dict) or set(bundle) != {'asr', 'aligner'}:
        raise ValueError('ASR와 정렬 모델의 두 스냅샷이 모두 필요합니다.')
    components = component_specs()
    components['asr']['snapshot_sha256'] = asr_digest(Path(bundle['asr']))
    components['aligner']['snapshot_sha256'] = qwen_digest(Path(bundle['aligner']))
    manifest = {'model_id': HEAVY_MODEL, 'components': components}
    return sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def heavy_status():
    from .asr_cache import ASR_FILES
    from .qwen_cache import QWEN_FILES

    bundle = cached_heavy()
    return {'model_id': HEAVY_MODEL, 'cached': bundle is not None,
            'path': {name: str(path) for name, path in bundle.items()} if bundle else None,
            'bytes': (sum((bundle['asr'] / name).stat().st_size for name in ASR_FILES)
                      + sum((bundle['aligner'] / name).stat().st_size for name in QWEN_FILES)) if bundle else None,
            'components': component_specs(), 'url': 'https://huggingface.co/Qwen/Qwen3-ASR-1.7B'}


def cleanup_heavy_download(run_id):
    from .asr_cache import cleanup_asr_download
    from .qwen_cache import cleanup_qwen_download

    try:
        cleanup_asr_download(run_id)
    finally:
        cleanup_qwen_download(run_id)
