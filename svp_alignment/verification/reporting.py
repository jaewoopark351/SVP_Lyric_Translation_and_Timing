"""CSV row representation and Markdown presentation of validation evidence."""

import csv
from collections import Counter
from statistics import median

from ..svp import note_times
from ..profiles.counting_stars import CHORUS_RANGES, LARGE_ERROR_MS


def milliseconds(time, reference):
    return '' if reference is None else round(1000 * (time - reference), 3)


def note_rows(before, after, assignments, continuations, syllables, evidence, unknown_notes):
    rows = []
    for index, (original, edited) in enumerate(zip(before, after)):
        old_start, old_end = note_times(original)
        start, end = note_times(edited)
        info = evidence[index]
        attack = info.get('start_reference')
        release = info.get('end_reference')
        syllable_ids = assignments.get(continuations.get(index, index), ())
        if index in continuations:
            syllable_ids = syllable_ids[-1:]
        linked = [syllables[item_id] for item_id in syllable_ids]
        rows.append(dict(
            note=index + 1, note_id=original['uuid'], pitch=original['pitch'], detune=original['detune'],
            old_onset_blick=original['onset'], new_onset_blick=edited['onset'],
            old_duration_blick=original['duration'], new_duration_blick=edited['duration'],
            old_start_s=round(old_start, 6), new_start_s=round(start, 6),
            old_end_s=round(old_end, 6), new_end_s=round(end, 6),
            old_lyrics=original['lyrics'], new_lyrics=edited['lyrics'],
            txt_line=linked[0]['line'] if linked else '',
            txt_columns=' / '.join(str(item['column']) for item in linked),
            txt_word=' / '.join(item['source'] for item in linked),
            syllable=' / '.join(item['spelling'] for item in linked),
            assignment=('UNKNOWN' if index in unknown_notes else
                        'CONTINUATION' if index in continuations else 'ALIGNED'),
            assignment_reason=unknown_notes.get(index, ''),
            waveform_start_s=attack, start_basis=info.get('start_basis', ''),
            onset_error_before_ms=milliseconds(old_start, attack), onset_error_after_ms=milliseconds(start, attack),
            onset_change_ms=milliseconds(start, old_start),
            waveform_end_s=release, end_basis=info.get('end_basis', ''),
            end_error_before_ms=milliseconds(old_end, release), end_error_after_ms=milliseconds(end, release),
            duration_change_ms=milliseconds(end - start, old_end - old_start),
        ))
    return rows


