# ASR 1.7B와 단어 정렬 모델 비교 실험

2026-11-15 사용자 요청으로 더 큰 음성 인식 모델을 선택하는 경로를 추가했다. 기존 [가사 배치 개선](lyrics-placement-improvement-plan.md)의 `word_note_groups_v1`과 음표 고정 계약을 유지하며, 모델 관측의 출처와 결과를 구분한다. 이전 자동·수동 SVP와 기존 결과를 덮어쓰지 않는다.

**Run Boy Run의 이번 실제 시험에서는 기존 Large보다 배치 결과가 나빠졌다.** 미배치가 6개에서 78개로 늘었고 미대응 음표에는 원본 `la`가 유지됐다. 무거운 조합은 비교용 명시 선택으로 제공하고 영어 자동 기본값은 Large로 유지한다. 모델 크기가 충분하다는 사실이 가창의 단어 시각·음표 대응 개선을 보장하지 않는다.

## 선택과 처리 방식

GUI의 **AI 정렬 모델**에서 **Qwen3 ASR 1.7B + ForcedAligner 0.6B**를 직접 선택하고 입력 검사를 다시 실행한다. 자동 선택은 영어 Large·지원 비영어 Qwen 강제 정렬을 그대로 사용하며 무거운 경로를 자동으로 고르지 않는다. 설치된 `qwen-asr==0.0.6`과 같은 `.venv`를 사용한다. 다른 모델이나 언어를 선택한 작업과 관측 캐시를 혼용하지 않는다.

1. `Qwen/Qwen3-ASR-1.7B`가 업로드 WAV를 인식한다. 제공 TXT를 인식 정답 문장으로 넣지 않는다.
2. `Qwen/Qwen3-ForcedAligner-0.6B`가 **인식 문장**의 단어 시간 범위를 추정한다.
3. 원문 TXT와 인식 단위를 전체 순서에 따라 대응한다. 정확한 단조 대응이 없거나 반복 위치가 모호한 TXT 단어는 UNKNOWN으로 보류한다. 비슷한 단어의 시각을 임의로 빌리거나 인식문으로 TXT를 교체하지 않는다.
4. 지원되는 원문 단어 시각으로 기존 연속 음표에 가사를 배치한다. 미배치·배치 후 검토와 사용자 확인을 별도로 표시한다.

