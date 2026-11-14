"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.verification.preservation import (EDITABLE, SOURCE_HASHES, verify_inputs, verify_svp)
from svp_alignment.verification.lyrics import (verify_lyrics)
from svp_alignment.verification.reporting import (milliseconds, note_rows)

__all__ = ["EDITABLE","SOURCE_HASHES","verify_inputs","verify_svp","verify_lyrics","milliseconds","note_rows"]
