"""Song-independent comparison CSV rows and truthful automatic-analysis reports."""

import json
import math

from ..audio.model_catalog import HEAVY_MODEL, QWEN_MODEL
from .placement_quality import summarize_quality


LARGE_ERROR_MS = 100


def _error(time, reference):
    return '' if reference is None else round(1000 * (time - reference), 3)


def _times(items, field):
    """A manual placement can own syllables with no model timing observation."""
    return ' / '.join(f"{item[field]:.3f}" for item in items
                      if isinstance(item.get(field), (int, float))
                      and not isinstance(item[field], bool) and math.isfinite(item[field]))


def note_rows(before, after, alignment, evidence):
    if len(before) != len(after) or len(before) != len(evidence):
        raise ValueError('음표 비교 자료의 개수가 다릅니다.')
    result = []
    for index, (old, new, observation) in enumerate(zip(before, after, evidence)):
        action = alignment.get('note_actions', {}).get(index, {})
        lead = alignment['continuations'].get(index, index)
        ids = action.get('syllable_ids', alignment['assignments'].get(lead, []))
        linked = [alignment['syllables'][item] for item in ids]
        attack, release = observation.get('start_reference'), observation.get('end_reference')
        result.append(dict(
            note=index + 1, note_id=old.get('note_id') or old.get('noteID') or str(old.get('locator', index)),
            pitch=old.get('pitch', ''), detune=old.get('detune', ''),
            old_onset_blick=old['onset'], new_onset_blick=new['onset'],
            old_duration_blick=old['duration'], new_duration_blick=new['duration'],
            old_start_s=round(old['start_s'], 6), new_start_s=round(new['start_s'], 6),
            old_end_s=round(old['end_s'], 6), new_end_s=round(new['end_s'], 6),
            old_lyrics=old.get('lyrics', ''), new_lyrics=new.get('lyrics', ''),
            txt_line=linked[0]['line'] if linked else '',
            txt_columns=' / '.join(str(item['column']) for item in linked),
            txt_word=' / '.join(item['source'] for item in linked),
            syllable=' / '.join(item['spelling'] for item in linked),
            assignment=('UNKNOWN' if index in alignment['unknown'] else
                        'CONTINUATION' if index in alignment['continuations'] else 'ALIGNED'),
            assignment_reason=alignment['unknown'].get(index, ''),
            waveform_start_s=attack, start_basis=observation.get('start_basis', ''),
            onset_error_before_ms=_error(old['start_s'], attack),
            onset_error_after_ms=_error(new['start_s'], attack),
            onset_change_ms=_error(new['start_s'], old['start_s']),
            waveform_end_s=release, end_basis=observation.get('end_basis', ''),
            end_error_before_ms=_error(old['end_s'], release), end_error_after_ms=_error(new['end_s'], release),
            duration_change_ms=_error(new['end_s'] - new['start_s'], old['end_s'] - old['start_s']),
            group_id=old.get('group_id', ''), original_note_index=old.get('original_note_index', index),
            timing_evidence=('NO_OBSERVATION' if attack is None and release is None else
                             'MODEL_WORD_WINDOW_ONLY' if observation.get('start_basis') == 'MODEL_WORD_WINDOW_ONLY'
                             else 'FRESH_CTC_CANDIDATE'),
            placement_action=action.get('action', ''), review_status=action.get('review_status', ''),
            word_index=action.get('word_index') if action.get('word_index') is not None else '',
            syllable_ids=' '.join(str(item) for item in action.get('syllable_ids', [])),
            owner_note_number=(action['owner_note'] + 1 if action.get('owner_note') is not None else ''),
            placement_policy=alignment.get('placement_policy', ''),
            symbol_risk=False if action and alignment.get('placement_policy') else '',
        ))
    return result


