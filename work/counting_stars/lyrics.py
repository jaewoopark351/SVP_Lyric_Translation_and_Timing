"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.alignment.lyrics import (source_words, syllable_evidence, note_lyrics)
from svp_alignment.alignment.evidence import (read_evidence)
from svp_alignment.profiles.counting_stars import (MULTISYLLABLE, NUCLEUS, REPEATS, REPEAT_OFFSETS)

__all__ = ["source_words","syllable_evidence","note_lyrics","read_evidence","MULTISYLLABLE","NUCLEUS","REPEATS","REPEAT_OFFSETS"]