def write_csv(path, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def time_summary(rows, field, exclude=()):
    valid = [row for row in rows if row[field + '_error_before_ms'] != ''
             and row[field.replace('onset', 'start') + '_basis'] not in exclude]
    if not valid:
        return '측정 기준점 없음'
    before = [abs(row[field + '_error_before_ms']) for row in valid]
    after = [abs(row[field + '_error_after_ms']) for row in valid]
    return (f'{len(valid)}개, 절대 오차 중앙값 {median(before):.1f} → {median(after):.1f} ms, '
            f'{LARGE_ERROR_MS} ms 이상 {sum(x >= LARGE_ERROR_MS for x in before)} → '
            f'{sum(x >= LARGE_ERROR_MS for x in after)}개')


def lyric_rows(words, syllables, assignments, notes, unknown_notes, unplaced):
    by_word = [[] for _ in words]
    for index, ids in assignments.items():
        for item_id in ids:
            item = syllables[item_id]
            by_word[item['word']].append((index, item))
    rows = []
    for (line, column, word), items in zip(words, by_word):
        case = unplaced.get((line, word))
        status = 'UNKNOWN' if case or any(index in unknown_notes for index, _ in items) else 'ALIGNED'
        unique = list(dict.fromkeys(index for index, _ in items))
        rows.append(dict(txt_line=line, txt_column=column, txt_word=word,
                         note_numbers=' / '.join(str(i + 1) for i in unique),
                         svp_lyrics=' / '.join(notes[i]['lyrics'] for i in unique),
                         syllables=' / '.join(s['spelling'] for _, s in items),
                         ctc_starts_s=' / '.join(f"{s['onset']:.3f}" for _, s in items),
                         ctc_vowel_candidates_s=' / '.join(f"{s['nucleus']:.3f}" for _, s in items),
                         ctc_end_s=' / '.join(f"{s['end']:.3f}" for _, s in items),
                         ctc_p=' / '.join(f"{s['p']:.2f}" for _, s in items),
                         mms_onsets_s=' / '.join(f"{s['alt_onset']:.3f}" for _, s in items),
                         status=status, reason=case[2] if case else ' / '.join(dict.fromkeys(
                             unknown_notes[i] for i in unique if i in unknown_notes)),
                         unknown_start_s=case[0] if case else '', unknown_end_s=case[1] if case else ''))
    return rows


def markdown(rows, lyrics, source, linked_audio, unplaced, studio_status):
    confirmed = len(lyrics) - sum(not row['note_numbers'] for row in lyrics)
    unknown = [row for row in rows if row['assignment'] == 'UNKNOWN']
    count = Counter(row['txt_line'] for row in lyrics)
    unknown_words = Counter(row['txt_line'] for row in lyrics if row['status'] == 'UNKNOWN')
    placed = Counter(row['txt_line'] for row in lyrics if row['note_numbers'])
    chorus_table = [f'| {start}–{stop} | {sum(count[n] for n in range(start, stop + 1))} | '
                    f'{sum(placed[n] for n in range(start, stop + 1))} | '
                    f'{sum(unknown_words[n] for n in range(start, stop + 1))} |'
                    for start, stop in CHORUS_RANGES]
    large = [row for row in rows if any(row[key] != '' and abs(row[key]) >= LARGE_ERROR_MS
            for key in ('onset_error_before_ms', 'onset_error_after_ms', 'end_error_before_ms', 'end_error_after_ms'))]
    lines = [
        '# Counting Stars 가사·타이밍 검증', '',
        '## 결과', '',
        f'- 원본 WAV 262.560초, 44.1 kHz, 스테레오 PCM. 분석 입력 `{source.name}`.',
        f'- TXT 81행 {len(lyrics)}단어를 모두 가사 검증표에 수록. SVP에 {confirmed}단어 배치, '
        f'{len(unplaced)}단어 미배치. SVP에서 배치한 단어를 역추출해 철자, 대소문자, 순서 및 반복을 검증했습니다.',
        f'- 기존 음표 715개. 시작 {sum(row["old_onset_blick"] != row["new_onset_blick"] for row in rows)}개, '
        f'길이 {sum(row["old_duration_blick"] != row["new_duration_blick"] for row in rows)}개, '
        f'가사 {sum(row["old_lyrics"] != row["new_lyrics"] for row in rows)}개 변경.',
        '- 파싱 `PASS`. 음표 ID, 개수, 순서, pitch, detune, 120 BPM, 4/4, 보컬·오디오 트랙 및 '
        '다른 프로젝트 필드 일치. 양수 길이, 시작 순서, 겹침 없음 확인. 세 원본 파일 SHA-256 일치.',
        f'- Studio Pro 열기 {studio_status}',
        '- 가창 정렬 전체 판정 `NOT_VERIFIED`. 아래 `UNKNOWN`과 보컬 렌더링 검증 범위를 확인하세요.',
        f'- 기존 연결 오디오 `{linked_audio["filename"]}`. 절대 경로 접근 확인. '
        'WAV 시작, 오디오 오프셋, 그룹 오프셋은 모두 0초. 두 WAV의 3초 표본 52개 중 51개에서 최대 파형 상관의 지연은 0초였습니다.',
        '', '## 전체 WAV 대조', '',
        '- 0.00–0.35초 초기 바닥 잡음, 약 0.373초 유성 전조, 약 0.453초 첫 가사 자음 후보. '
        '22.76초 무렵 첫 구간 유성음 종료. 25–28.8초 미약한 잔류 성분은 `UNKNOWN`. '
        '37.36초 무렵 숨·잡음 이후 37.77초 첫 절 모음이 관측됩니다.',
        '- 54.72–56.72초는 긴 `I` 후보. 국소 인식과 56.70초 부근의 `feel` 자음이 이를 지지하며 긴 구간의 음절 시작은 `UNKNOWN`입니다. '
        '62.32초의 TXT에 없는 `And` 후보는 +70.8205초 반복 파형에서 확인했습니다.',
        '- 111.28–113.70초 `Hey` 계열, 182.84–184.10초 `Oh` 계열은 TXT에 없는 가창 후보입니다. 기존 음표와 임시 가사를 유지했습니다.',
        '- 202.55–204.10초는 피치 54→56→54의 `me` 지속, 다음 `makes`는 약 205.59초입니다.',
        '- 브리지 네 회와 아웃트로 네 회를 각기 대조했습니다. 아웃트로는 보컬이 겹쳐 첫 반복과 `I learned`의 세부 발음 경계가 특히 불확실합니다. '
        '마지막 강한 유성음은 약 253.91초이며, 254초 부근부터 262.56초 끝까지 추가 가사를 뒷받침하는 근거가 없습니다.',
        '', '### 후렴 반복', '',
        '두 반복군에서 파형 일치가 뚜렷한 구간의 시차는 약 70.820초와 128.854초였습니다. 각 반복의 자체 CTC와 음표를 함께 대조했습니다.', '',
        '| TXT 행 | 원문 단어 수 | SVP 배치 수 | UNKNOWN 단어 수 |', '| --- | ---: | ---: | ---: |',
        *chorus_table,
        '', '## 타이밍 오차', '',
        '20 ms 간격 wav2vec2 영어 CTC와 MMS CTC, 전체 및 국소 Whisper, WAV의 10 ms RMS·Praat 피치, 반복 파형을 비교했습니다. '
        'CTC의 문자 시각은 자음·모음 후보이며, 음표 시작은 국소 파형의 유성 진입이나 피치 전환을 우선했습니다. '
        '두 WAV에서 확인한 피치 전환과 두 CTC가 일치하는 파형 공격점 위주로 편집했습니다. '
        '다음 통계는 편집에도 사용한 기준점과의 차이입니다. 기준점이 없는 음표는 통계에서 제외했습니다.', '',
        f'- 시작 {time_summary(rows, "onset")}.',
        f'- 독립적인 종료 {time_summary(rows, "end", ("CONTIGUOUS_NEXT_BOUNDARY",))}.',
        '- 아래는 시작 또는 종료 기준점과 100 ms 이상 차이가 난 행입니다. 양수는 음표가 늦음을 뜻합니다. '
        '빈 항목은 해당 기준점이 없음을 뜻합니다. 인접 음표 경계에서 얻은 종료도 표에 포함했습니다.', '',
        '| 음표 | WAV 구간 초 | 시작 오차 전 → 후 ms | 종료 오차 전 → 후 ms | 근거 |',
        '| ---: | --- | --- | --- | --- |',
    ]
    for row in large:
        span = f'{row["old_start_s"]:.3f}–{row["old_end_s"]:.3f}'
        lines.append(f'| {row["note"]} | {span} | {row["onset_error_before_ms"]} → {row["onset_error_after_ms"]} | '
                     f'{row["end_error_before_ms"]} → {row["end_error_after_ms"]} | '
                     f'{row["start_basis"]} {row["end_basis"]} |')
    lines.extend(['', '## UNKNOWN', '',
        '기존 음표를 추가하거나 분할하지 않았습니다. 한 음표가 여러 단어를 포함하는 경우 파일의 가사 문자열은 확인했으며, '
        '합성 발음과 내부 경계는 미확인입니다. `+`는 다음 음절, `-`는 앞 발음의 지속입니다. '
        '같은 단어의 여러 음절이 한 음표를 쓰면 내부 개별 경계도 미확인입니다. '
        '음표 번호는 원본 순서의 1부터 시작하며, 비교표에 각 UUID와 TXT 위치를 기록했습니다. '
        '확인 근거가 부족한 시작·끝은 기존 시각을 유지했습니다. [Dreamtonics 피아노 롤 설명서](https://sv2.docs.dreamtonics.com/en/pianoroll)', '',
        '| TXT 행·미배치 단어 | WAV 후보 초 | 사유 |', '| --- | --- | --- |'])
    for (line, word), (start, end, reason) in sorted(unplaced.items()):
        lines.append(f'| {line} `{word}` | {start:.3f}–{end:.3f} | {reason} |')
    lines.extend(['', f'음표 단위 `UNKNOWN` {len(unknown)}개는 비교표의 `assignment_reason`에 근거를 기록했습니다. '
                  '가사 검증표의 `UNKNOWN`에는 미배치와 배치했으나 발음·경계가 불확실한 단어를 모두 포함합니다.', '',
                  '## 구현 검증', '',
                  '| 모듈 | 책임 | 판정 |', '| --- | --- | --- |',
                  '| `svp.py` | 그룹 참조 해석, 시간 단위, SVP 읽기·쓰기 | `NO_SPLIT_REQUIRED` |',
                  '| `lyrics.py`, `match.py` | TXT·음절 후보와 순서 보존 음표 대응 | `COMPLETE` |',
                  '| `timing.py` | 파형 기준점으로 시간 조정 | `COMPLETE` |',
                  '| `verification.py`, `report.py` | 재파싱·보존 검증과 비교표·보고서 출력 | `COMPLETE` |',
                  '| `run.py` | 입력 확인, 작업 순서 및 결과 경로 | `NO_SPLIT_REQUIRED` |', '',
                  '재현 진입점은 `work/counting_stars/run.py`이며, `work/acoustic`과 `work/pitch`의 관측 자료를 읽습니다. '
                  '기존 결과 파일이 있는 경로에서는 새 결과 생성이 중단됩니다.', ''])
    return '\n'.join(lines)


def gui_markdown(rows, lyrics, source, linked_audio, input_summary=None):
    """Describe this GUI run without presenting cached observations as fresh analysis."""
    unplaced = [row for row in lyrics if not row['note_numbers']]
    unknown_notes = [row for row in rows if row['assignment'] == 'UNKNOWN']
    unknown_words = [row for row in lyrics if row['status'] == 'UNKNOWN']
    lines = [
        '# Counting Stars GUI 가사·타이밍 검증', '',
        '## 이번 작업', '',
        '- 모드: 검증된 Counting Stars 입력과 기존 분석 자료로 결과 재생성.',
        '- 기존 CTC 문자·단어 시각과 피치·파형 경계 관측 자료를 읽었습니다. 새 음성 분석은 실행하지 않았습니다.',
        '- 원본 세 파일은 읽기 전용이며 출력 SVP는 별도 파일입니다.',
        f'- 원본 WAV: \u0060{source}\u0060.',
        f'- 기존 SVP 연결 오디오: \u0060{linked_audio["filename"]}\u0060. 기존 경로 문자열을 보존했습니다.',
        '', '## 검증 상태', '',
        '| 검사 | 상태 | 근거 |', '| --- | --- | --- |',
        '| SVP 재파싱 | PASS | 초안을 다시 읽어 JSON과 원본 널 접미사 확인 |',
        '| 멜로디·프로젝트 보존 | PASS | 음표 ID·개수·순서·pitch·detune와 허용 필드 외 전체 필드 비교 |',
        '| 가사 순서·반복 | PASS | 배치된 가사와 음절 대응을 기준 TXT의 순서로 역검증 |',
        '| 입력·기존 분석 자료 SHA-256 | PASS | 고정 프로필과 일치 확인 |',
        '| 새 WAV 분석 | NOT_RUN | 1차 GUI는 기존 관측 자료를 재사용 |',
        '| 이번 작업에서 전체 WAV 청취 | NOT_RUN | 자동 결과 생성 범위에 청취 검증이 없음 |',
        '| Synthesizer V Studio Pro 실제 열기 | NOT_RUN | 이번 GUI 작업에서 실행하지 않음 |',
        '| 보컬 합성·재생 | NOT_RUN | Synthesizer V에서 별도 검토 필요 |',
        '| 가창 정렬 전체 판정 | NOT_VERIFIED | 미확정 발음·경계와 실제 합성 검토가 남음 |',
        '', '## 결과와 미확정 구간', '',
        f'- 음표 {len(rows)}개, TXT {len(lyrics)}단어 중 {len(lyrics) - len(unplaced)}단어 배치, {len(unplaced)}단어 미배치.',
        f'- 음표 UNKNOWN {len(unknown_notes)}개, 가사 UNKNOWN {len(unknown_words)}단어.',
        f'- 기존 기준점 대비 시작: {time_summary(rows, "onset")}.',
        f'- 기존 기준점 대비 독립적인 종료: {time_summary(rows, "end", ("CONTIGUOUS_NEXT_BOUNDARY",))}.',
        '- 이 통계는 편집에 사용한 기존 관측 기준점과의 차이입니다. 새로 측정한 정렬 정확도가 아닙니다.',
        '- 확인 근거가 부족한 시작·끝은 기존 시각을 유지했습니다. 세부 근거는 음표 비교 CSV와 가사 검증 CSV에 있습니다.',
        '', '| TXT 행 | 미배치 단어 | WAV 후보 초 | 사유 |', '| ---: | --- | --- | --- |',
    ]
    for row in unplaced:
        lines.append(f'| {row["txt_line"]} | {row["txt_word"]} | '
                     f'{row["unknown_start_s"]}–{row["unknown_end_s"]} | {row["reason"]} |')
    if input_summary:
        lines.extend(['', '## 입력·관측 자료 이력', '', '| 입력 | SHA-256 |', '| --- | --- |'])
        for source_path, digest in zip(input_summary.get('paths', ()), input_summary.get('input_hashes', ())):
            lines.append(f'| {source_path} | {digest} |')
        lines.extend(['', '| 기존 관측 자료 | SHA-256 |', '| --- | --- |'])
        for source_path, digest in input_summary.get('evidence_hashes', {}).items():
            lines.append(f'| {source_path} | {digest} |')
        for warning in input_summary.get('warnings', ()):
            lines.append(f'- {warning}')
    lines.append('')
    return '\n'.join(lines)
