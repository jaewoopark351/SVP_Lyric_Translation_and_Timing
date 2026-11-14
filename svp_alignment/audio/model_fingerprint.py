"""Stream immutable model artifacts into byte-exact SHA256 fingerprints."""

import hashlib
from pathlib import Path


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
