"""Coordinate immutable song observations, lyric placement, and review rendering."""

from copy import deepcopy
from pathlib import Path

from .general_prepared import GeneralPrepared
from .jobs.song_inputs import inspect_song
from .project import read_project
from .alignment.general_lyrics import read_words
from .alignment.general_matching import match_words_to_notes
from .alignment.review_edits import restore_alignment, apply_review_edit, PLACEMENT_POLICY
from .verification.general_reporting import note_rows, lyric_rows, markdown
from .verification.general_lyrics import verify_placement
from .verification.lyrics_only import verify_lyrics_only
from .verification.preservation import file_hash


def _finish(document, summary, alignment, provenance, edits=()):
    before = document.target_notes()
    evidence = [dict(start_reference=None, end_reference=None,
                     start_basis='ORIGINAL_UNCONFIRMED', end_basis='ORIGINAL_UNCONFIRMED')
                for _ in before]
    for index, ids in alignment['assignments'].items():
        candidate = alignment['syllables'][ids[0]]
        last_candidate = alignment['syllables'][ids[-1]]
        evidence[index] = dict(start_reference=candidate['onset'], end_reference=last_candidate['end'],
                               start_basis=('MODEL_WORD_WINDOW_ONLY' if candidate.get('alignment_unit') == 'word'
                                            else 'FRESH_CTC_CHARACTER_CANDIDATE'),
                               end_basis=('MODEL_WORD_WINDOW_ONLY' if last_candidate.get('alignment_unit') == 'word'
                                          else 'FRESH_CTC_CHARACTER_CANDIDATE'))
    changes = {before[index]['locator']: {'lyrics': text}
               for index, text in alignment['lyric_fields'].items()}
    updated = document.apply(changes)
    verify_lyrics_only(document, updated)
    after = document.target_notes(project=updated)
    verification = verify_placement(alignment['words'], alignment, after)
    provenance = {**deepcopy(provenance), 'placement_policy': alignment['placement_policy'],
                  'symbol_chains': verification['symbol_chains'],
                  'source_accounting': verification['source_accounting'],
                  'review_edit_count': len(edits), 'overall': 'NOT_VERIFIED'}
    rows = note_rows(before, after, alignment, evidence)
    lyrics = lyric_rows(alignment['words'], alignment, after, model_id=provenance['model_id'])
    report = markdown(rows, lyrics, summary, provenance)
    context = dict(schema=1, input_hashes=list(summary['input_hashes']), model_id=summary['model_id'],
                   placement_policy=alignment['placement_policy'], alignment=deepcopy(alignment),
                   evidence=deepcopy(evidence), provenance=provenance, edits=list(edits))
    return GeneralPrepared(document, updated, summary, rows, lyrics, report, provenance,
                           review_context=context)


def prepare_song(paths, summary, workspace, progress=None, cancelled=None):
    from .audio.alignment import align_words

    if summary.get('operation') != 'lyrics_only':
        raise ValueError('기존 타이밍 수정 작업을 가사만 입력하는 작업으로 재계산할 수 없습니다. '
                         '세 입력 파일을 새로 검사하세요.')

    def checkpoint(label, fraction):
        if cancelled is not None and cancelled():
            raise InterruptedError('작업이 취소됐습니다.')
        if progress is not None:
            progress(label, fraction)

    checkpoint('업로드한 곡의 입력 재검사', 0.0)
    if 'model_choice' not in summary:
        raise ValueError('모델을 선택하고 입력을 다시 검사하세요.')
    current = inspect_song(*paths, language=summary.get('language', 'auto'),
                           model_choice=summary['model_choice'])
    if any(current[key] != summary[key] for key in
           ('paths', 'input_hashes', 'group_id', 'model_choice', 'model_id')):
        raise ValueError('입력 파일이 검사 이후 변경됐습니다. 다시 검사하세요.')
    document = read_project(paths[0], uploaded=True)
    before = document.target_notes()
    words = read_words(paths[1])
    aligned, provenance = align_words(
        paths[2], words, workspace,
        progress=lambda label, fraction: checkpoint(label, 0.05 + 0.7 * fraction),
        cancelled=cancelled, language=summary.get('language', 'auto'),
        model_choice=summary['model_choice'])
    if provenance.get('model_id') != summary['model_id']:
        raise ValueError('실행된 AI 모델이 검사한 선택 모델과 다릅니다.')
    checkpoint('발음 관측과 연속된 기존 음표 대응', 0.78)
    alignment = match_words_to_notes(words, aligned, before,
                                     audio_offset=float(summary.get('audio_offset', 0.0)))
    prepared = _finish(document, summary, alignment, provenance)
    checkpoint('가사 연결·원본 음표 전체 보존 확인', 1.0)
    if summary['input_hashes'] != [file_hash(value) for value in paths]:
        raise ValueError('분석 중 입력 파일이 변경됐습니다. 다시 검사하세요.')
    return prepared


def restore_song(paths, summary, context, edit=None):
    """Rebuild a validated review revision without re-running acoustic inference."""
    if (context.get('schema') != 1 or context.get('placement_policy') != PLACEMENT_POLICY
            or context.get('input_hashes') != summary.get('input_hashes')
            or context.get('model_id') != summary.get('model_id')
            or summary.get('operation') != 'lyrics_only'):
        raise ValueError('교정 근거의 입력·모델·배치 정책이 다릅니다. 입력을 다시 검사하세요.')
    if summary['input_hashes'] != [file_hash(value) for value in paths]:
        raise ValueError('교정 전에 입력 파일이 변경됐습니다.')
    document = read_project(paths[0], uploaded=True)
    alignment = restore_alignment(context['alignment'])
    words = read_words(paths[1])
    if alignment['words'] != words:
        raise ValueError('교정 근거와 TXT 원문 토큰이 다릅니다.')
    evidence = context.get('evidence')
    if not isinstance(evidence, list) or len(evidence) != len(document.target_notes()):
        raise ValueError('교정 근거의 음표 관측 기록이 다릅니다.')
    edits = deepcopy(context.get('edits', []))
    if edit is not None:
        alignment = apply_review_edit(alignment, document.target_notes(), **edit)
        edits.append(deepcopy(edit))
    prepared = _finish(document, summary, alignment, context['provenance'], edits)
    if summary['input_hashes'] != [file_hash(value) for value in paths]:
        raise ValueError('교정 중 입력 파일이 변경됐습니다.')
    return prepared