def lyric_rows(words, alignment, notes, model_id=None):
    result = []
    for word_index, word in enumerate(words):
        items = [(note, alignment['syllables'][item])
                 for note, ids in sorted(alignment['assignments'].items())
                 for item in ids if alignment['syllables'][item]['word'] == word_index]
        note_ids = list(dict.fromkeys(note for note, _ in items))
        if alignment.get('placement_policy'):
            note_ids = list(alignment.get('word_spans', {}).get(word_index, []))
        reason = alignment['unplaced'].get(word_index, '')
        reasons = [reason] if reason else []
        reasons.extend(alignment['unknown'][note] for note in note_ids if note in alignment['unknown'])
        candidates = [item for item in alignment['syllables'] if item['word'] == word_index]
        starts = [item['onset'] for item in candidates if item['onset'] is not None]
        ends = [item['end'] for item in candidates if item['end'] is not None]
        unknown = bool(reasons) or not items
        word_only = (model_id in (QWEN_MODEL, HEAVY_MODEL)
                     or any(item.get('alignment_unit') == 'word' for item in candidates))
        available_scores = [item['p'] for _, item in items if item['p'] is not None
                            and item['onset'] is not None and item['end'] is not None]
        actions = [alignment.get('note_actions', {}).get(note, {}) for note in note_ids]
        reviews = [action.get('review_status') for action in actions]
        review_status = ('NEEDS_REVIEW' if not note_ids or 'NEEDS_REVIEW' in reviews else
                         'USER_CONFIRMED' if all(status == 'USER_CONFIRMED' for status in reviews)
                         else 'AUTO_CANDIDATE') if alignment.get('placement_policy') else ''
        result.append(dict(
            txt_line=word['line'], txt_column=word['column'], txt_word=word['source'],
            note_numbers=' / '.join(str(index + 1) for index in note_ids),
            svp_lyrics=' / '.join(str(notes[index].get('lyrics', '')) for index in note_ids),
            syllables=' / '.join(item['spelling'] for _, item in items),
            ctc_starts_s=('' if word_only else _times([item for _, item in items], 'onset')),
            ctc_vowel_candidates_s='',
            ctc_end_s=('' if word_only else _times([item for _, item in items], 'end')),
            ctc_p=('' if word_only else ' / '.join(f"{score:.3f}" for score in available_scores)),
            mms_onsets_s=(_times([item for _, item in items], 'onset') if model_id == 'MMS_FA' else ''),
            status='UNKNOWN' if unknown else 'ALIGNED', reason=' / '.join(dict.fromkeys(reasons)),
            unknown_start_s=min(starts) if starts and unknown else '',
            unknown_end_s=max(ends) if ends and unknown else '',
            word_index=word_index,
            model_id=model_id or '', alignment_unit='word' if word_only else 'character',
            score_available=bool(available_scores) and not word_only,
            observed_word_start_s=min(starts) if starts else '',
            observed_word_end_s=max(ends) if ends else '',
            placement_policy=alignment.get('placement_policy', ''),
            placement_state=('UNPLACED' if word_index in alignment['unplaced'] else 'PLACED'),
            review_status=review_status,
            symbol_risk=False if alignment.get('placement_policy') else '',
        ))
    return result


def _cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('`', "'")


