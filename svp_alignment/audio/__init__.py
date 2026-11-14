"""Song-independent forced alignment of supplied lyrics to their vocal WAV."""

from .alignment import align_words
from .models import get_model_status

__all__ = ["align_words", "get_model_status"]
