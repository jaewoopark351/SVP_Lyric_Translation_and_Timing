"""The in-memory result of a read-only alignment calculation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PreparedAlignment:
    inputs: tuple[Path, Path, Path]
    original: dict
    updated: dict
    suffix: bytes
    duration: float
    audio: dict
    words: list
    syllables: list
    assignments: dict
    continuations: dict
    unknown: dict
    evidence: list

    def as_legacy_tuple(self):
        return (self.inputs, self.original, self.updated, self.suffix, self.duration,
                self.audio, self.words, self.syllables, self.assignments,
                self.continuations, self.unknown, self.evidence)