def markdown(rows, lyrics, input_summary, provenance):
    lyrics_only = input_summary.get('operation') == 'lyrics_only'
    cached = input_summary.get('mode') == 'counting_stars'
    reused = bool(provenance.get('cache_reused')) and not cached
    heavy = provenance.get('model_id') == HEAVY_MODEL
    word_only = provenance.get('model_id') in (QWEN_MODEL, HEAVY_MODEL)
    unknown_notes = [row for row in rows if row['assignment'] == 'UNKNOWN']
    unknown_words = [row for row in lyrics if row['status'] == 'UNKNOWN']
    missing = [row for row in lyrics if not row['note_numbers']]
    quality = summarize_quality(rows, lyrics)
    large = [row for row in rows if any(row.get(key, '') != '' and abs(row[key]) >= LARGE_ERROR_MS
             for key in ('onset_error_before_ms', 'onset_error_after_ms',
                         'end_error_before_ms', 'end_error_after_ms'))]
    lines = [
        ('# 기존 음표 유지 · 가사 입력 자동 대응 검토' if lyrics_only
         else '# 일반 곡 가사·타이밍 자동 정렬 검토'), '',
        '- 전체 가창 정렬 판정: `NOT_VERIFIED`.',
        ('- 이 결과는 해당 입력에 대해 저장된 기존 CTC 관측으로 가사를 대응한 자동 후보입니다. '
         if cached else '- 이 결과는 같은 입력·모델·설정의 저장된 음성 관측으로 가사를 대응한 자동 후보입니다. '
        if reused else '- 이 결과는 WAV의 ASR 인식·인식 문장의 단어 정렬·제공 TXT 대응으로 만든 자동 후보입니다. '
        if heavy else '- 이 결과는 선택한 WAV와 TXT로 실행한 음성 강제 정렬의 자동 후보입니다. ') +
        ('Qwen의 단어 시간 범위는 개별 음절·문자 시각이 아니며 신뢰도 점수는 제공되지 않습니다. '
         '단어 범위만 가사 대응에 사용하고 해당 후보는 UNKNOWN으로 검토합니다.' if word_only else
         'CTC 문자 시각과 모델 점수는 실제 음표 공격점·음절 수·가창 발음의 확인 결과가 아닙니다.'),
        ('- 기존 Counting Stars 관측 재사용: `RUN`. 새 CTC 강제 정렬: `NOT_RUN`. '
         if cached else '- 같은 입력·모델·설정의 저장 관측 재사용: `RUN`. 새 추론: `NOT_RUN`. '
         if reused else '- 새 ASR 1.7B 인식 + ForcedAligner 0.6B 단어 정렬: `RUN` (두 모델·입력·원시 인식 해시는 아래 이력 참조). '
         if heavy else '- 새 음성 강제 정렬: `RUN` (모델·입력 해시·설정은 아래 이력 참조). ') +
        '전체 WAV 청취 검증: `NOT_RUN`. 독립적인 파형/피치 경계 검증: `NOT_RUN`.',
        '- Synthesizer V Studio Pro 실제 열기: `NOT_RUN`. 보컬 합성·발음 재생: `NOT_RUN`.',
        f'- 음표 {len(rows)}개, UNKNOWN 음표 {len(unknown_notes)}개. TXT {len(lyrics)}단어 중 '
        f'{len(lyrics) - len(missing)}단어 배치, {len(missing)}단어 미배치, UNKNOWN 단어 {len(unknown_words)}개.',
        ('- 이 작업은 기존 음표의 \x60lyrics\x60만 입력합니다. 원본 \x60onset\x60·\x60duration\x60·'
         '\x60pitch\x60·\x60detune\x60, 음표 개수·배열 순서·그룹·오프셋·참조·템포·박자와 나머지 모든 '
         '프로젝트 필드는 그대로 유지합니다. 저장 시 가사 외 전체 필드의 원본 동일성을 별도로 검사합니다.'
         if lyrics_only else
         '- 원본 음표 개수·배열 순서·pitch·detune·참조·템포·박자와 허용 필드 외 프로젝트 정보는 '
         '저장 후 별도의 보존 검사 대상입니다. 이 보고서 생성 자체가 보존 검사 통과를 뜻하지 않습니다.'),
        '- TXT의 대소문자·철자·위치·반복은 단어 인덱스로 연결합니다. 원문 전체를 복원할 수 없는 '
        '단어는 미배치로 남깁니다. 음표가 부족해도 음표를 추가하거나 멜로디를 분할하지 않습니다.',
        *(['- ASR 1.7B는 제공 TXT를 정답 문장으로 입력하지 않고 WAV를 인식합니다. '
           'ForcedAligner 0.6B는 인식 문장의 단어 시간을 추정합니다. 제공 TXT가 최종 가사의 기준이며 '
           '인식문으로 교체하지 않습니다. 원문과의 단조·정확 대응이 없거나 반복 대응이 모호한 '
           '단어는 UNKNOWN으로 남깁니다. ASR 인식문과 모델 시각은 실제 가창의 정답이 아닙니다.'] if heavy else []),
        '- 영어 음절 수는 철자의 모음군과 기존 SVP의 `+` 표기를 보조 근거로 추정합니다. '
        '다음 음절은 `+`, 한 음절의 지속 후보는 `-`로 기록합니다. 여러 음절을 한 음표에 압축하면 '
        '원문 부분문자열을 사용하고, 내부 경계·압축·멜리스마는 청취 확인 전 UNKNOWN입니다.',
        ('- ALIGNED와 UNKNOWN 모두 원본 음표 시각을 유지합니다. WAV의 발음 시각은 가사와 음표를 '
         '대응하는 관측 자료이며, 음표의 위치나 길이에 적용하지 않습니다. '
         'ALIGNED는 자동 대응 상태이며 가창 검증 PASS가 아닙니다.'
         if lyrics_only else
         '- UNKNOWN 경계는 기존 시각을 유지합니다. 40 ms 미만 길이, 0.75초 초과 이동과 '
         '새 음표 겹침을 만드는 후보는 적용하지 않습니다. ALIGNED는 자동 대응 상태이며 가창 검증 PASS가 아닙니다.'),
        ('- 배치 품질: ' + ('자동 배치 완료 후보' if quality['placement_complete'] else '부분 초안')
         + f". 미대응 원문 유지 {quality['unresolved_notes']}음표, 배치 후 검토 필요 "
         + f"{quality['review_required_notes']}음표, 사용자 확인 {quality['confirmed_notes']}음표, "
         + f"기호 연결 이상 {quality['symbol_risks']}곳. 기술적 파일 저장과 가창 확인은 별도입니다."
         if quality['quality_known'] else
         '- 배치 품질: 이전 정책 자료로 세부 행동·기호 연결을 복원할 수 없어 미상입니다. 확인 완료로 승격하지 않습니다.'),
        '', '## 입력 및 새 분석 이력', '',
        '```json', json.dumps(dict(inputs=input_summary, analysis=provenance), ensure_ascii=False,
                              indent=2, default=str).replace('```', "'''"), '```',
        '', '## 100 ms 이상 기준점 오차', '',
        ('관측된 단어 범위와의 차이이며 음절 경계 오차나 발음 정확도의 측정이 아닙니다.' if word_only else
         '모델 문자 기준점과의 차이이며 독립적인 발음 정확도 측정이 아닙니다. '
         '양수는 음표가 후보보다 늦음을 뜻합니다. 종료 기준은 CTC가 제공한 문자 종료 후보입니다.'), '',
        ('| 음표 | 고정된 원본 시작 오차 ms | 고정된 원본 종료 오차 ms | 상태 |' if lyrics_only else
         '| 음표 | 시작 오차 전 → 후 ms | 종료 오차 전 → 후 ms | 상태 |'),
        '| ---: | --- | --- | --- |',
    ]
    if lyrics_only:
        lines.extend(f"| {row['note']} | {row['onset_error_before_ms']} | "
                     f"{row['end_error_before_ms']} | {row['assignment']} |" for row in large)
    else:
        lines.extend(f"| {row['note']} | {row['onset_error_before_ms']} → {row['onset_error_after_ms']} | "
                     f"{row['end_error_before_ms']} → {row['end_error_after_ms']} | {row['assignment']} |" for row in large)
    lines.extend(['', '## UNKNOWN 단어와 미배치', '',
                  '| 단어 인덱스 | TXT 행·열 | 원문 | 음표 | 후보 초 | 사유 |',
                  '| ---: | --- | --- | --- | --- | --- |'])
    lines.extend(f"| {row['word_index']} | {row['txt_line']}:{row['txt_column']} | {_cell(row['txt_word'])} | "
                 f"{row['note_numbers']} | {row['unknown_start_s']}–{row['unknown_end_s']} | {_cell(row['reason'])} |"
                 for row in unknown_words)
    lines.extend(['',
                  ('음표별 미확정 사유와 고정된 원본 시각·모델 후보 차이는 음표 비교 CSV, '
                   '전체 TXT 위치와 반복은 가사 검증 CSV를 참조하세요.' if lyrics_only else
                   '음표별 미확정 사유와 변경 전후 시각은 음표 비교 CSV, 전체 TXT 위치와 반복은 가사 검증 CSV를 참조하세요.'),
                  ''])
    return '\n'.join(lines)
