"""Select a verified cached profile or a fresh uploaded-song calculation."""

from pathlib import Path

from svp_alignment.pipeline import inspect_paths
from svp_alignment.profiles.counting_stars import SOURCE_HASHES
from svp_alignment.verification.preservation import file_hash
from svp_alignment.audio.model_catalog import MODEL_CHOICES


def inspect_job_inputs(paths, language='auto', model_choice='auto'):
    paths = tuple(Path(value) for value in paths)
    if model_choice not in {value for _, value in MODEL_CHOICES}:
        raise ValueError('지원하는 AI 정렬 모델을 선택하세요.')
    if model_choice == 'cached_counting_stars':
        if tuple(file_hash(value) for value in paths) != SOURCE_HASHES:
            raise ValueError('기존 Counting Stars 분석 자료는 검증된 원본 세 파일에만 사용할 수 있습니다.')
        summary = inspect_paths(*paths)
        if summary:
            summary["mode"] = "counting_stars"
            summary["language"] = language
            summary["operation"] = "lyrics_only"
            summary["model_choice"] = model_choice
            summary["model_id"] = model_choice
            title = paths[0].stem
            summary["title"] = title
            summary["artifact_names"] = [title + "_LYRICS_FILLED.svp",
                                         title + " - Note comparison.csv",
                                         title + " - Lyric verification.csv",
                                         title + " - Verification.md"]
            summary.setdefault("warnings", []).append(
                "기존 발음 관측은 가사 대응에만 사용하며 음표의 시작·길이·음높이와 가사 외 모든 필드는 유지합니다.")
            return summary
    from svp_alignment.general_pipeline import inspect_song
    return inspect_song(*paths, language=language, model_choice=model_choice)


def prepare_job(paths, summary, workspace, progress=None, cancelled=None):
    if summary.get("operation") != "lyrics_only":
        raise ValueError("이전 타이밍 수정 작업입니다. 파일을 다시 업로드하고 입력 검사를 실행하세요.")
    if 'model_choice' not in summary:
        raise ValueError('모델 선택이 기록되지 않은 이전 작업입니다. 모델을 선택하고 입력을 다시 검사하세요.')
    if summary.get("mode", "counting_stars") == "counting_stars":
        from svp_alignment.cached_lyrics import prepare_cached_lyrics
        return prepare_cached_lyrics(paths, summary, workspace, progress=progress, cancelled=cancelled)
    from svp_alignment.general_pipeline import prepare_song
    return prepare_song(paths, summary, workspace, progress=progress, cancelled=cancelled)