이 조합의 선택 ID는 `Qwen/Qwen3-ASR-1.7B+ForcedAligner-0.6B`다. ASR 1.7B는 음성 인식 모델이고 0.6B는 주어진 문장의 단어 시각을 추정하는 모델이다. 두 숫자를 합친 하나의 강제 정렬 모델로 설명하지 않는다. [공식 모델별 역할](https://github.com/QwenLM/Qwen3-ASR#released-models-description-and-download), [ASR 1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), [ForcedAligner 0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B).

단어 시각만 제공하며 문자·음절 시작 시각과 CTC 확률은 제공하지 않는다. `p=None`, `chars=[]`, `alignment_unit="word"`, `score_unavailable=True`로 기록한다. CSV의 CTC 시작·종료·확률 열은 비워 두고 `observed_word_start_s`·`observed_word_end_s`를 사용한다. ASR이 인식한 문장과 단어 시각은 실제 가창의 정답이 아니며, 관측이 달라졌다는 사실만으로 배치 정확도 향상을 확정하지 않는다.

## 원본과 검토 계약

최종 가사의 기준은 제공 TXT의 철자·위치·순서·반복이다. **기존 음표의 `lyrics`만 변경**하며 `onset`·`duration`·`pitch`·개수·순서·ID·템포·트랙·오디오 경로 및 나머지 JSON 값과 타입을 보존한다. 초안과 출력 SVP를 다시 읽어 엄격한 동일성 검사를 수행한다. 음표가 없는 WAV 말미의 단어를 넣기 위해 새 음표를 만들거나 기존 음표를 이동하지 않는다.

미배치가 줄어도 주변 단어의 경계가 옳다는 뜻은 아니다. 같은 SVP·TXT·WAV로 이전 Large 결과와 비교하고 미배치, 반복 단어 위치, 단어 시작이 한 음표 빠른 지점, `+`·`-` 연결, 최종 발음 시각을 검토한다. 내부 음절·지속음은 단어 범위만으로 확정할 수 없으므로 UNKNOWN을 유지한다. 청취·Studio 열기·합성 검증은 기술적 파일 저장과 별도이며 전체 가창 판정은 `NOT_VERIFIED`다.

## 이력과 원시 관측

작업별 이력은 선택 ID와 실제 ASR·정렬 모델 ID, 두 구성 요소의 revision·가중치 파일 해시, 입력 해시·설정·실제 장치·패키지 버전을 기록한다. ASR revision은 `7278e1e70fe206f11671096ffdd38061171dd6e5`, 정렬 모델 revision은 `1c85775dfe71a2a90e6aeea682c6eb9df3d8848b`다. ASR 캐시는 `work/models/qwen-asr/<revision>/`, 정렬 캐시는 기존 `work/models/qwen/<revision>/`를 사용한다. 두 snapshot을 묶은 해시를 별도로 계산하고 둘 중 하나라도 달라지면 다른 모델 관측으로 취급한다. 다운로드 완료·파일 해시 검증·실제 추론은 별도 검사다.

이력의 `method`는 `QWEN_ASR_REFERENCE_ALIGNMENT`, `model_components`는 두 모델의 고정 ID·revision·가중치 해시를 기록한다. `recognition` 메타데이터는 `asr_model_id`, `aligner_model_id`, `recognized_text`, `recognized_language`, `recognized_word_count`, `source_word_count`, `matched_word_count`, `unmatched_word_count`, `ambiguous_word_count`, `invalid_observation_word_count`를 포함한다. `recognized_word_count`는 SDK가 반환한 원시 단위 수이며 영문 단어 수라고 단정하지 않는다. 인식문과 원시 단어 범위는 원문 대응 전에 저장하고 `raw_observations_path`·`raw_observations_sha256`으로 연결한다. 원시 관측의 `source`는 `official-qwen-asr-returned-items-before-reference-mapping`이며 각 단위의 `text`, `start_time`, `end_time`를 보존한다. `backend`, `qwen_asr_version`, `timestamp_chunk_seconds`도 실제 런타임 값으로 기록한다.

생성 설정은 `max_new_tokens=4096`, `max_inference_batch_size=1`이다. 최초 실행에는 ASR 가중치를 추가로 다운로드한다. 앱 입력 제한은 단독 Qwen과 동일하게 300초다. 설치된 `qwen-asr==0.0.6`의 timestamp 경로는 최대 180초 단위로 나누어 처리하고 전역 시각으로 합친다. 따라서 214초 Run Boy Run도 SDK 내부에서 나뉘며 앱이 미검증 긴 곡의 지원 범위를 자동 확대하지 않는다. TXT 대응은 합친 인식문 문자열을 다시 나누는 대신 반환된 timestamp 단위를 사용한다. 실행 시간·GPU 메모리와 가창 품질은 실제 입력에 따라 검증한다. 선택한 모델 실패 시 다른 모델로 조용히 바꾸지 않는다.

## 책임 경계

파일 이동 없이 새 책임은 기존 `audio/`에 배치했다. 경로는 프로젝트 루트 기준이며, 기존 CTC·단독 Qwen·CLI·초안 교정 API를 보존한다. 구조 판정은 실제 담당자와 호출·수명 경계에 대한 소스·집중 검사 근거이며, 아래 실제 추론·가창 검증과 별개다.

| 변경 전 담당자와 소스 근거 | 책임과 배치 | 변경 후 담당자와 실제 경로 | 상태·쓰기·수명 이전 | 호출자·호환성·검증 | 남은 책임과 판정 |
| --- | --- | --- | --- | --- | --- |
| `audio/model_catalog.py`의 Base/Large/MMS/단독 Qwen 선택 | 무거운 조합의 명시 선택·언어 정책 | [audio/model_catalog.py](../svp_alignment/audio/model_catalog.py) | 식별·선택 목록만 소유. 자동 선택과 이전 작업 복원 정책 유지 | 입력 검사·worker·UI가 같은 선택값 사용. 자동 기본값 유지·이전 작업 선택 복원 검사 | NO_SPLIT_REQUIRED — 기존 모델 선택 책임에 응집 |
| 기존 `audio/models.py`·`qwen_cache.py`의 단일 모델 캐시 | ASR snapshot의 고정 revision·파일 무결성·원자 게시 | [audio/asr_cache.py](../svp_alignment/audio/asr_cache.py), [models.py](../svp_alignment/audio/models.py) | ASR 파일 해시·snapshot 게시·시도별 다운로드 정리. 기존 정렬 snapshot은 재사용하고 덮어쓰지 않음 | models는 새 담당자에 위임. 캐시 고정·손상·다운로드 정리 집중 검사, 기존 모델 캐시 유지 | COMPLETE — ASR snapshot 쓰기·수명 소유자를 분리 |
| 새 조합 모델과 기존 단일 Path 모델 API | 양 구성 요소의 불변 식별·캐시 뷰·통합 해시 | [audio/heavy_bundle.py](../svp_alignment/audio/heavy_bundle.py) | 새 폴더·상태 manifest를 소유하지 않음. ASR·정렬 snapshot 담당자에 위임하고 두 구성의 해시를 함께 결합 | models·worker·alignment가 조합일 때만 두 경로 dict 사용. 기존 단일 모델 Path API·양 구성 서명 검사 | COMPLETE — 조합 식별의 새 경계와 호출 확인 |
| `audio/models.py::digest_file`을 `qwen_cache.py`가 되가져오는 지연 import | 모델 파일 바이트의 공통 SHA-256 계산 | [audio/model_fingerprint.py](../svp_alignment/audio/model_fingerprint.py) | 정확한 함수 출발은 `audio/models.py::digest_file`, 도착은 `audio/model_fingerprint.py::digest_file`. 읽기 전용 해시 계산이며 모델·캐시·다운로드 상태 없음 | models가 같은 이름으로 의도적으로 재노출해 기존 import·mock 경로 유지. qwen_cache는 새 담당자 직접 참조. 새 bundle→qwen_cache→models→bundle 순환을 제거 | COMPLETE — 공통 계산 담당자를 분리, 기존 공개 API 보존 |
| `audio/qwen_inference.py`의 제공 TXT 강제 정렬 | WAV ASR 인식·인식 문장 정렬·원시 관측 전달 | [audio/asr_inference.py](../svp_alignment/audio/asr_inference.py) | worker 내부 모델·장치·텐서 수명과 원시 관측 쓰기 소유. 다른 모델로 자동 대체하지 않음 | 기존 `align_words` 공통 관측 형식 유지. TXT 미전달·원시 결과·OOM 재시도·정리 집중 검사 | COMPLETE — ASR 모델 자원·원시 관측 담당자를 분리 |
| 새 ASR 관측과 최종 TXT의 대응 요구 | 전체 순서·정확 대응과 모호성 판정 | [audio/asr_reference.py](../svp_alignment/audio/asr_reference.py) | 순수 계산. 파일·모델·작업 상태를 소유하지 않음. 미대응·모호성은 UNKNOWN | 추론 담당자가 호출, 원문 토큰·반복 순서 보존. 동률·미일치·잘못된 시각 경계 검사 | COMPLETE — 모델 자원과 순수 대응 정책을 분리 |
| 기존 `audio/worker.py`·`alignment.py`의 프로세스·서명 | 조합 모델이 고정된 추론 수명·캐시 이력 | [audio/worker.py](../svp_alignment/audio/worker.py), [alignment.py](../svp_alignment/audio/alignment.py) | 기존 PID·취소·잠금·시도별 작업 소유권 유지. 이력에 양 모델과 원시 관측 연결 | 기존 Base/Large/MMS/단독 Qwen·취소·복원 계약 유지. 원시 파일 해시 불일치 캐시 거절 검사 | NO_SPLIT_REQUIRED — 기존 프로세스·관측 게시 책임에 위임 추가 |
| 보고서의 단독 Qwen 분기·UI의 강제 정렬 문구 | 두 단계 모델의 관측 한계와 TXT 기준 표시 | [verification/general_reporting.py](../svp_alignment/verification/general_reporting.py), [ui/presentation.py](../svp_alignment/ui/presentation.py), [gradio_app.py](../svp_alignment/ui/gradio_app.py) | 기존 읽기 전용 표현 책임 유지. 저장 관측 재사용과 새 추론을 구분. 교정 상태를 변경하지 않음 | CSV 기존 열 유지·가짜 CTC 점수 방지, GUI 기본값·콜백 계약 유지. 새 분기·앱 구성 포함 집중 46개 통과 | NO_SPLIT_REQUIRED — 표현 경계 유지·이전 API 호환 확인 |

## 검증 기록

이번 확장 전 기준은 전체 205개 회귀 검사 통과다. 새 코드의 집중·전체 검사와 실제 GPU 실행 결과는 이 절에 별도로 기록하며, 과거 테스트·과거 CUDA 실행을 새 모델의 검증으로 합산하지 않는다. 가창 정확도는 `NOT_VERIFIED`이며 이번 곡의 자동 배치 지표는 기존 Large보다 나빠졌다.

| 검사 | 결과와 근거 |
| --- | --- |
| ASR 가중치 다운로드·무결성 | PASS — 고정 revision의 10개 모델 파일 4,703,055,333 bytes. 두 가중치 shard 합계 4,698,521,512 bytes이며 각각 공개 SHA-256 대조. snapshot fingerprint `cdcb5bddccc40aa119b6f00fb9ed32ab1f720fc12beadfc41438a35c9d697d0e` |
| 보고서·표시·기존 배치 집중 검사 | PASS — `tests/test_heavy_reporting.py` 신규 4개, 기존 일반 배치 37개·GUI 표시 5개를 함께 실행해 46개 통과, 0.280초. ASR+FA 구분·가짜 문자/점수 없음·재사용 표시·기존 화면 계약 확인 |
| 원문 대응 집중 검사 | PASS — 12개, 0.002초. 정확 순서·반복·오인식·미대응·동률·잘못된 시각·단위 병합·문자 시각 미생성 확인. 독립 전수 비교 3,400경우·최적 경로 12,826개도 통과 |
| ASR 실행·캐시 경계 집중 검사 | PASS — 10개, 0.117초. TXT 미전달·모델 구성·원시 관측·OOM 재시도·정리·제한 검증. 실제 GPU 추론과 별도 |
| 파일 지문 분리·이전 API 호환 | PASS — 집중 6개, 0.562초. `models.digest_file` 재노출 동일성과 다중 블록 바이트 해시·기존 Qwen 캐시/실패 정리 확인 |
| 정적 구조·일반 진입점 로딩 | PASS — 프로덕션/app Python 64개 AST·compile, 최상위 공개 프로젝트 클래스 파일별 하나 이하, 기존 공개 import 호환, 프로젝트 import 순환 없음 |
| 최종 전체 회귀 검사 | PASS — **240개, 96.537초, exit 0**. 최종 동률 대응·입력 경계·파일 지문 분리 수정 포함. 기존 CLI·업로드·GUI·작업 복원·취소·엄격 보존과 새 모델 경로 검사. 과거 205개·중간 237개와 구분 |
| 원본·기존 결과·실행 설정 보존 | PASS — 기존 입력·기존 결과·AGENTS·프로젝트 스킬·app·Start_GUI·requirements 등 보호 대상 85개 SHA-256을 최종 재대조해 변경 0개. 기존 CLI의 결과 보존은 전체 회귀 검사에서도 확인 |

최종 [전체 회귀 로그](../work/heavy-model-validation/run-1794670836312/final-suite-log.txt), [검증 요약](../work/heavy-model-validation/run-1794670836312/final-validation.json), [구조 검사](../work/heavy-model-validation/run-1794670836312/structure-check.json), [모델 다운로드 기록](../work/heavy-model-validation/run-1794670836312/model-download.jsonl)에 근거를 남겼다. 구조 판정과 자동·실제 실행 통과는 아래 미검증 가창 정확도를 대체하지 않는다.

## Run Boy Run 실제 GPU 비교

새 작업 `ed6dcea7-99f3-45c0-bff1-511339e43c99`는 같은 원본 SVP·TXT·214.32초 보컬 WAV를 `cuda:0`에서 새로 인식·정렬했다. `cache_reused=false`이며 저장·재파싱·COMPLETED 복원까지 확인했다. 경과 시간 482.673초는 모델 다운로드 완료 대기·로딩·추론·검증을 포함한 작업 전체 시간이며 순수 GPU 추론 성능이나 기존 캐시 실행과의 속도 비교 수치가 아니다.

| 지표 | 기존 Large | ASR 1.7B + FA 0.6B |
| --- | ---: | ---: |
| 기존 음표 / TXT 단어 | 256 / 178 | 256 / 178 |
| 배치 단어 | 172 | 100 |
| 미배치 단어 | 6 | 78 |
| 미대응 원문 유지 음표 | 0 | 95 |
| 남은 `la` | 0 | 91 |
| 과거 수동 `-` 교정 29곳과 일치 | 26 | 11 |

과거 수동본 일치는 동일 음표 ID의 비교이며 실제 청취 정확도가 아니다. 사용한 과거 수동 기준의 SHA-256은 `a9a59018e8c4c54676f04128c6bad836ff4cb16004df0c7b5864094155489fae`이고 현재 외부 수동본 파일의 상태나 변경된 음표 전체를 정답으로 사용하지 않는다. [29곳 비교 근거](../work/heavy-model-validation/run-1794670836312/historical-sustain-comparison.json)를 보존했다.

공식 반환 timestamp 단위는 183개였다. TXT 178단어의 대응 판정은 MATCHED 111개, INVALID_OBSERVATION 59개, UNMATCHED 8개, AMBIGUOUS 0개다. MATCHED 중에도 기존 음표에 대응하지 못한 단어가 있어 최종 배치는 100개다. 원시 단위 67개는 모두 `start_time == end_time`인 길이 0 관측이었고 역전·WAV 범위 밖 원시 단위는 0개였다. TXT의 INVALID_OBSERVATION 59개는 정확 대응된 단어 중 시각이 무효인 수이며 인식문과 불일치한 8단어와 구분한다. 이 값들을 늘리거나 옮겨 배치 수를 채우지 않고 UNKNOWN으로 보류했다.

이 결과는 무거운 모델 경로를 실제로 실행했다는 근거이지만 정렬 품질 통과는 아니다. 긴 가창 범위를 단어 시각으로 정렬하는 과정이 의심되며, ASR 오인식·SDK 분할·정렬 모델 중 어느 요인이 각 구간을 망쳤는지는 추가 구간 실험 없이 확정하지 않는다. 특히 마지막 `run`은 INVALID_OBSERVATION으로 시각이 없어서 미배치로 남았다. 기존 Large의 약 204초 후보를 이 모델이 올바른 시각으로 고쳤다고 설명하지 않는다.

새 결과의 `onset`·`duration`·`pitch` 변경은 각각 0개, `lyrics` 변경은 152개다. 가사 외 JSON 전체 값과 타입 동일성·파싱·엄격 보존은 PASS다. 배치 후 검토 필요 161음표·미대응 95음표, UNKNOWN 256음표·178단어, 사용자 확인 0개, 기호 연결 위험 0개다. 기호 검사를 통과했다고 가창 발음이나 누락을 통과시킨 것은 아니며 결과는 **부분 초안·NOT_VERIFIED**다.

실험용 [SVP](<../outputs/ed6dcea7-99f3-45c0-bff1-511339e43c99/Woodkid - Run Boy Run 여자 커버_LYRICS_FILLED.svp>)와 [검증 보고서](<../outputs/ed6dcea7-99f3-45c0-bff1-511339e43c99/Woodkid - Run Boy Run 여자 커버 - Verification.md>), [실행 요약](../work/heavy-model-validation/run-1794670836312/first-actual-result.json), [실행 로그](../work/heavy-model-validation/run-1794670836312/first-actual-execution.jsonl)를 별도 폴더에 보존했다. 이 결과를 기존 Large 결과의 개선본으로 권하지 않는다.

실제 실행의 조합 모델 해시는 `4c34f3f5d6ea04d186afdbc4b4a7d0d7e0129aec6aefef5255543892996de29a`, [공식 반환 관측](../work/gradio/ed6dcea7-99f3-45c0-bff1-511339e43c99/audio/attempt-4de99cb6581343199f871d1e4afbfeb0/asr-observations.json)의 SHA-256은 `9b29b5c8487f55f5647fb2278213ac561ed646ddc138bafcc206c90845e7300e`다. 실행 중 NVML 표본에서 GPU 메모리 사용 14,939,451,392 bytes를 관측했으나 최고치나 최소 필요 VRAM으로 측정한 값은 아니다.

실제 브라우저 화면·전체 WAV 청취·Synthesizer V Studio Pro 열기·합성 보컬 재생은 NOT_RUN이며 전체 가창 대응은 NOT_VERIFIED다. 단어 시각 실패의 원인 확정과 새 경계의 실제 청취 검증은 남아 있다.
