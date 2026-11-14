"""Inspect one immutable uploaded song and bind its model/input contract."""

from pathlib import Path

import soundfile as sf

from svp_alignment.project import read_project
from svp_alignment.alignment.general_lyrics import read_words
from svp_alignment.verification.preservation import file_hash
from svp_alignment.audio.transcript import select_model
from svp_alignment.audio.model_catalog import WORD_OBSERVATION_MODELS
from svp_alignment.alignment.general_matching import PLACEMENT_POLICY


def inspect_song(svp, txt, wav, language="auto", model_choice="auto"):
    paths = tuple(Path(value).resolve(strict=True) for value in (svp, txt, wav))
    if any(not value.is_file() for value in paths):
        raise ValueError("SVP, TXT, WAV 파일을 각각 업로드하세요.")
    if tuple(value.suffix.lower() for value in paths) != (".svp", ".txt", ".wav"):
        raise ValueError("SVP, TXT, WAV 파일 종류를 확인하세요.")
    hashes = [file_hash(value) for value in paths]
    document = read_project(paths[0], uploaded=True)
    notes = document.target_notes()
    words = read_words(paths[1])
    if not words:
        raise ValueError("TXT에 분석할 가사가 없습니다.")
    model_id = select_model(words, language, model_choice)
    audio = sf.info(paths[2])
    if audio.frames <= 0 or audio.samplerate <= 0 or audio.channels <= 0:
        raise ValueError("WAV 오디오가 비어 있거나 형식이 올바르지 않습니다.")
    if model_id in WORD_OBSERVATION_MODELS and audio.duration > 300:
        raise ValueError('Qwen 정렬 모델은 5분 이하 WAV를 지원합니다. 영어 Large 또는 MMS_FA를 선택하세요.')
    details = document.inspect()
    title = paths[0].stem
    summary = {
        **details,
        "mode": "general",
        "operation": "lyrics_only",
        "placement_policy": PLACEMENT_POLICY,
        "language": language,
        "model_choice": model_choice,
        "model_id": model_id,
        "title": title,
        "paths": [str(value) for value in paths],
        "input_hashes": hashes,
        "evidence_hashes": {},
        "note_count": len(notes),
        "word_count": len(words),
        "line_count": len({word["line"] for word in words}),
        "duration": audio.duration,
        "channels": audio.channels,
        "sample_rate": audio.samplerate,
        "group_id": " / ".join(dict.fromkeys(str(note["group_id"]) for note in notes)),
        "artifact_names": [
            title + "_LYRICS_FILLED.svp",
            title + " - Note comparison.csv",
            title + " - Lyric verification.csv",
            title + " - Verification.md",
        ],
    }
    summary.setdefault("audio_offset", 0.0)
    summary.setdefault("warnings", [])
    summary["warnings"].append(
        "이 곡의 WAV와 TXT로 가사를 기존 음표에 대응합니다. "
        "음표 위치·길이·음높이는 유지하고 lyrics만 입력합니다. 자동 후보는 실제 청취·합성 확인이 필요합니다."
    )
    if hashes != [file_hash(value) for value in paths]:
        raise ValueError("검사 중 입력 파일이 변경됐습니다. 다시 검사하세요.")
    return summary

