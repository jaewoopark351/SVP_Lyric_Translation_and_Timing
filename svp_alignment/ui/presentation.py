"""Read-only review formatting for the local Gradio screen."""

from __future__ import annotations

import json
import math
from typing import Any

from ..audio.model_catalog import HEAVY_MODEL, MODEL_CHOICES, QWEN_MODEL, saved_model_choice

MODEL_LABELS = {value: label for label, value in MODEL_CHOICES}
ACTION_LABELS = {
    "WORD_START": "단어 시작", "NEXT_SYLLABLE": "다음 음절 (+)",
    "CONTINUE": "지속음 (-)", "TEXT_FRAGMENT": "분할 가사",
    "UNASSIGNED_ORIGINAL": "미대응 · 원본 유지",
}
REVIEW_LABELS = {"AUTO_CANDIDATE": "자동 후보", "NEEDS_REVIEW": "검토 필요",
                 "USER_CONFIRMED": "사용자 확인"}

NOTE_COLUMNS = (
    ("note", "음표"), ("txt_line", "TXT 행"), ("txt_word", "TXT 단어"),
    ("old_lyrics", "원본 가사"), ("new_lyrics", "수정 가사"),
    ("old_start_s", "원본 시작 (초)"), ("new_start_s", "수정 시작 (초)"),
    ("old_duration_s", "원본 길이 (초)"), ("new_duration_s", "수정 길이 (초)"),
    ("onset_error_before_ms", "시작 오차 전 (ms)"),
    ("onset_error_after_ms", "시작 오차 후 (ms)"),
    ("end_error_before_ms", "종료 오차 전 (ms)"),
    ("end_error_after_ms", "종료 오차 후 (ms)"),
    ("assignment", "상태"), ("assignment_reason", "미확정 사유"),
    ("start_basis", "시작 근거"), ("end_basis", "종료 근거"),
    ("note_id", "음표 ID"),
    ("placement_action", "배치 행동"), ("review_status", "검토 상태"),
    ("symbol_risk", "기호 연결 위험"),
)
LYRIC_COLUMNS = (
    ("txt_line", "TXT 행"), ("txt_column", "행 내 위치"), ("txt_word", "원문 단어"),
    ("note_numbers", "음표 번호"), ("svp_lyrics", "SVP 가사"),
    ("syllables", "음절"), ("status", "상태"), ("reason", "미확정 사유"),
    ("unknown_start_s", "미확정 시작 (초)"), ("unknown_end_s", "미확정 끝 (초)"),
    ("review_status", "검토 상태"), ("symbol_risk", "기호 연결 위험"),
)
QUALITY_FILTERS = (
    ("전체", "all"), ("미대응 음표", "unassigned_notes"),
    ("미배치 단어", "unplaced_words"), ("기호 연결 위험", "symbol_risks"),
    ("배치 후 검토 필요", "review_required"), ("사용자 확인", "confirmed"),
    ("이전 작업 · 분류 기록 없음", "legacy_unknown"),
)
ERROR_COLUMNS = (
    "onset_error_before_ms", "onset_error_after_ms",
    "end_error_before_ms", "end_error_after_ms",
)
REVIEW_STATES = {"REVIEW_READY", "COMPLETED"}
STATUS_LABELS = {
    "CREATED": "작업 생성", "VALIDATING": "입력 검사 중", "READY": "실행 준비 완료",
    "RUNNING": "기존 음표에 가사 대응 중", "REVIEW_READY": "검토 가능 · 아직 저장 전",
    "EXPORTING": "새 결과 저장 중", "COMPLETED": "새 결과 저장 완료",
    "CANCEL_REQUESTED": "취소 요청됨 · 현재 단계 종료 대기", "CANCELLED": "취소됨",
    "FAILED": "작업 실패",
}


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _quality_match(row: dict, quality_filter: str, *, lyric=False) -> bool:
    if quality_filter == "all":
        return True
    action = row.get("placement_action")
    review = row.get("review_status")
    if quality_filter == "legacy_unknown":
        return not review and not action and not row.get("placement_policy")
    if quality_filter == "unassigned_notes":
        return not lyric and action == "UNASSIGNED_ORIGINAL"
    if quality_filter == "unplaced_words":
        return lyric and not str(row.get("note_numbers", "")).strip()
    if quality_filter == "symbol_risks":
        return str(row.get("symbol_risk", "")).lower() in {"true", "1"}
    if quality_filter == "review_required":
        return (review == "NEEDS_REVIEW" and action != "UNASSIGNED_ORIGINAL"
                and (not lyric or bool(str(row.get("note_numbers", "")).strip())))
    if quality_filter == "confirmed":
        return review == "USER_CONFIRMED"
    raise ValueError("검토 분류를 다시 선택하세요.")


