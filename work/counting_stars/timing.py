"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.alignment.timing import (local_rms_onset, onset_candidate, time_notes)
from svp_alignment.alignment.evidence import (read_pitch_data)
from svp_alignment.profiles.counting_stars import (ONSET_LANDMARKS, END_LANDMARKS)

__all__ = ["local_rms_onset","onset_candidate","time_notes","read_pitch_data","ONSET_LANDMARKS","END_LANDMARKS"]
