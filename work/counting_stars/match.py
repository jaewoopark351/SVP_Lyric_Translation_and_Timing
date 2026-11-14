"""Compatibility exports for the original Counting Stars script imports."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from svp_alignment.alignment.matching import (review_status, point_cost, line_assignment, match_notes)
from svp_alignment.profiles.counting_stars import (LINE_STARTS, LINE_STOPS, LANDMARKS, UNPLACED, UNPLACED_NOTES, REVIEW_NOTES)

__all__ = ["review_status","point_cost","line_assignment","match_notes","LINE_STARTS","LINE_STOPS","LANDMARKS","UNPLACED","UNPLACED_NOTES","REVIEW_NOTES"]