def filtered_notes(snapshot: dict, unknown_only=False, large_only=False, threshold=100,
                   quality_filter="all") -> list[dict]:
    """Use the same error fields and >= threshold contract as the CSV report."""
    threshold = finite_number(threshold)
    if threshold is None or threshold < 0:
        raise ValueError("큰 오차 기준은 0 이상의 유한한 ms 값이어야 합니다.")
    rows = snapshot.get("comparison_rows", [])
    return [row for row in rows
            if (not unknown_only or row.get("assignment") == "UNKNOWN")
            and _quality_match(row, quality_filter)
            and (not large_only or any(
                (value := finite_number(row.get(key))) is not None and abs(value) >= threshold
                for key in ERROR_COLUMNS))]


def filtered_lyrics(snapshot: dict, unknown_only=False, quality_filter="all") -> list[dict]:
    return [row for row in snapshot.get("lyric_rows", [])
            if (not unknown_only or row.get("status") == "UNKNOWN")
            and _quality_match(row, quality_filter, lyric=True)]


def table_data(rows: list[dict], columns=NOTE_COLUMNS) -> dict:
    data = []
    for original in rows:
        row = dict(original)
        for prefix in ("old", "new"):
            start = finite_number(row.get(f"{prefix}_start_s"))
            end = finite_number(row.get(f"{prefix}_end_s"))
            if start is not None and end is not None:
                row[f"{prefix}_duration_s"] = round(end - start, 6)
        row["placement_action"] = ACTION_LABELS.get(row.get("placement_action"), "분류 기록 없음")
        row["review_status"] = REVIEW_LABELS.get(row.get("review_status"), "분류 기록 없음")
        symbol = str(row.get("symbol_risk", "")).lower()
        row["symbol_risk"] = "위험" if symbol in {"true", "1"} else "없음" if symbol in {"false", "0"} else "기록 없음"
        data.append([row.get(key, "") for key, _ in columns])
    return {"headers": [label for _, label in columns], "data": data}


def status_text(snapshot: dict) -> str:
    status = snapshot.get("status", "CREATED")
    label = STATUS_LABELS.get(status, status)
    quality = snapshot.get("summary", {})
    if status == "COMPLETED":
        if not quality.get("quality_known"):
            label = "이전 결과 저장 완료 · 가사 완성도 확인 불가"
        elif not quality.get("placement_complete"):
            label = "부분 초안 저장 완료"
        else:
            label = "가사 배치 초안 저장 완료 · 청취 확인 필요"
    text = f"**{label}** · `{status}`"
    if snapshot.get("stage"):
        text += f"\n\n{snapshot['stage']}"
    if snapshot.get("input_summary"):
        text += "\n\n" + model_text(snapshot)
        if not selected_model(snapshot) and status in {"READY", "REVIEW_READY"}:
            text += "\n\n**모델 선택 이전 작업**입니다. 실행·저장하려면 파일을 다시 올리고 입력 검사를 실행하세요."
        if not current_placement_policy(snapshot) and status in {"READY", "REVIEW_READY"}:
            text += "\n\n**이전 가사 배치 방식의 작업**입니다. 새 배치와 교정을 사용하려면 파일을 다시 올리고 입력 검사를 실행하세요."
    if snapshot.get("input_summary") and not lyrics_only(snapshot):
        text += "\n\n**이전 타이밍 수정 작업**입니다. 가사 전용 결과를 만들려면 입력 검사를 다시 실행하세요."
    if snapshot.get("input_summary", {}).get("filename_mismatches"):
        text += "\n\n선택한 파일명이 AGENTS.md 계약과 다릅니다. 내용은 고정 프로필 해시와 일치하며, 원래 파일명을 보존합니다. 검사 상세를 확인하세요."
    if snapshot.get("error"):
        text += "\n\n오류 사유:\n\n" + fenced(snapshot["error"])
    return text


def fenced(value: Any) -> str:
    text = str(value).replace("```", "'''" )
    return "```text\n" + text + "\n```"


def input_text(snapshot: dict) -> str:
    information = snapshot.get("input_summary", {})
    if not information:
        return "SVP·TXT·WAV를 업로드한 뒤 **입력 검사**를 누르세요."
    return fenced(json.dumps(information, ensure_ascii=False, indent=2, default=str))


