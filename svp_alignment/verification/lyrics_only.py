"""Require exact project preservation outside selected existing note lyrics."""

from copy import deepcopy
import json


def verify_lyrics_only(document, updated, track_index=None):
    """Reject every change except lyrics on the document's target notes."""
    document.verify(updated, track_index)
    before, after = deepcopy(document.data), deepcopy(updated)
    for record in document.target_notes(track_index):
        original_note, changed_note = before, after
        for part in record["locator"]:
            original_note = original_note[part]
            changed_note = changed_note[part]
        original_note.pop("lyrics", None)
        changed_note.pop("lyrics", None)
    # JSON equality distinguishes true/1 and 1/1.0, unlike Python dict equality.
    options = dict(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if json.dumps(before, **options) != json.dumps(after, **options):
        raise ValueError(
            "가사만 입력하는 작업에서는 선택 음표의 lyrics 외 필드를 변경할 수 없습니다. "
            "음표 위치·길이·음높이와 프로젝트 설정을 원본 그대로 유지해야 합니다."
        )
    return True
