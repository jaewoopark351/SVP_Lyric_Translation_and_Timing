"""Piecewise conversion between Synthesizer V blicks and project seconds."""

from bisect import bisect_right
from copy import deepcopy
import math

BLICK_PER_QUARTER = 705_600_000


class TempoMap:
    """Integrate constant-tempo segments without modifying tempo marks."""

    def __init__(self, tempo, start_time_seconds=0.0):
        if not isinstance(start_time_seconds, (int, float)) or isinstance(start_time_seconds, bool) or not math.isfinite(start_time_seconds):
            raise ValueError('SVP startTimeSeconds must be a finite number.')
        if not isinstance(tempo, list) or not tempo:
            raise ValueError('SVP requires at least one tempo mark at blick zero.')
        positions, bpms = [], []
        for mark in tempo:
            if not isinstance(mark, dict):
                raise ValueError('Malformed SVP tempo mark.')
            position, bpm = mark.get('position'), mark.get('bpm')
            if not isinstance(position, int) or isinstance(position, bool):
                raise ValueError('SVP tempo positions must be integer blicks.')
            if not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or not math.isfinite(bpm) or bpm <= 0:
                raise ValueError('SVP tempo BPM must be positive and finite.')
            if positions and position <= positions[-1]:
                raise ValueError('SVP tempo positions must be strictly increasing.')
            positions.append(position)
            bpms.append(float(bpm))
        if positions[0] != 0:
            raise ValueError('SVP tempo map must begin at blick zero.')
        self.start_time_seconds = float(start_time_seconds)
        self.marks = deepcopy(tempo)
        self._positions = tuple(positions)
        self._bpms = tuple(bpms)
        seconds = [self.start_time_seconds]
        for index in range(1, len(positions)):
            seconds.append(seconds[-1] + (positions[index] - positions[index - 1]) * 60.0 / (BLICK_PER_QUARTER * bpms[index - 1]))
        self._seconds = tuple(seconds)

    @staticmethod
    def _finite(value, name):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f'{name} must be a finite number.')
        return float(value)

    def blick_to_seconds(self, blick):
        blick = self._finite(blick, 'Blick position')
        index = max(0, bisect_right(self._positions, blick) - 1)
        return self._seconds[index] + (blick - self._positions[index]) * 60.0 / (BLICK_PER_QUARTER * self._bpms[index])

    def seconds_to_blick(self, seconds):
        seconds = self._finite(seconds, 'Seconds')
        index = max(0, bisect_right(self._seconds, seconds) - 1)
        return self._positions[index] + (seconds - self._seconds[index]) * BLICK_PER_QUARTER * self._bpms[index] / 60.0