def model_text(snapshot: dict) -> str:
    information = snapshot.get("input_summary", {})
    provenance = snapshot.get("summary", {}).get("provenance") or {}
    choice = saved_model_choice(information, provenance)
    if choice == "cached_counting_stars":
        return "**분석 선택: Counting Stars 기존 관측 재사용** · 새 AI 모델 분석은 실행하지 않습니다."
    resolved = information.get("model_id") or provenance.get("model_id")
    label = MODEL_LABELS.get(choice, choice)
    if not selected_model(snapshot) and not resolved:
        return "**이전 AI 모델: 기록 없음** · 모델 선택 칸의 기본값은 과거 실행 모델을 확정하지 않습니다."
    return f"**AI 정렬 모델: {label}**" + (f" · 실제 모델: {resolved}" if resolved else "")


def selected_model(snapshot: dict) -> bool:
    return bool(snapshot.get("input_summary", {}).get("model_choice"))


def lyrics_only(snapshot: dict) -> bool:
    return snapshot.get("input_summary", {}).get("operation") == "lyrics_only"


def current_placement_policy(snapshot: dict) -> bool:
    information = snapshot.get("input_summary", {})
    return (information.get("mode") != "general"
            or information.get("placement_policy") == "word_note_groups_v1")


def correction_syllable_number(row: dict, snapshot: dict) -> int:
    """Suggest a word-local boundary; the correction policy still validates it."""
    word = row.get("word_index")
    if word is None or str(word).strip() == "":
        return 2
    related = [item for item in snapshot.get("comparison_rows", [])
               if str(item.get("word_index")) == str(word)]
    def ids(item):
        return [int(value) for value in str(item.get("syllable_ids", "")).split()]
    try:
        parts = sorted({part for item in related for part in ids(item)})
        current_ids = ids(row)
        if row.get("placement_action") == "NEXT_SYLLABLE" and current_ids:
            return parts.index(current_ids[0]) + 1
        note = int(row["note"])
        starts = [(int(item["note"]), parts.index(ids(item)[0])) for item in related
                  if item.get("placement_action") in {"WORD_START", "NEXT_SYLLABLE", "TEXT_FRAGMENT"}
                  and ids(item) and int(item["note"]) != note]
        before = max((part for number, part in starts if number < note), default=0)
        after = min((part for number, part in starts if number > note), default=len(parts))
        return before + 2 if before + 1 < after else 2
    except (ValueError, TypeError, KeyError):
        return 2


def report_text(snapshot: dict) -> str:
    report = snapshot.get("report", "")
    if report and not lyrics_only(snapshot):
        return (
            "**이전 타이밍 수정 작업 보고서** · 이 결과에는 음표 시작·길이 변경이 포함될 수 있습니다. "
            "현재 가사 전용 작업의 결과가 아닙니다.\n\n---\n\n" + report
        )
    return report


