# Counting Stars GUI 가사·타이밍 검증

## 이번 작업

- 모드: 검증된 Counting Stars 입력과 기존 분석 자료로 결과 재생성.
- 기존 CTC 문자·단어 시각과 피치·파형 경계 관측 자료를 읽었습니다. 새 음성 분석은 실행하지 않았습니다.
- 원본 세 파일은 읽기 전용이며 출력 SVP는 별도 파일입니다.
- 원본 WAV: `E:\동영상_편집\AI_커버\OneRepublic - Counting Stars 힝구\1_OneRepublic - Counting Stars_(Vocals).wav`.
- 기존 SVP 연결 오디오: `E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구/1_1_1_OneRepublic - Counting Stars_(Vocals)_(Vocals)_(No Reverb).wav`. 기존 경로 문자열을 보존했습니다.

## 검증 상태

| 검사 | 상태 | 근거 |
| --- | --- | --- |
| SVP 재파싱 | PASS | 초안을 다시 읽어 JSON과 원본 널 접미사 확인 |
| 멜로디·프로젝트 보존 | PASS | 음표 ID·개수·순서·pitch·detune와 허용 필드 외 전체 필드 비교 |
| 가사 순서·반복 | PASS | 배치된 가사와 음절 대응을 기준 TXT의 순서로 역검증 |
| 입력·기존 분석 자료 SHA-256 | PASS | 고정 프로필과 일치 확인 |
| 새 WAV 분석 | NOT_RUN | 1차 GUI는 기존 관측 자료를 재사용 |
| 이번 작업에서 전체 WAV 청취 | NOT_RUN | 자동 결과 생성 범위에 청취 검증이 없음 |
| Synthesizer V Studio Pro 실제 열기 | NOT_RUN | 이번 GUI 작업에서 실행하지 않음 |
| 보컬 합성·재생 | NOT_RUN | Synthesizer V에서 별도 검토 필요 |
| 가창 정렬 전체 판정 | NOT_VERIFIED | 미확정 발음·경계와 실제 합성 검토가 남음 |

## 결과와 미확정 구간

- 음표 715개, TXT 527단어 중 515단어 배치, 12단어 미배치.
- 음표 UNKNOWN 183개, 가사 UNKNOWN 158단어.
- 기존 기준점 대비 시작: 249개, 절대 오차 중앙값 25.0 → 0.0 ms, 100 ms 이상 24 → 0개.
- 기존 기준점 대비 독립적인 종료: 11개, 절대 오차 중앙값 60.0 → 0.0 ms, 100 ms 이상 2 → 0개.
- 이 통계는 편집에 사용한 기존 관측 기준점과의 차이입니다. 새로 측정한 정렬 정확도가 아닙니다.
- 확인 근거가 부족한 시작·끝은 기존 시각을 유지했습니다. 세부 근거는 음표 비교 CSV와 가사 검증 CSV에 있습니다.

| TXT 행 | 미배치 단어 | WAV 후보 초 | 사유 |
| ---: | --- | --- | --- |
| 36 | but | 125.798–125.925 | 1절 반복의 동일 파형과 MIDI 56 유성음이 있으나 2절 원본은 해당 시간에 음표가 없음 |
| 37 | but | 127.778–127.905 | 1절 반복의 동일 파형과 MIDI 56 유성음이 있으나 2절 원본은 해당 시간에 음표가 없음 |
| 46 | But | 156.245–156.34 | 대응 후렴에서 예상되는 시각의 에너지가 낮고 유성 피치와 독립 음표가 없음 |
| 54 | And | 184.85–184.93 | 독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지 |
| 56 | And | 188.77–188.85 | 독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지 |
| 58 | And | 192.69–192.78 | 독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지 |
| 60 | And | 196.59–196.69 | 독립 인식은 접속사를 생략하고 해당 음표는 money의 끝 음절을 지지 |
| 66 | But | 214.27–214.35 | 대응 후렴에서 예상되는 시각의 에너지가 낮고 유성 피치와 독립 음표가 없음 |
| 74 | And | 238.89–239.03 | 두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침 |
| 76 | And | 242.81–242.95 | 두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침 |
| 78 | And | 246.75–246.89 | 두 CTC 모델 모두 접속사를 생략한 전사가 더 적합. 아웃트로는 보컬 레이어가 겹침 |
| 80 | And | 250.59–250.82 | 독립 인식은 엇갈리며 두 CTC 모델 모두 접속사를 생략한 전사가 더 적합 |

## 입력·관측 자료 이력

| 입력 | SHA-256 |
| --- | --- |
| E:\동영상_편집\AI_커버\OneRepublic - Counting Stars 힝구\OneRepublic - Counting Stars 여자 커버.svp | 5a5a89cf05140ad42f39aaaa1837bd4fee634b5a1f1ca6559394e2d761f8c82a |
| E:\동영상_편집\AI_커버\OneRepublic - Counting Stars 힝구\OneRepublic - Counting Stars.txt | 077027714e053f328a86c41ef481441bf8c613486508a4a1b2f0d351607bb366 |
| E:\동영상_편집\AI_커버\OneRepublic - Counting Stars 힝구\1_OneRepublic - Counting Stars_(Vocals).wav | f17de82652e85baaf7a7ac08d774c8dbcdc7fcc692d207e0c99e94e7ce986456 |

| 기존 관측 자료 | SHA-256 |
| --- | --- |
| work/acoustic/en_ctc_words.json | 1617aa87be4b284fcec9f1232ea63652252234d1d71c363d9a290ed3d4b44e89 |
| work/acoustic/mms_ctc_words.json | 7985a8f2558083bad528bc422e39a1784e0ea33ac2bb3b27bf5bae375cb63112 |
| work/pitch/pitch_boundary_candidates.csv | 43372e398d9676affaa32317a596d38cb04f94200cc93f6953e440cd06bd690b |
| work/pitch/source_frames.csv | 5bd33339635d8de6d4aeadde2de6f21484321d35d9edb78a3071c64e7a514b6d |
- Existing observations are reused; no new WAV analysis or listening verification is performed.
- Selected filenames differ from AGENTS.md contract names. Their contents passed the fixed profile SHA-256 check; filenames were preserved.
