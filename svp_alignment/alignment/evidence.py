"""Read and fingerprint the existing, immutable acoustic observation files."""

import csv
import json
from pathlib import Path

from ..profiles.counting_stars import EVIDENCE_HASHES, ROOT
from ..verification.preservation import file_hash


def verify_evidence(root=ROOT):
    fingerprints = {}
    for relative, expected in EVIDENCE_HASHES.items():
        source = Path(root) / relative
        if not source.is_file():
            raise ValueError(f'Required cached observation file is missing: {source}')
        actual = file_hash(source)
        if actual != expected:
            raise ValueError(f'Cached observations have changed: {source} '
                             f'(SHA-256 expected {expected}, actual {actual}). '
                             'This profile cannot reuse unverified observations.')
        fingerprints[relative] = actual
    return fingerprints


def read_evidence(path, words):
    observations = json.loads(Path(path).read_text(encoding='utf-8'))
    assert [(item['line'], item['column'], item['source']) for item in observations] == words
    return observations


def read_pitch_data(folder):
    with (folder / 'pitch_boundary_candidates.csv').open(newline='', encoding='utf-8') as source:
        boundaries = list(csv.DictReader(source))
    with (folder / 'source_frames.csv').open(newline='', encoding='utf-8') as source:
        frames = [(float(row['wav_time_s']), float(row['rms_dbfs']),
                   float(row['praat_midi_pitch']), float(row['praat_strength']))
                  for row in csv.DictReader(source)]
    assert len(frames) == 26256
    assert [int(row['index_0_based']) for row in boundaries] == list(range(715))
    return boundaries, frames