def review_text(snapshot: dict) -> str:
    if snapshot.get("status") not in REVIEW_STATES:
        return "결과 생성 후 음표·가사 비교표를 검토할 수 있습니다."
    notes = snapshot.get("comparison_rows", [])
    lyrics = snapshot.get("lyric_rows", [])
    unknown = sum(row.get("assignment") == "UNKNOWN" for row in notes)
    unknown_words = sum(row.get("status") == "UNKNOWN" for row in lyrics)
    missing = sum(not str(row.get("note_numbers", "")).strip() for row in lyrics)
    summary = snapshot.get("summary", {})
    provenance = summary.get("provenance") or {}
    model_id = (snapshot.get("input_summary", {}).get("model_id")
                or provenance.get("model_id"))
    general = snapshot.get("input_summary", {}).get("mode") == "general"
    analysis = (
        "같은 입력·모델·설정의 저장 관측으로 자동 후보를 복원했습니다. "
        "이번 작업의 새 추론·전체 WAV 청취 검증: **NOT_RUN**. "
        if general and provenance.get("cache_reused") else
        "WAV를 ASR 1.7B로 인식하고 인식 문장을 ForcedAligner 0.6B로 단어 시각에 대응했습니다. "
        "**새 ASR 인식·단어 정렬 실행 완료 · 전체 WAV 청취 검증: NOT_RUN**. "
        if general and model_id == HEAVY_MODEL else
        "이 곡의 WAV와 가사를 강제 정렬해 자동 후보를 생성했습니다. "
        "**새 음성 정렬 실행 완료 · 전체 WAV 청취 검증: NOT_RUN**. "
        if general else
        "검증된 Counting Stars 기존 분석 자료를 재사용했습니다. "
        "이번 작업의 새 음성 분석·전체 WAV 청취 검증: **NOT_RUN**. "
    )
    if model_id == HEAVY_MODEL:
        analysis += (
            "제공 TXT를 최종 가사의 기준으로 유지합니다. ASR 인식문은 정답이 아니며 TXT와 정확히 "
            "대응하지 않거나 반복 위치가 모호한 단어는 UNKNOWN입니다. "
        )
    if model_id in (QWEN_MODEL, HEAVY_MODEL):
        analysis += (
            "**Qwen은 단어 시간 범위만 제공하며 개별 음절·문자 시각과 신뢰도 점수는 제공하지 않습니다.** "
            "단어 범위로 대응한 가사 후보는 UNKNOWN으로 표시합니다. 원본 보컬을 듣고 확인하세요. "
        )
    operation = (
        "**가사 전용 작업 · 원본 음표 시간 고정**\n\n"
        "음표 시작·길이·음높이·개수·순서와 프로젝트 설정을 유지하고 가사만 변경했습니다.\n\n"
        if lyrics_only(snapshot) else
        "**이전 타이밍 수정 작업** · 이 결과에는 음표 시작·길이 변경이 포함될 수 있습니다. "
        "현재 가사 전용 작업의 결과가 아닙니다.\n\n"
    )
    preservation = "가사 외 전체 필드 보존" if lyrics_only(snapshot) else "허용 필드 외 보존"
    if not summary.get("quality_known"):
        quality_text = ("**이전 작업 · 새 검토 분류 기록 없음**. 기존 파일과 보고서는 그대로 보존합니다. "
                        "현재 분류 기준의 배치 완료·사용자 확인 여부는 알 수 없습니다.\n\n")
    else:
        completion = "가사 배치 완료 · 청취 확인 필요" if summary.get("placement_complete") else "부분 초안 · 미해결 항목 있음"
        quality_text = (
            f"**{completion}**\n\n"
            f"미대응 음표 {summary.get('unresolved_notes', 0)}개 · "
            f"미배치 단어 {missing}개 · 기호 연결 위험 {summary.get('symbol_risks', 0)}개 · "
            f"배치 후 검토 필요 {summary.get('review_required_notes', 0)}개 · "
            f"사용자 확인 {summary.get('confirmed_notes', 0)}개\n\n"
        )
    return (
        operation + quality_text + "**가사 대응 전체 판정: NOT_VERIFIED**\n\n"
        f"음표 {len(notes)}개 · UNKNOWN 음표 {unknown}개 · "
        f"TXT {len(lyrics)}단어 · UNKNOWN 단어 {unknown_words}개 · 미배치 {missing}단어\n\n"
        + model_text(snapshot) + "\n\n" + analysis +
        "아래 재생기는 원본 보컬의 선택 구간만 재생합니다.\n\n"
        "Synthesizer V Studio Pro 실제 열기: **NOT_RUN** · 합성 보컬 재생: **NOT_RUN**. "
        f"파일 파싱: **{summary.get('parse', 'NOT_VERIFIED')}** · "
        f"{preservation}: **{summary.get('preservation', 'NOT_VERIFIED')}**. "
        "상세 근거는 검증 보고서를 확인하세요."
    )


def row_interval(row: dict) -> tuple[float, float]:
    starts = [finite_number(row.get(key)) for key in ("old_start_s", "new_start_s", "unknown_start_s")]
    ends = [finite_number(row.get(key)) for key in ("old_end_s", "new_end_s", "unknown_end_s")]
    starts = [value for value in starts if value is not None]
    ends = [value for value in ends if value is not None]
    if not starts or not ends:
        raise ValueError("이 행에는 재생 시각이 없습니다. 시작·종료 초를 직접 입력하세요.")
    start = max(0.0, min(starts) - 0.25)
    end = min(start + 30.0, max(ends) + 0.25)
    return round(start, 3), round(end, 3)


def preview_interval(row: dict, snapshot: dict) -> tuple[float, float]:
    """Convert project timeline columns to the uploaded WAV's own clock."""
    offset = float(snapshot.get("input_summary", {}).get("audio_offset", 0.0))
    relative = dict(row)
    for key in ("old_start_s", "new_start_s", "unknown_start_s",
                "old_end_s", "new_end_s", "unknown_end_s"):
        value = finite_number(row.get(key))
        if value is not None:
            relative[key] = value - offset
    return row_interval(relative)
