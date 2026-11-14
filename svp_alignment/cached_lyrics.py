"""Place cached Counting Stars lyrics while preserving every other note field."""

from .alignment.evidence import read_evidence
from .alignment.lyrics import note_lyrics, source_words, syllable_evidence
from .alignment.matching import match_notes, review_status
from .general_prepared import GeneralPrepared
from .pipeline import inspect_paths
from .profiles.counting_stars import ROOT, UNPLACED
from .project import read_project
from .verification.general_reporting import markdown
from .verification.lyrics import verify_lyrics
from .verification.lyrics_only import verify_lyrics_only
from .verification.reporting import lyric_rows, note_rows


def prepare_cached_lyrics(paths, summary, workspace, progress=None, cancelled=None):
    """Reuse lyric correspondence evidence; timing calculation is never invoked."""
    def checkpoint(label, fraction):
        if cancelled is not None and cancelled():
            raise InterruptedError("작업이 취소됐습니다.")
        if progress is not None:
            progress(label, fraction)
        if cancelled is not None and cancelled():
            raise InterruptedError("작업이 취소됐습니다.")

    checkpoint("기존 가사 관측 자료·원본 재검사", 0.0)
    current = inspect_paths(*paths)
    if any(current[key] != summary[key] for key in
           ("paths", "input_hashes", "evidence_hashes", "group_id")):
        raise ValueError("입력 또는 가사 관측 자료가 검사 이후 변경됐습니다. 다시 검사하세요.")
    document = read_project(paths[0], uploaded=True)
    records = document.target_notes()
    original_notes = [record["note"] for record in records]
    words = source_words(paths[1])
    acoustic = ROOT / "work" / "acoustic"
    en = read_evidence(acoustic / "en_ctc_words.json", words)
    mms = read_evidence(acoustic / "mms_ctc_words.json", words)
    syllables = syllable_evidence(en, mms)
    checkpoint("기존 음표에 가사 대응 · 음표 시간 고정", 0.4)
    assignments, continuations = match_notes(syllables, original_notes)
    unknown = review_status(syllables, original_notes, assignments, continuations)
    display = note_lyrics(assignments, syllables)
    changes = {}
    evidence = []
    for index, record in enumerate(records):
        if index in display:
            changes[record["locator"]] = {"lyrics": display[index]}
        elif index in continuations:
            changes[record["locator"]] = {"lyrics": "-"}
        ids = assignments.get(continuations.get(index, index), ())
        if index in continuations:
            ids = ids[-1:]
        linked = [syllables[item] for item in ids]
        evidence.append(dict(
            start_reference=min((item["onset"] for item in linked), default=None),
            end_reference=max((item["end"] for item in linked), default=None),
            start_basis="CACHED_CTC_REFERENCE_ONLY",
            end_basis="CACHED_CTC_REFERENCE_ONLY",
        ))
    updated = document.apply(changes)
    verify_lyrics_only(document, updated)
    after = [record["note"] for record in document.target_notes(project=updated)]
    placed = verify_lyrics(after, assignments, continuations, syllables, words, UNPLACED)
    if placed != 515:
        raise ValueError("Counting Stars 가사 대응 수가 기존 관측 자료와 다릅니다.")
    rows = note_rows(original_notes, after, assignments, continuations,
                     syllables, evidence, unknown)
    lyrics = lyric_rows(words, syllables, assignments, after, unknown, UNPLACED)
    for index, row in enumerate(lyrics):
        row["word_index"] = index
    provenance = dict(
        method="CACHED_CTC_LYRIC_PLACEMENT", cache_reused=True,
        operation="lyrics_only", evidence_hashes=summary["evidence_hashes"],
        listening="NOT_RUN", overall="NOT_VERIFIED",
    )
    report = markdown(rows, lyrics, summary, provenance)
    checkpoint("가사 외 전체 필드 보존 확인", 0.9)
    current = inspect_paths(*paths)
    if any(current[key] != summary[key] for key in
           ("paths", "input_hashes", "evidence_hashes", "group_id")):
        raise ValueError("가사 배치 중 입력 또는 기존 관측 자료가 변경됐습니다.")
    checkpoint("가사 입력 후보 준비 완료 · 음표 유지", 1.0)
    return GeneralPrepared(document, updated, summary, rows, lyrics, report, provenance)
