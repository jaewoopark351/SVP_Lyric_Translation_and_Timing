# Gradio GUI 구현·검증 기록

확인일: 2026-11-15. 현재 GUI는 **기존 음표를 고정하고 가사 `lyrics`만 넣는** 작업이다. 선택한 모델로 업로드 WAV·TXT를 새로 분석하며 기본값은 큰 모델 우선이다. Counting Stars 기존 가사 대응 자료는 별도 옵션에서만 사용한다. 모든 경로에서 음표 위치·길이를 변경하지 않는다. 이 문서는 [GUI 계획](gradio-gui-plan.md)의 초기 타이밍 수정 구현, 가사 전용 변경과 모델 선택 확장의 검증 이력을 구분한다. 실행 명령과 화면 사용 순서는 [README](../README.md#gradio-gui-실행)에 있다.

Run Boy Run 후속 분석에서 확인한 원본 `la` 잔존·철자 음절 수에 따른 단어 미배치·`+` 연결 위험을 일반 곡의 연속 음표 구간 배치, 최종 기호 검증, 초안 교정과 품질 분류로 개선했다. 현재 계약·책임 배치·검증과 한계는 [가사 배치 개선 분석 및 구현 기록](lyrics-placement-improvement-plan.md)에 있다. 아래 154개 등 이전 검증 수치는 당시 구현 이력으로 보존한다. COMPLETED는 저장 성공이고 전체 가창 대응은 NOT_VERIFIED다.

## 구현한 기능

- 원본 SVP·TXT·보컬 WAV 드래그·파일 선택, 업로드 직후 프로젝트 내부 보관, 보관본·관측 자료 SHA-256와 그룹·음표·템포·연결 오디오 검사.
- AI 정렬 모델 선택: 자동·영어 Large·Qwen·MMS·영어 Base·Counting Stars 기존 자료. 기본 자동은 Counting Stars도 새 분석. 기존 자료 조건 미충족은 사유와 함께 실패하며 다른 모델로 자동 전환하지 않음. 읽기 전용 비교표의 배치·검토·누락·기호 위험 필터와 WAV 기준 최대 30초 구간 재생.
- 일반 곡은 단어별 연속 음표 구간, 음절 압축·지속 후보와 원문 부분문자열을 소유 정보로 기록. 별도 교정기에서 가사·+/−·사용자 확인을 변경하고 불변 초안 버전으로 보관. 오래된 화면의 중복 적용과 완료 결과 변경을 차단.
- 미대응 원문 유지와 배치 후 검토를 분리하고 부분 초안 저장 완료를 표시. Counting Stars 기존 자료의 세부 품질은 미상이고 교정기는 비활성.
- 가사 언어·모델 선택과 복원, 가변 템포·그룹/오디오 오프셋 처리, 작업별 분석 이력과 격리 프로세스·실제 종료까지 취소 관리.
- 모든 새 GUI 입력 기록에 `operation="lyrics_only"`를 기록하고 고정 음표에 가사만 대응. `onset`·`duration`·`pitch`·`detune`·개수·순서 등 `lyrics` 외 모든 필드와 나머지 프로젝트 전체를 원본과 동일하게 보존.
- 단계별 진행 표시와 협력적 취소, 입력 변경 시 이전 결과 연결 해제, 세션별 작업 격리와 작업 ID 복구.
- 검토와 저장 분리. 작업별 새 폴더에 SVP·음표 비교 CSV·가사 검증 CSV·Markdown 보고서 게시 후 다운로드 제공.

일반 곡은 실제 입력의 음표·단어 수를 읽고 별도 분석·가사 대응 결과를 기록한다. 파일 파싱·`lyrics` 외 전체 필드 보존 판정과 가창 대응 전체 판정은 구분한다. 전체 가창 대응은 NOT_VERIFIED이며 실제 Studio 열기·합성 재생을 자동 통과 처리하지 않는다. Counting Stars의 715개 음표·527단어와 UNKNOWN 음표 183개·가사 158단어·미배치 12단어는 기존 타이밍 수정 결과의 역사 수치이며, 현재 가사 전용 결과 수치로 사용하지 않는다.

일반 곡과 새 모델 분석을 구현했다. 번역·수동 음표 편집·보컬 합성은 후속 범위다. 여러 보컬 트랙의 대상 선택, 공유 그룹의 개별 참조 편집, 참조 범위로 잘린 음표와 정렬되지 않은 원본 음표는 자동 처리하지 않고 명확한 오류로 중단한다. 다국어 정렬 경로는 제공하지만 실제 MMS 가창 추론 품질은 아직 검증하지 않았다.

## 입력과 작업 파일

GUI는 원본 SVP·가사 TXT·보컬 WAV 각각의 파일 업로드 칸을 제공한다. 파일을 드래그하거나 선택하면 프로젝트의 `work/uploads/<uuid>/<원래 파일명>`에 즉시 복사한다. 파일마다 새 UUID 디렉터리를 사용하므로 같은 이름으로 다시 올려도 기존 파일을 덮어쓰지 않는다. 공백·한글 파일명을 지원하고 원본 바이트를 보존한다. 입력 교체·제거와 앱 종료는 보관본을 자동 삭제하지 않는다. 외부 원본을 수정하지 않는다.

입력 검사 콜백은 File 위젯의 현재 값을 서버 `InputSelectionRegistry`에서 보관본 경로로 해석한 뒤 JobManager에 전달한다. 레지스트리는 브라우저 세션·파일 종류별 선택과 세대 토큰을 잠금으로 보호하고, 교체·제거 뒤 늦게 완료된 복사가 이전 선택을 되살리지 못하게 한다. 모델·파일 또는 언어 선택이 바뀌면 이전 작업·결과 연결도 무효화한다. `ui/upload_callbacks.py`가 File의 사용자 `.upload`·`.clear` 이벤트를 연결하며, 파일의 `.change`는 사용하지 않는다.

세 개의 `gr.State`는 작업 ID, 현재 File 값·언어·모델 선택의 입력 서명, 화면이 본 초안 버전을 보관한다. 선택한 보관본 경로는 서버 레지스트리 소유다. 검사 후 계산·저장·미리듣기는 작업에 바인딩된 입력 경로를 사용하며 manifest는 경로·해시·가사 전용 operation·선택값 model_choice·실제 model_id를 기록한다. 작업 ID 복구는 선택 레지스트리를 초기화하고 File 위젯을 비우되 현재 가사 전용 작업은 manifest의 보관본으로 계속하고 저장한 언어와 모델 선택도 복원한다. 보관 경로는 검사 상세에 표시하며 새 입력 검사는 세 파일을 다시 올려 시작한다. 이전 정책 작업은 아래 가사 전용 변경 절의 호환 규칙을 따른다.

SVP 내부의 기존 절대·상대 오디오 경로 문자열을 보존한다. 일반 곡은 연결 파일 부재 또는 원래 상대 경로를 확인할 수 없는 경우 경고를 표시하고 업로드 WAV로 독립 분석한다. 연결 참조가 하나면 해당 시작 오프셋을 WAV 원점으로 가정하고, 하나로 정할 수 없으면 WAV 0초=프로젝트 0초를 가정해 경고한다. 경로와 원점 가정은 보고서에 남기며 실제 연결 오디오 검증으로 표시하지 않는다. Counting Stars의 상대 오디오 참조·외부 연결 파일·관측 자료 검사는 캐시 사용 조건으로 유지한다. 명시한 기존 자료 옵션의 검사에 실패하면 사유를 표시하고 중단하며, 기존 CLI는 원래 실패 계약을 유지한다. Gradio 임시 경로로 참조를 바꾸거나 업로드 파일명에서 원래 폴더를 추측하지 않는다. CLI의 `--source` 계약도 유지한다.

AGENTS.md의 `(1)` 파일명과 기존 파일명 차이는 검사 화면과 보고서에 표시한다. 현재 폴더에서 확인한 기존 세 파일은 고정 해시와 일치했다. `(1)` 세트는 해당 폴더에 없어 직접 대조하지 않았다. 파일명 변경이나 해시 검증 완화로 차이를 숨기지 않는다.

| 위치 | 소유 내용과 계약 |
| --- | --- |
| `work/uploads/<uuid>/<원래 파일명>` | 업로드 직후 저장한 입력 보관본. 매 업로드를 새 디렉터리에 격리하고 기존 파일·외부 원본은 수정하지 않음 |
| `work/gradio/<작업 ID>/manifest.json` | 입력 경로·해시·`input_summary.operation`·진행 상태·결과 해시. Lock·Event·대용량 계산 객체는 직렬화하지 않음 |
| `work/gradio/<작업 ID>/audio/` | 일반 곡의 입력·모델 해시·설정·장치·단어/문자 시각 관측 결과. attempt별 request/progress/error와 실제 PID·실행 환경 기록 |
| `work/models/torchaudio/` | Large·Base·MMS의 CTC 모델 캐시. 기존 지원 캐시는 읽기 전용 재사용하고 다운로드·추론 잠금은 실제 자원 수명까지 유지 |
| `work/models/qwen/<revision>/` | Qwen 고정 공개 snapshot과 파일별 해시. staging 디렉터리를 통해 게시하고 기존 snapshot은 덮어쓰지 않음 |
| `work/gradio/<작업 ID>/draft/` 및 `draft-000001/` 이후 | 재파싱·가사/보존 검사를 마친 불변 초안 버전과 해시를 기록한 review-context.json. manifest가 선택한 버전만 현재 초안이며 저장 전에는 다운로드 목록에 넣지 않음 |
| `work/gradio/<작업 ID>/preview/` | 원본 WAV에서 복사한 선택 구간. 원본 분석 자료를 덮어쓰지 않음 |
| `work/gradio_cache/` | 프로젝트 내부 Gradio 전달용 캐시 |
| `outputs/<작업 ID>/` | 새 GUI는 `<stem>_LYRICS_FILLED.svp`와 검증 자료 세 파일. 충돌 시 실패하고 새 대상 폴더 게시 후 네 파일을 완료 결과로 제공. 기존 TIMING_FIXED 결과는 보존 |
| `work/gui-validation/` | 변경 전·후 CLI 재현 결과와 검증 기록 |

입력·관측 자료를 실행·저장·미리듣기 때 다시 확인한다. 완료 결과는 조회·복구 시에도 파일 해시를 검사한다. 서버 재시작으로 중단된 작업은 실패로 기록하며, 현재 가사 전용의 검토 완료 작업과 게시 완료 작업은 작업 ID로 복구한다. 이전 미완료 작업의 실행·저장은 차단한다. 게시 중 취소 경쟁은 작업 잠금으로 제어하고 실패·취소·변조된 결과를 완료 다운로드로 공개하지 않는다.

## 책임 이전과 배치

프로젝트 루트 기준 경로다. **이 표는 초기 GUI·업로드 구현 시점의 책임 이전 이력**이다. 현재 가사 전용 경로의 변경은 아래 별도 표가 우선한다. 기존 자체 코드만 이전했으며 acoustic/pitch 분석 스크립트와 외부 패키지 코드는 변경하지 않았다. 이전 모듈의 재노출은 기존 bare import·직접 실행 호출자를 보존하는 호환 경계다.

| 변경 전 담당자와 소스 근거 | 책임과 배치 | 변경 후 담당자와 실제 경로 | 상태·쓰기·수명 이전 | 호출자·호환성·검증 | 남은 책임과 판정 |
| --- | --- | --- | --- | --- | --- |
| `work/counting_stars/svp.py`: read/write/song_notes | SVP 파싱·참조·직렬화·시간 단위의 응집된 형식 경계 | [svp_alignment/svp.py](../svp_alignment/svp.py) | 문서·널 접미사·그룹 참조 보존. 쓰기는 요청받은 새 경로에 한정 | 기존 모듈 재노출, 저장 후 파싱·전체 필드 대조 | NO_SPLIT_REQUIRED |
| 기존 svp/lyrics/match/timing/run의 곡별 기대값·사전·기준점 | Counting Stars 고정 정책 | [profiles/counting_stars.py](../svp_alignment/profiles/counting_stars.py) | 원본·관측 해시, 파일명, 행별 범위와 정책을 프로필 소유로 이전 | 공용 계산과 기존 상수 재노출이 같은 프로필 참조 | COMPLETE. 이 고정 정책은 Counting Stars 경로만 소유 |
| 기존 lyrics/timing/match의 JSON·CSV 읽기와 출처 | 관측 자료 읽기 | [alignment/evidence.py](../svp_alignment/alignment/evidence.py) | 파일은 읽기 전용, 자료 해시와 기존 근거 전달 | pipeline에서 동일 네 관측 파일 확인 | COMPLETE |
| 기존 lyrics/match/timing의 음절·대응·시간 보정 | 각 판단 정책별 배치 | [alignment/lyrics.py](../svp_alignment/alignment/lyrics.py), [matching.py](../svp_alignment/alignment/matching.py), [timing.py](../svp_alignment/alignment/timing.py) | 계산 결과로 음절·대응·UNKNOWN·경계 근거 반환. 원본 쓰기 없음 | 기존 모듈 재노출, 결과 SVP·CSV 바이트 호환 | COMPLETE |
| 기존 verification/report의 보존·가사 판정과 표현 | 검증 판정과 보고서 표현 분리 | [verification/preservation.py](../svp_alignment/verification/preservation.py), [lyrics.py](../svp_alignment/verification/lyrics.py), [reporting.py](../svp_alignment/verification/reporting.py) | 판정·비교 행 반환과 CSV/Markdown 형식을 분리. 실제 게시 소유권은 artifacts | CLI 기존 열·보고서 유지. GUI는 별도 정직한 NOT_RUN/NOT_VERIFIED 보고 | COMPLETE |
| 기존 run.py prepare의 순서 제어·수정본 계산 | 읽기 전용 공용 처리 흐름과 계산 결과 계약 | [pipeline.py](../svp_alignment/pipeline.py), [prepared_alignment.py](../svp_alignment/prepared_alignment.py) | 진행·취소를 콜백으로 전달, PreparedAlignment는 메모리 계산 결과만 소유 | CLI와 GUI의 Counting Stars 경로가 같은 prepare_paths 사용. 기존 12필드 tuple 보존 | COMPLETE |
| 기존 run.py argparse/prepare/run/출력 | CLI 진입·이전 API·레거시 게시 계약 | [cli.py](../svp_alignment/cli.py), [legacy.py](../svp_alignment/legacy.py), [기존 run.py](../work/counting_stars/run.py) | 임시 폴더 정리, 파일별 rename, report-only 예외 계약 보존 | 기존 옵션·출력명·stdout JSON, 외부 cwd 실행, 충돌·report-only 회귀 검사 | COMPLETE. 파일별 rename을 전체 폴더 원자 게시로 표현하지 않음 |
| 기존에 없던 GUI 작업 수명 | 작업 상태 전환과 실행 순서 | [jobs/manager.py](../svp_alignment/jobs/manager.py), [state.py](../svp_alignment/jobs/state.py) | JobManager가 전환, JobState가 작업별 상태·Event·RLock 소유. UI State는 작은 ID·서명만 보관 | 취소·실패·재시작·진행률·두 작업 격리 테스트 | COMPLETE |
| 기존 run.py 결과 쓰기 및 새 GUI 복구 요구 | 작업별 초안·게시·직렬화·무결성 | [jobs/artifacts.py](../svp_alignment/jobs/artifacts.py) | ArtifactStore가 작업 경로·manifest·파일 쓰기·staging 정리 소유 | 기존 파일 보존, 충돌·부분 복사 실패·변조·경로 탈출 검사 | COMPLETE |
| 새 세션 및 원본 구간 청취 요구 | 세션 연결과 오디오 구간 자원 경계 | [jobs/sessions.py](../svp_alignment/jobs/sessions.py), [preview.py](../svp_alignment/jobs/preview.py) | SessionRegistry가 revision·작업 연결 소유. preview가 짧은 WAV 핸들 수명과 clip 쓰기 소유 | 입력 변경·늦은 응답 재연결 차단, 구간·길이·경로 검사 | COMPLETE |
| 기존 GUI 경로 입력과 새 파일 업로드 요구 | 업로드 파일의 프로젝트 내부 보관 | [jobs/uploads.py](../svp_alignment/jobs/uploads.py) | UploadStore가 고유 디렉터리·복사·보관 경계·실패 정리를 소유. 저장 성공 경로만 전달하고 외부 원본과 기존 보관본은 수정하지 않음 | UI 업로드 어댑터가 위임. 계산·CLI 경로 API 유지. 업로드 보관 테스트 12개 통과 | COMPLETE |
| 기존 callbacks의 입력 값과 새 비동기 업로드 선택 | 세션별 입력 선택과 세대 토큰 | [jobs/input_selection.py](../svp_alignment/jobs/input_selection.py) | InputSelectionRegistry가 세션·파일 종류별 원본 캐시 값→보관본 경로·세대 토큰과 RLock 소유. 교체·제거·복구 시 선택 무효화 | 업로드 bind·입력 검사 resolve·복구 reset. 선택 레지스트리 테스트 9개 통과 | COMPLETE |
| 기존 callbacks의 입력 서명·세션 연결 | 사용자 파일 업로드·제거와 작업 콜백 위임 | [ui/upload_callbacks.py](../svp_alignment/ui/upload_callbacks.py), [callbacks.py](../svp_alignment/ui/callbacks.py), [gradio_app.py](../svp_alignment/ui/gradio_app.py) | File의 .upload·.clear 이벤트를 연결하고 저장·선택 소유자에게 위임. gr.State는 작업 ID·파일/언어 입력 서명 두 값만 소유. 복구 시 File을 비우고 기존 작업 입력 유지 | resolve_inputs가 보관 경로를 JobManager에 전달. 교체·제거·늦은 응답·복구·입력 구성 등 UI 검사 14개 통과 | COMPLETE |
| 새 Gradio 화면과 실행 환경 | 화면 구성·이벤트·표현·시작 구성 분리 | [ui/gradio_app.py](../svp_alignment/ui/gradio_app.py), [callbacks.py](../svp_alignment/ui/callbacks.py), [presentation.py](../svp_alignment/ui/presentation.py), [app.py](../app.py) | 시작 환경은 app.py, 세션 식별과 이벤트 위임은 callbacks, 표시 변환은 presentation | 읽기 전용·private 이벤트·전체 콜백 수명 직렬화 구성 및 현재 14개 UI 직접 테스트 | COMPLETE. 브라우저 화면 검증은 NOT_RUN |

1차 구현과 이번 업로드 보관·파일 선택 상태·UI 어댑터의 구조 판정은 COMPLETE다. 새 담당자별 소유권·호출자·참조와 집중 테스트를 위 표에서 확인했다. 프로덕션 파일당 최상위 프로젝트 클래스는 하나 이하다. 순환 import, 기존 경로 참조와 실제 CLI 진입점 로딩을 점검했다. 일반 곡 확장의 새 담당자·모델 자원·캐시 수명은 아래 추가 표에서 기록한다.

## 검증 결과

이 절은 일반 곡 확장 전 초기 GUI·업로드 구현의 검증 이력이다. 경로 입력 방식의 24개와 업로드 변경 후 52개 결과를 구분해 보존한다. 일반 곡 확장과 현재 가사 전용 변경의 검증은 아래 각각 별도 절에 기록한다.

| 검사 | 결과와 근거 |
| --- | --- |
| 당시 가상환경·패키지 | PASS — Python 3.10.22, Gradio 6.17.3, 당시 런타임 68개 고정. 일반 곡 확장에서는 uroman을 추가해 69개이며 기존 버전 유지 |
| 작업 수명 회귀 검사 | PASS — 15개. 입력 변경, 협력적 취소, 충돌, 부분 쓰기 실패, 변조, 작업 격리, 복구, 미리듣기, 진행률 |
| UI 콜백·구성 검사 | PASS — 14개. 업로드→검사→계산→검토→저장→복구, 입력 선택·제거·늦은 응답 차단, 필터·행 선택, 읽기 전용·큐 설정 |
| 기존 CLI 회귀 검사 | PASS — 1개. 외부 cwd 직접 실행, 네 파일 바이트 일치, 기존 결과 충돌, report-only 갱신·재실행 실패 계약 |
| 초기 구현 전체 테스트 | PASS — 당시 24개, unittest discover. ResourceWarning 활성 상태에서도 통과 |
| 업로드 보관 | PASS — 12개. 원본 바이트·파일명 보존, 반복 업로드 격리, 경로 경계, 실패 정리 및 보관본 확인 |
| 입력 선택 레지스트리 | PASS — 9개. 세션·파일 종류별 선택, 세대 토큰, 교체·제거·복구 초기화와 잘못된 입력 차단 |
| 업로드 변경 후 전체 테스트 | PASS — 52개(작업 15·UI 14·업로드 전송 1·업로드 보관 12·입력 선택 9·CLI 1), unittest discover. pip check 통과 |
| 실제 업로드 전송 | PASS — TestClient로 실제 multipart 세 파일 업로드, Gradio FileData 전처리·업로드 이벤트·프로젝트 보관·입력 검사 READY·복구 시 File 비우기 확인. 브라우저나 네트워크 포트를 사용하지 않은 ASGI 검사 |
| 원본·관측·기존 결과 보존 | PASS — 원본 세 파일·관측 네 파일과 기존 outputs의 SHA-256 일치. 무관한 acoustic/pitch 자체 코드 변경 없음 |
| 앱 실행 | PASS — 초기 구현 검증 당시 127.0.0.1:7860에서 실행해 로컬 서버 HTTP 응답 확인. 현재 기본 포트는 28670 |
| 실제 브라우저 입력·다운로드 화면 | NOT_RUN — Windows 브라우저의 현재 URL을 확신할 수 없다는 Computer Use 도구 검사로 자동화 중단. 직접 콜백 검사를 실제 화면 검증으로 간주하지 않음 |
| 당시 새 음성 분석·전체 WAV 청취 | NOT_RUN — 초기 구현은 기존 분석 자료 재사용 범위. 후속 새 분석은 아래 기록 |
| Synthesizer V Studio Pro 실제 열기·합성 보컬 재생 | NOT_RUN — 이번 작업에서 실행하지 않음 |
| 전체 가창 정렬 | NOT_VERIFIED — UNKNOWN·미배치 가사와 실제 합성 검토가 남음 |

실제 File 전처리 검사에서는 설치된 Gradio의 임시파일 ResourceWarning을 관측했다. 경고는 억제하지 않았고 외부 패키지 코드는 변경하지 않았다. TestClient·앱·테스트 작업 폴더는 종료·정리했다.

검사 명령:

```powershell
.\.venv\Scripts\python.exe -B -W always::ResourceWarning -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

변경 전 결과는 `work/gui-validation/legacy-baseline/`, 변경 후는 `work/gui-validation/new-cli/`에 보존했다. 네 파일의 SHA-256이 각각 일치한다. 기존 CSV 열, SVP 바이트, CLI 보고서의 Windows 줄바꿈도 유지했다.

| 기존 CLI 파일 | 변경 전·후 SHA-256 |
| --- | --- |
| 가사 검증 CSV | `ada2120a82b43dc6f6931721a19da1ed9e71a9e04c8a1089af3b181c4bd50339` |
| 음표 비교 CSV | `27d4cb60ffb6685a81a8d6608db84d281580b6e8d49b78486b1499db6a0dbb7c` |
| 검증 Markdown | `09847c12eee94fbb42840cee3af5a84d440f188320b71a699fb7e766eb18a318` |
| TIMING_FIXED SVP | `2c242e767cabb70be64a95e31e7db28ac99ac53e4c548d2cf4bb83da78f80a8c` |

GUI 보고서는 새 분석·기존 자료 재사용과 실제 수행하지 않은 검증을 구분해 CLI 보고서와 문구가 다르다. 기존 CLI의 studio-status 자유 문자열은 GUI의 자동 PASS 근거로 사용하지 않는다.

서버는 loopback에만 바인딩하고 share=False, strict_cors=True로 실행한다. 파일 제공 목록에 원본 폴더나 프로젝트 전체를 등록하지 않는다. 다운로드는 해당 작업에서 게시·재검증한 네 파일, 오디오는 해당 작업의 짧은 원본 clip만 반환한다.

## 일반 곡 확장과 책임 배치

**아래는 음표 시작·길이 수정이 포함됐던 이전 정책의 구현·검증 이력이다. 현재 GUI는 이 시간 후보 적용 경로를 실행하지 않으며, 음표 고정·가사 전용 변경 절의 계약을 따른다.**

기존 Counting Stars CLI와 자체 acoustic/pitch 스크립트는 유지했다. 일반 경로는 업로드 세 파일 해시가 기존 프로필과 다르거나, 해시는 같아도 캐시 검사에서 외부 연결 오디오·관측 자료 조건을 충족하지 못한 경우 선택한다. GUI는 캐시 검사의 ValueError/OSError 사유를 경고에 남긴 뒤 해당 WAV·TXT를 새로 강제 정렬한다. 기존 CLI의 엄격한 캐시 검증·실패 계약은 유지한다. 정규화는 모델 입력에만 적용하고 TXT 원문·대소문자·행/열·반복을 보존한다. 단어 수를 맞추기 위해 기존 음표를 추가·분할하거나 멜로디를 변경하지 않는다. 자동 음절 내부 경계·멜리스마·낮은 신뢰도 등의 UNKNOWN은 기존 시각을 유지한다. 참조 범위 안에 있는 정상 원본 음표의 시간 후보가 참조 시작·끝 경계를 벗어나면 그 후보도 UNKNOWN으로 남기고 원래 시각을 유지한다. 원본부터 참조 범위에 잘린 미지원 구조와 구분하며, 경계를 넘는 후보 하나로 전체 작업을 실패시키지 않는다. 전체 정렬 판정은 항상 NOT_VERIFIED이며 CTC 문자 점수를 실제 가창 검증으로 간주하지 않는다.

모델 캐시는 작업 사이에서 공유하지만 기존 가중치를 덮어쓰지 않는다. 새 다운로드는 모델별 잠금과 고유 임시 파일을 사용한다. 추론 전체 수명은 작업 간 잠금으로 직렬화하고, 취소는 실제 worker 종료·대기 후에 완료 처리한다. 작업 안의 관측 캐시도 WAV·원문 토큰·모델 해시·설정·버전·언어 서명이 같을 때만 재사용한다.

| 변경 전 담당자와 소스 근거 | 책임과 배치 | 변경 후 담당자와 실제 경로 | 상태·쓰기·수명 이전 | 호출자·호환성·검증 | 남은 책임과 판정 |
| --- | --- | --- | --- | --- | --- |
| 기존 JobManager의 고정 Counting Stars 파이프라인 호출 | 해시 기반 곡 경로 선택과 일반 처리 흐름 | [jobs/processing.py](../svp_alignment/jobs/processing.py), [general_pipeline.py](../svp_alignment/general_pipeline.py), [general_prepared.py](../svp_alignment/general_prepared.py) | 세 원본 해시와 기존 캐시 검사를 모두 통과한 경우에만 기존 경로. 캐시 검사 ValueError/OSError는 원인 경고와 일반 분석으로 전환. GeneralPrepared는 일반 계산 결과만 소유 | inspect/prepare 호출과 모드별 artifact 이름·보고서 계약을 jobs에 연결 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 기존 svp.py의 고정 그룹·BPM 조건과 새 일반 형식 요구 | SVP 문서·참조·음표 locator·허용 필드 보존 | [project/document.py](../svp_alignment/project/document.py) | SvpDocument가 원문 복사·참조 해석·새 파일 쓰기와 재파싱 경계 소유. 원본 쓰기 금지 | 단일 보컬 트랙 및 참조 그룹, shared/clipped/모호한 구조 거절. 일반 pipeline에서 사용 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 고정 120 BPM 변환과 새 가변 시간축 요구 | 템포 구간과 프로젝트 시각 변환 | [project/tempo_map.py](../svp_alignment/project/tempo_map.py) | TempoMap이 가변 템포·startTimeSeconds의 양방향 변환 소유. 그룹 오프셋은 문서 경계에서 적용 | 음표 시작·끝 변환과 보존 검사에 사용 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 기존 곡별 음절 사전·행 범위와 새 Unicode TXT | 원문 위치·토큰·추정 음절 근거 | [alignment/general_lyrics.py](../svp_alignment/alignment/general_lyrics.py) | 원문 파일 읽기 전용. UTF-8/UTF-16 BOM/CP949 토큰 위치·반복 보존, 추정 경계 사유 반환 | 일반 파이프라인과 대응 정책이 사용. 불확실한 음절은 UNKNOWN | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 고정 Counting Stars 매칭·시간 규칙과 새 일반 정책 | 기존 음표 대응과 안전한 시간 후보 적용 | [alignment/general_matching.py](../svp_alignment/alignment/general_matching.py), [general_timing.py](../svp_alignment/alignment/general_timing.py) | 대응·미배치·UNKNOWN 반환. 원본 음표 개수·pitch 추가/분할 없이 미확정 시 기존 타이밍 유지 | 일반 pipeline→document.apply→보존 검증. 낮은 신뢰도·과도한 이동·새 겹침·참조 범위 밖 시간 후보를 적용하지 않고 UNKNOWN/원본 타이밍 유지 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 새 모델 입력의 문자 제약과 원문 가사 | 원문 보존과 모델용 정규화 | [audio/transcript.py](../svp_alignment/audio/transcript.py) | 원문·word_index 유지, 언어별 모델 선택·uroman/ASCII 정규화. 발음 불명 토큰은 UNKNOWN | alignment와 worker에 정규화 토큰 전달. 원본 TXT를 수정하지 않음 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 새 일반 곡 WAV 입력 | SoundFile 읽기와 모델용 리샘플링 | [audio/waveform.py](../svp_alignment/audio/waveform.py) | WAV 핸들 수명과 16 kHz 모노 배열 소유. 원본 sample/frame/채널 메타데이터 반환 | worker에서 사용, 원본 바이트·분석 입력과 미리듣기를 구분 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 새 모델 다운로드·공유 캐시 요구 | 모델 조회·다운로드·게시 | [audio/models.py](../svp_alignment/audio/models.py) | 기존 캐시 읽기 전용. 새 다운로드의 고유 임시 파일·FileLock·해시·실패 정리 소유 | worker ensure_model. 기존 모델 덮어쓰기와 작업 간 다운로드 충돌 방지 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 새 CTC 모델 계산 | 청크 추론·강제 정렬 계산 | [audio/inference.py](../svp_alignment/audio/inference.py) | 모델 텐서·CUDA/CPU 계산은 worker 프로세스 내 함수가 소유. 점수·문자 후보 반환 | worker가 호출. CUDA 우선·메모리 부족 시 CPU 재시도 구현 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 새 작업별 분석·취소·GPU 수명 요구 | 관측 요청·작업 프로세스 수명과 격리 실행 | [audio/alignment.py](../svp_alignment/audio/alignment.py), [worker.py](../svp_alignment/audio/worker.py) | alignment가 실제 PID의 시작·종료대기·작업 간 잠금·작업별 캐시를 소유. worker가 모델·GPU·관측 JSON·runtime PID 기록 소유 | JobManager가 동기적으로 전체 수명 대기. Windows 실제 인터프리터 부트스트랩·종료 후 잠금 해제 | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 기존 고정 곡 검증·보고 형식과 새 일반 결과 | 가사 대응 보존 판정과 자동 후보 보고 | [verification/general_lyrics.py](../svp_alignment/verification/general_lyrics.py), [general_reporting.py](../svp_alignment/verification/general_reporting.py) | 원문 토큰·순서·반복·미배치 판정과 비교 행/보고 표현을 별도 소유. 실제 파일 게시 담당자는 기존 ArtifactStore | 모드별 이름·열·관측 이력과 UNKNOWN을 jobs/artifacts에 전달. 실제 청취·Studio·합성은 NOT_RUN | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |
| 기존 File 입력 서명·표 시각·고정 제목 | 일반 화면·언어 바인딩·WAV 좌표 미리듣기 | [ui/gradio_app.py](../svp_alignment/ui/gradio_app.py), [callbacks.py](../svp_alignment/ui/callbacks.py), [presentation.py](../svp_alignment/ui/presentation.py), [jobs/preview.py](../svp_alignment/jobs/preview.py) | 언어가 입력 서명·manifest에 포함. 사용자 언어 변경이 작업 무효화, 복구가 언어 복원. 표 프로젝트 시각을 WAV 기준 초로 변환 | 일반 버튼·동일 상태/저장 경계 유지. 미리듣기는 원본 WAV clip | COMPLETE — 최종 116개 회귀 검사와 실제 영어 곡 처리 확인 |

새 담당자 12개 경계의 구조 판정은 COMPLETE다. 실제 호출 경로·소유 상태·쓰기·자원 종료와 집중 회귀 검사를 확인했으며, 아래 실행 결과와 미수행 검증은 별도로 구분한다.

## 일반 곡 확장 검증

이 표와 연결된 Shooting Stars `_TIMING_FIXED.svp`는 정책 변경 전 결과다. 원본·기존 결과와 해당 검증 이력을 보존하며 현재 가사 전용 결과로 다시 명명하거나 덮어쓰지 않는다. 당시 116개 통과는 신규 가사 전용 정책의 검증을 뜻하지 않는다.

| 검사 | 결과와 근거 |
| --- | --- |
| 실제 다른 영어 곡의 새 분석·게시 | PASS — Shooting Stars 여자 커버, 작업 `28f80b01-aaa9-4a6b-af11-92c65bf84bd0`. 227.07초 WAV·281개 음표·240단어를 실제 CUDA 영어 CTC로 처리하고 결과 네 파일 게시. 파이프라인·저장 포함 21.953초 |
| 실제 결과의 가사·미확정 | 229단어 배치·11단어 미배치, UNKNOWN 음표 239개·단어 198개. 완료는 파일 게시 상태이며 가창 정렬 PASS를 뜻하지 않음 |
| 결과 파싱·멜로디/설정 보존 | PASS — 실제 실행의 summary parse/preservation 판정. 원본 음표 개수·순서·pitch·detune·참조·시간축 등 허용 필드 외 보존 |
| 추가 경계 수정 전 전체 자동 회귀 검사 | PASS — 당시 전체 108개, 35.864초. 기존 CLI·업로드·UI 및 일반 곡 SVP/시간축·가사 대응·음성 분석·작업 수명 회귀 검사 |
| 캐시 대체 분석·참조 경계 수정 후 전체 회귀 검사 | PASS — 최종 전체 116개, 44.152초. 기존 캐시 조건 미충족의 새 분석 전환과 정상 음표의 참조 경계 밖 후보 UNKNOWN·원본 타이밍 보존 회귀 검사 포함 |
| 새 의존성·환경 | PASS — uroman 1.3.1.1 추가, 런타임 69개와 기존 버전 보존. pip check: No broken requirements found. |
| CPU 전체 추론·MMS 실제 가창 추론 | NOT_RUN — 실제 영어 CUDA 전체 실행과 구분 |
| 브라우저 화면·전체 WAV 청취·Studio 열기·보컬 합성 | NOT_RUN — 이 확장에서 해당 검증을 실행하지 않음. 기존 도구 URL 확인 실패 이후 새 브라우저 시도 없음 |
| 전체 가창 정렬 | NOT_VERIFIED — 자동 관측·UNKNOWN·미배치가 남고 실제 청취·합성 검토를 수행하지 않음 |

실제 결과의 [검증 보고서](<../outputs/28f80b01-aaa9-4a6b-af11-92c65bf84bd0/Shooting Stars 여자 커버 - Verification.md>)와 [실행 요약](../work/gui-validation/general-song-result.json), [실행 로그](../work/gui-validation/general-song-run.log)에 입력·모델 SHA-256·장치·설정·관측 상태를 기록했다. 사용한 영어 모델 ID는 WAV2VEC2_ASR_BASE_960H이고 실제 장치는 cuda:0, 해당 작업 관측 cache_reused는 false다.

## 음표 고정·가사 전용 변경

사용자가 기존 음표를 유지하고 가사만 넣도록 범위를 정정했다. 새 GUI 작업은 `input_summary.operation="lyrics_only"`로 식별한다. 일반 곡의 CTC 관측과 Counting Stars 캐시는 가사를 대응시키는 근거로만 사용하며, 음표의 `onset`·`duration`을 계산·적용하는 `time_notes`나 기존 CLI의 `prepare_paths`를 GUI 실행에 사용하지 않는다. 변경 가능한 SVP 필드는 대상 기존 음표의 `lyrics`뿐이다.

대상 음표 개수·배열 순서·위치·길이·음높이·detune·ID를 비롯해 `lyrics`를 제외한 모든 필드와 나머지 프로젝트 전체가 원본과 정확히 같아야 한다. 기존 타이밍이 모델 관측과 다르거나 UNKNOWN이더라도 그대로 둔다. 가사를 맞추려고 음표를 추가·분할·합치거나 재배열하지 않는다. 원본 파일이 남아 있다는 확인만으로 음표 보존을 통과시키지 않는다.

초안 저장 전, 저장된 SVP 재파싱 후, 최종 게시 직전에 같은 엄격 보존 검사를 실행한다. 출력은 Counting Stars를 포함해 모두 `outputs/<작업 ID>/<원본 SVP stem>_LYRICS_FILLED.svp`다. CSV의 전후 시각은 같으며 발음 관측 오차는 가사 대응의 참고값으로 보고한다. 미배치·불확실 가사는 UNKNOWN으로 표시하고 전체 가창 대응은 NOT_VERIFIED를 유지한다.

이전 `_TIMING_FIXED.svp` 결과 파일과 계산 내용은 새 정책 결과로 덮어쓰지 않는다. 이전 COMPLETED 작업은 **이전 타이밍 수정 작업**으로 표시하고 파일 해시를 검증해 기존 파일 내용 그대로 다운로드·미리듣기를 제공한다. 이전 READY/REVIEW_READY를 포함한 미완료 작업은 실행·저장을 거절하고 세 입력을 다시 올려 가사 전용으로 검사하도록 안내한다. 작업 상태 manifest에는 정책 변경에 따른 재검사 요구나 서버 중단을 표시하는 FAILED 상태를 기록할 수 있다. 이전 결과를 새 정책 결과처럼 재저장하지 않는다. 기존 Counting Stars CLI의 옵션·결과명·타이밍 조정과 실패 계약은 그대로 유지한다. AGENTS.md의 기존 개별 작업 계약도 수정하지 않는다.

이번 변경에서 파일 이동은 없다. 아래 경로는 프로젝트 루트 기준이다.

| 변경 전 담당자와 소스 근거 | 책임과 배치 | 변경 후 담당자와 실제 경로 | 상태·쓰기·수명 이전 | 호출자·호환성·검증 | 남은 책임과 판정 |
| --- | --- | --- | --- | --- | --- |
| GUI가 기존 Counting Stars prepare_paths의 가사·타이밍을 함께 사용 | 검증된 캐시의 가사 대응만 적용하는 GUI 어댑터 | [cached_lyrics.py](../svp_alignment/cached_lyrics.py) | 기존 관측·음절·매칭·UNKNOWN은 읽기 전용 재사용. 원본에서 가사만 바꾼 계산 결과 반환, 시간 보정 호출 제거 | jobs/processing이 새 어댑터 선택. 기존 pipeline/CLI 유지와 캐시 경로의 음표 동일성 회귀 검사 통과 | COMPLETE — 새 GUI 어댑터를 기존 타이밍 CLI와 분리, 전체 127개 검사 통과 |
| 일반 GUI prepare_song이 time_notes 후보를 onset/duration에 적용 | 고정 음표의 가사 대응과 결과 구성 | [general_pipeline.py](../svp_alignment/general_pipeline.py), [general_prepared.py](../svp_alignment/general_prepared.py) | 관측·매칭 결과에서 lyrics만 반영. 전후 시각은 원본 시각, operation과 새 artifact 이름 전달 | 일반 음성 worker·언어·원문 대응 계약 유지. 시간 후보 미호출 검사와 실제 Shooting Stars 결과의 전 필드 비교 통과 | NO_SPLIT_REQUIRED — 기존 처리 흐름과 결과 계약에 응집, 시간 보정 제거 |
| 기존 형식 보존 검사는 onset/duration/lyrics 수정을 허용 | GUI 가사 전용 완전 동일성 판정 | [verification/lyrics_only.py](../svp_alignment/verification/lyrics_only.py) | verify_lyrics_only가 대상 기존 음표의 lyrics만 제외해 문서 전체 대조. 파일 쓰기·작업 상태 소유하지 않음 | 일반·캐시 파이프라인과 ArtifactStore가 공통 사용. onset/duration 등 변조 거절 검사 통과. 기존 CLI 보존 검사 유지 | COMPLETE — 별도 검증 정책 담당자와 실제 호출 확인 |
| 기존 JobManager가 이전 정책 작업도 같은 실행·저장 경로로 복원 | operation에 따른 현재 작업 계약과 이전 결과 호환 | [jobs/processing.py](../svp_alignment/jobs/processing.py), [manager.py](../svp_alignment/jobs/manager.py) | 새 검사에 lyrics_only 기록. 이전 미완료 실행·저장 차단 및 재검사·중단 상태 기록. 이전 완료 결과 파일은 그대로 읽음 | 이전 미완료 거절 회귀 검사와 새·이전 COMPLETED 실제 복원 각각 네 파일 확인. 기존 결과·계산 내용 보존, 상태 manifest는 FAILED 등으로 갱신 가능 | NO_SPLIT_REQUIRED — 경로 선택과 작업 수명 담당자를 기존 경계에 유지 |
| 기존 ArtifactStore의 모드별 이름과 허용 필드 검증 | 가사 전용 초안·재파싱·게시 검증 경계 | [jobs/artifacts.py](../svp_alignment/jobs/artifacts.py) | 새 이름 LYRICS_FILLED와 strict 검사 위임. 새 폴더 게시·실패 정리·기존 파일 보존 계약 유지 | 저장 전·재파싱 후·게시 직전 lyrics 외 변경 거절 검사 통과. 기존 완료 결과는 예전 이름으로 복원 | NO_SPLIT_REQUIRED — 파일 게시 소유권 유지, 검증 정책은 별도 담당자에 위임 |
| 기존 GUI의 타이밍 보정 설명·실행 버튼·결과 표시 | 음표 고정 가사 배치 화면과 이전 작업 표기 | [ui/gradio_app.py](../svp_alignment/ui/gradio_app.py), [callbacks.py](../svp_alignment/ui/callbacks.py), [presentation.py](../svp_alignment/ui/presentation.py) | 기존 세션·입력 선택·언어·취소 수명 유지. 새 결과와 이전 타이밍 수정 결과를 구분해 표시 | 직접 콜백·구성·실제 ASGI/process_api 집중 22개 통과. 브라우저 실제 화면은 별도 NOT_RUN | NO_SPLIT_REQUIRED — 화면·이벤트 위임·읽기 전용 표현의 기존 담당자 유지 |

구조 판정은 위 새 담당자·기존 담당자와 실제 호출 경계에 대해 완료했다. 기존 CLI와 자료 경로를 보존했고 신규 모듈의 로딩·순환 의존·공개 클래스 배치를 확인했다. 정적 검사한 프로덕션/app Python 51개에서 구문 오류와 파일당 최상위 프로젝트 클래스 하나 규칙 위반은 없었다. 독립 소스 검토에서도 차단 결함을 찾지 못했다. 구조 판정은 아래 자동·실제 실행 및 미수행 가창 검증과 구분한다.

| 신규 검사 | 결과와 근거 |
| --- | --- |
| 일반 곡의 lyrics 전용 처리·엄격 보존 검증 | PASS — 핵심 집중 검사 34개. 가변 템포·그룹 오프셋과 다른 발음 관측값을 적용해도 onset/duration 고정, lyrics 외 필드 변조 거절 확인 |
| UI 콜백·구성·실제 업로드 전송 | PASS — 집중 검사 22개. 직접 콜백·앱 구성·실제 ASGI 업로드·Gradio process_api, 원본과 결과의 음표 시작/종료 동일, 이전 작업 표기·다운로드 보존 확인. 실제 브라우저 화면 검사와 구분 |
| Counting Stars 캐시의 lyrics 전용 처리·게시 경계 | PASS — 최종 회귀 검사에 캐시 경로의 lyrics 외 보존, time_notes/prepare_paths 미호출과 저장 경계 변조 거절 포함 |
| 이전 완료 복구·미완료 작업 차단·기존 CLI 호환 | PASS — 회귀 검사 통과. 새 `a7da05ed-9aa2-426d-a772-032b84ecb955`와 이전 `28f80b01-aaa9-4a6b-af11-92c65bf84bd0`를 실제 COMPLETED로 복원하고 각각 네 파일 확인 |
| 실제 Shooting Stars 가사 전용 생성·재파싱·게시 | PASS — 새 작업 `a7da05ed-9aa2-426d-a772-032b84ecb955`. 227.07초 WAV를 CUDA에서 새로 분석, 저장 포함 21.542초. 281개 음표·240단어 중 229단어 배치·11단어 미배치, UNKNOWN 음표 195개·단어 154개 |
| 실제 새 결과의 음표 전체 필드 동일성 | PASS — 원본과 새 결과에서 onset 0개·duration 0개·pitch 0개 변경, lyrics 263개 변경. 대상 lyrics를 제외한 JSON 문서 전체가 정확히 동일. 파싱·엄격 보존 검사 모두 PASS |
| 기존 타이밍 수정 결과와 구분 | 이전 `28f80b01-aaa9-4a6b-af11-92c65bf84bd0` 결과는 onset 42개·duration 42개를 변경했음을 확인. 원본·이전 결과는 보존하고 새 작업으로 별도 게시 |
| 전체 자동 테스트·pip check | PASS — 이번 변경 후 전체 127개, 64.526초. pip check: No broken requirements found. 이전 116개 수치와 구분 |
| 정적 검사·원본/기존 결과 보존 | PASS — 프로덕션/app Python 51개 compile 및 클래스 배치 검사. 입력 세 파일·이전 결과 네 파일·AGENTS/app/Start_GUI/requirements/기존 CLI 관련 파일을 포함한 15개 SHA-256 불변 확인 |
| 브라우저·전체 WAV 청취·Studio 실제 열기·보컬 합성 | NOT_RUN — 실제 실행 여부를 각각 기록해야 함 |
| 전체 가창 대응 | NOT_VERIFIED — 자동 대응 후보이며 실제 청취·합성 검토가 남음 |

새 가사 전용 [SVP](<../outputs/a7da05ed-9aa2-426d-a772-032b84ecb955/Shooting Stars 여자 커버_LYRICS_FILLED.svp>)와 [검증 보고서](<../outputs/a7da05ed-9aa2-426d-a772-032b84ecb955/Shooting Stars 여자 커버 - Verification.md>), [실행·전 필드 비교 요약](../work/gui-validation/lyrics-only-result-a7da05ed-9aa2-426d-a772-032b84ecb955.json)에 근거를 남겼다. 이 실행은 새 WAV 관측(`cache_reused=false`)이며 영어 모델 `WAV2VEC2_ASR_BASE_960H`, 장치 `cuda:0`를 사용했다. UNKNOWN 수는 가사만 적용한 현재 결과의 수치이고, 이전 시간 후보 정책의 UNKNOWN 수치와 구분한다.

## 큰 모델과 GUI 모델 선택

사용자 요청으로 기본 영어 모델을 Base에서 **Wav2Vec2 Large LV60K**로 바꾸고 **Qwen3-ForcedAligner 0.6B**를 추가했다. 기존 Base·MMS도 GUI에서 고를 수 있다. 이 변경은 가사 대응의 음성 관측만 확장하며, `operation="lyrics_only"`와 `_LYRICS_FILLED.svp` 출력 계약은 그대로다. 모델이 찾은 발음 시각과 음표가 달라도 `onset`·`duration`·`pitch` 및 가사 외 모든 필드는 원본과 정확히 같아야 한다.

화면의 **AI 정렬 모델**(`elem_id="model-choice"`)은 `audio/model_catalog.py`의 선택 목록을 사용한다. 모델 기본값은 `auto`다. 언어 영어 또는 언어 자동의 ASCII 알파벳 가사는 Large, 지원 비영어 언어를 명시한 경우 Qwen, 비ASCII 자동 언어·다국어는 MMS를 사용한다. Qwen을 직접 선택한 경우 언어 자동의 ASCII 가사는 영어로 처리하지만 비ASCII 가사는 지원 언어를 명시해야 한다. Qwen은 최대 300초 WAV를 지원하며 긴 곡은 영어 Large 또는 MMS를 선택한다. 지원하지 않는 조합은 입력 검사에서 안내한다.

Counting Stars의 기존 관측 자료는 `cached_counting_stars`를 명시한 경우에만 선택한다. 해당 곡의 세 해시·관측 자료·연결 오디오 검사에서 실패하면 작업을 실패 처리하고 다른 모델로 자동 전환하지 않는다. 기본 자동은 정확히 같은 Counting Stars 입력도 새 Large 분석을 수행한다. 기존 CLI의 엄격한 입력·관측 검사와 결과 바이트 계약은 유지한다.

입력 서명·`input_summary`·분석 요청 서명에는 `model_choice`와 실제 `model_id`를 포함한다. 파일·언어·모델 변경은 이전 작업 연결을 끊고 재검사를 요구한다. 복구는 File을 비우고 저장된 언어·모델을 복원한다. 모델 선택 정보가 없는 이전 미완료 작업은 실행·저장을 차단하고 재검사하도록 안내한다. 이전 COMPLETED는 기존 결과·모델 이력을 그대로 표시하고 다운로드·미리듣기를 유지한다. 이전 계산을 새 기본 모델로 조용히 이어 가지 않는다.

Qwen은 고정 공개 revision `1c85775dfe71a2a90e6aeea682c6eb9df3d8848b`의 모델 파일을 프로젝트 `work/models/qwen/`에 원자적으로 게시하고 파일 해시를 검증한다. CTC 캐시와 Qwen 캐시는 분리한다. 작업별 관측 캐시는 선택 모델·실제 모델·입력·설정·버전이 같을 때만 재사용하며 기존 결과나 다른 모델의 관측을 덮어쓰지 않는다. 프로세스 시작·실제 PID 종료 대기·공유 잠금은 기존 `audio/alignment.py`의 소유권을 유지한다. 취소·실패 뒤에는 종료한 worker의 동일 run_id 다운로드 scratch 중 알려진 파일만 정리하며 기존 snapshot·다른 attempt·미확인 파일은 보존한다.

Qwen 관측은 원문 토큰·문자·순서·반복을 다시 대조한다. 공개 API의 단어 단위 관측에 문자 경계나 CTC 확률을 추정해 채우지 않는다. 프로젝트 변환 단계는 범위 밖·비유한 수·길이 0/음수·역전 관측과 겹침 양측을 해당 단어의 UNKNOWN으로 남긴다. 유효 관측은 시각을 클리핑하거나 이동하지 않고 유지한다. 원문 문자·순서·반복 불일치는 전체 실패로 처리한다. 공식 반환 시각 원본은 작업 `audio/attempt-<run_id>/qwen-observations.json`에 배타적으로 저장하고 provenance에 경로·SHA-256을 남긴다. 이 관측 근거는 다운로드 임시 파일 정리 대상이 아니다. `p=None`, `chars=[]`, `score_unavailable=True`를 기록하고 신뢰도 미제공·불확실한 음절 대응은 UNKNOWN으로 남긴다. 가사 CSV에는 `model_id`, `alignment_unit`, `score_available`, `observed_word_start_s`, `observed_word_end_s`를 추가했다. Qwen은 기존 `ctc_starts_s`·`ctc_end_s`·`mms_onsets_s`에 대신 계산한 단어 시각을 채우지 않고 빈칸으로 둔다. UNKNOWN 수 감소를 모델 정확도 향상의 근거로 자동 판정하지 않는다. 파싱·보존 검증과 실제 가창 대응 검증을 분리한다.

파일 이동 없이 다음 책임을 기존 경계에 추가하거나 새 담당자에 분리했다. 경로는 프로젝트 루트 기준이다.

| 변경 전 담당자와 소스 근거 | 책임과 배치 | 변경 후 담당자와 실제 경로 | 상태·쓰기·수명 이전 | 호출자·호환성·검증 | 남은 책임과 판정 |
| --- | --- | --- | --- | --- | --- |
| `audio/transcript.py`의 영어 Base/MMS 자동 선택과 새 GUI 선택 요구 | 가중치 로딩 없는 모델 식별·언어·선택 정책 | [audio/model_catalog.py](../svp_alignment/audio/model_catalog.py) | 상수·선택 목록·라우팅·이전 선택 복원 함수를 소유. 모델 텐서·파일·변경 가능 상태 없음 | transcript·일반 입력 검사·jobs·UI가 같은 선택값 사용. 기존 ENGLISH_MODEL 등 상수 참조 호환 확인 | COMPLETE — 모델 선택 정책 분리·호환 상수 참조와 백엔드 25개 검사 확인 |
| `audio/models.py`의 단일 CTC 파일 다운로드와 새 Qwen 다중 파일 snapshot | Qwen revision·파일 집합·무결성·게시 경계 | [audio/qwen_cache.py](../svp_alignment/audio/qwen_cache.py), [models.py](../svp_alignment/audio/models.py) | Qwen 고유 staging·FileLock·8개 파일·snapshot 해시·실패 정리 소유. 기존 가중치 덮어쓰기 금지. CTC 단일 파일 캐시는 기존 담당자 유지 | worker ensure_model이 모델별 캐시 담당자에 위임. 기존 경로와 다운로드 계약 유지 확인 | COMPLETE — Qwen snapshot 소유권 분리·캐시/취소 정리 검사 확인. 실제 다운로드 결과는 아래 별도 기록 |
| `audio/inference.py`의 CTC 문자 계산과 새 Qwen 관측 형식 | Qwen 추론·단어 관측과 원문 대응 | [audio/qwen_inference.py](../svp_alignment/audio/qwen_inference.py) | worker 내부에서 aligner·장치·텐서 생성/해제. 300초 제한·원문 대조·점수 미제공 소유 | worker가 모델별 추론에 위임. 공통 원문 토큰·시각 결과 계약, 새 문자/확률 생성 금지 확인 | COMPLETE — Qwen 관측 전담 분리·단어 경계/원문/점수 미제공 검사 확인. 실제 추론은 아래 별도 기록 |
| 기존 transcript/worker/alignment의 Base/MMS 분석 요청 | 선택 모델이 고정된 작업 프로세스 수명과 관측 이력 | [audio/alignment.py](../svp_alignment/audio/alignment.py), [worker.py](../svp_alignment/audio/worker.py), [transcript.py](../svp_alignment/audio/transcript.py) | 선택·실제 모델·입력·설정 서명을 기록. 기존 실제 PID·종료대기·공유 잠금·작업별 attempt 수명 유지 | Large/Qwen/기존 모델을 같은 align_words 호출과 worker 경계로 실행. 취소와 캐시 혼용 차단 확인 | NO_SPLIT_REQUIRED — 기존 작업 프로세스 수명 유지, 요청·캐시 검증과 담당자 위임·실제 PID 취소 검사 확인 |
| jobs의 입력 해시 기반 자동 Counting Stars 경로와 모델 미기록 작업 | 선택 모델 검사·재검증·이전 작업 호환 | [jobs/processing.py](../svp_alignment/jobs/processing.py), [manager.py](../svp_alignment/jobs/manager.py), [general_pipeline.py](../svp_alignment/general_pipeline.py) | model_choice/model_id 바인딩, 명시 cache만 허용, 이전 미완료 실행/저장 차단. 완료 파일 수명 보존 | prepare_song→선택 모델 관측→lyrics만 적용. 기존 CLI·새/이전 결과 이름·strict 보존 검사 유지 확인 | NO_SPLIT_REQUIRED — 기존 경로 선택·작업 수명 담당자 유지, 실행 모델 교차 검사·서명·lyrics 보존 집중 검사 확인 |
| 언어 dropdown만 있던 화면과 이벤트 입력 목록 | 모델 선택 컴포넌트·이벤트 구성 | [ui/gradio_app.py](../svp_alignment/ui/gradio_app.py) | `model-choice` dropdown 추가. MODEL_CHOICES를 catalog에서 읽고 사용자 입력 이벤트가 무효화 콜백에 위임. 모델 로딩·변경 가능 서버 자원 소유 없음 | 직접 UI 26개와 실제 ASGI 1개에서 모델 입력·복원 이벤트 구성 확인. 파일 이동·자원 소유권 이전 없음 | NO_SPLIT_REQUIRED — 기존 화면 구성 책임에 응집 |
| 기존 파일/언어 서명과 18개 콜백 출력 | 세션 입력 결합·작업 API 위임 | [ui/callbacks.py](../svp_alignment/ui/callbacks.py) | 모델을 서명에 결합하고 JobManager에 전달. 19개 출력으로 모델 복원, 작은 State 계약 유지. 작업·파일·모델 자원은 기존 담당자 소유 | UI/ASGI 27개에서 변경 후 stale 실행 차단·이전 완료 다운로드·실제 Progress/SelectData 인자 주입 확인 | NO_SPLIT_REQUIRED — 세션 식별과 위임의 기존 경계 유지 |
| 기존 언어·상태만 표시한 요약 변환 | 선택 모델·실제 모델과 이전 작업 안내 표현 | [ui/presentation.py](../svp_alignment/ui/presentation.py) | 저장된 summary를 읽어 표시만 변환. 모델 이력 미상과 이전 미완료 재검사를 표시. 상태·파일 쓰기 없음 | UI/ASGI 27개에서 실제 모델 표시·미완료 실행/저장 비활성화 확인. 브라우저 화면은 NOT_RUN | NO_SPLIT_REQUIRED — 읽기 전용 표현 책임 유지 |
| 기존 CTC 문자 시각·확률 기반의 일반 곡 음절 후보와 매칭 비용 | Qwen 실제 단어 범위를 고정 음표 대응 근거로 전달 | [alignment/general_lyrics.py](../svp_alignment/alignment/general_lyrics.py), [general_matching.py](../svp_alignment/alignment/general_matching.py) | 단어 창을 그대로 전달하고 내부 음절·문자 시각이나 확률을 생성하지 않음. 고정 음표와의 겹침·간격으로 대응하며 미제공 확률은 중립 비용 처리. 상태·파일·자원 소유권 변경 없음 | 원문 순서·반복·전체 단어 배치 계약과 lyrics 외 동일성 검사 유지. word-only 후보·가짜 시각/점수 차단 집중 검사 통과 | NO_SPLIT_REQUIRED — 기존 음절 근거·대응 정책의 경계 유지 |
| CTC 전용 이름을 재사용한 일반 곡 가사 CSV·보고서 | 모델별 관측 단위와 실제 점수 제공 여부 표현 | [verification/general_reporting.py](../svp_alignment/verification/general_reporting.py) | 계산된 후보를 읽어 CSV·Markdown 형식으로 변환. model_id·alignment_unit·score_available·관측 단어 범위를 표시하고 Qwen의 CTC/MMS 칸은 비움. 모델·작업 상태·파일 쓰기 소유 없음 | 기존 Counting Stars CLI 보고서 형식은 유지. 단어 관측을 문자 시각·CTC 확률로 표시하지 않는 집중 검사 확인 | NO_SPLIT_REQUIRED — 기존 검증 표현 책임에 응집 |

| 신규 검사 | 결과와 근거 |
| --- | --- |
| 모델별 선택·캐시·원문 대응·취소 집중 검사 | PASS — 음성 백엔드 집중 25개, 실제 PID 취소·잠금 해제 포함 |
| UI 콜백·구성·실제 업로드 전송 | PASS — 직접 UI 26개와 실제 ASGI 1개, 총 27개. FileData→명시 모델 입력 검사→언어/모델 복원→다른 모델의 이전 작업 실행 차단, 실제 Progress/SelectData 인자 전달 확인 |
| 모델 선택·관측·가사 전용 핵심 집중 검사 | PASS — 루트 집중 41개. 실행 model_id 교차 검사·모델 선택 서명 변경·Qwen 단어 관측의 가짜 문자/점수 차단·lyrics 외 전체 보존 포함 |
| 전체 회귀·기존 CLI 바이트 호환·음표 전체 보존 | PASS — 최종 전체 154개, 70.019초, exit 0. Qwen 원시 관측 UNKNOWN 처리·CSV 표시와 UI 최종 문구 반영 후 재실행. 이전 127개 및 중간 150개 통과와 구분 |
| 신규 의존성 설치·버전 보존·pip check | PASS — 같은 .venv에 28개 추가. 기존 71개 버전 변경 0개, 현재 설치 99개·런타임 requirements 97개 일치. pip check: No broken requirements found. qwen-asr 실제 import·영/한/일 토큰화·한국어 사전 자산 확인 |
| 영어 Large 실제 CUDA 가창 추론 | PASS — 자동 모델 선택으로 새 작업 `f7e1c1aa-07d7-405e-a11e-560899ea08da`. Shooting Stars 227.07초, 저장 포함 34.4초, 새 관측. 281개 음표·240단어 중 229배치·11미배치, UNKNOWN 음표 208개·단어 167개 |
| 실제 Large 결과 음표·복원 | PASS — onset/duration/pitch 변경 0개·lyrics 267개 변경. lyrics 외 JSON 전체 동일, COMPLETED 복원과 auto 선택 보존 |
| Qwen 실제 CUDA 가창 추론 | PASS — 새 작업 `bf1513c3-9663-4ab6-a5a1-7bb1ad29d974`. Shooting Stars 227.07초를 CUDA에서 새로 분석, 저장 포함 37.576초. 240단어 중 124배치·116미배치, 시각 미지원 관측 47단어. UNKNOWN 음표 281개·단어 240개는 단어 관측 검토 정책 포함 |
| 실제 Qwen 결과 음표·복원 | PASS — onset/duration/pitch 변경 0개·lyrics 153개 변경. lyrics 외 JSON 전체 동일, COMPLETED 복원·Qwen 선택 보존. 원시 반환 자료 경로·SHA-256을 provenance에 기록 |
| 실제 Qwen CSV 관측 표현 | PASS — 가사 CSV 240행 모두 Qwen model_id·word 단위, score_available=false. CTC 시작/종료/확률·MMS 칸 전부 빈칸이며 단어 범위 별도 열로 표시 |
| 정적 검사·공개 타입 배치 | PASS — 프로덕션 Python 54개 AST/compile 및 파일당 최상위 공개 프로젝트 클래스 하나 이하 확인 |
| 원본·기존 결과·실행 설정 보존 | PASS — 보호 대상 18개 SHA-256 변경 0개(원본 3개·기존 결과 8개·AGENTS/app/Start_GUI/기존 CLI 관련 파일). app.py --help 기본 포트 28670, 프로덕션 compile 재확인 |
| 실제 브라우저 화면·청취·Studio 열기·합성 | NOT_RUN — 자동 코드 검사와 구분 |
| 전체 가창 대응 | NOT_VERIFIED — 자동 가사 대응 후보이며 청취 검토가 남음 |

실제 자동 선택 Large 결과의 [SVP](<../outputs/f7e1c1aa-07d7-405e-a11e-560899ea08da/Shooting Stars 여자 커버_LYRICS_FILLED.svp>)와 [보고서](<../outputs/f7e1c1aa-07d7-405e-a11e-560899ea08da/Shooting Stars 여자 커버 - Verification.md>)를 새 폴더에 저장했다. 이전 Base·타이밍 수정 결과를 덮어쓰지 않았다. Large의 UNKNOWN 수가 이전 Base보다 많으므로 모델 크기 변경을 가창 대응 정확도 향상으로 확정하지 않는다. 비교는 같은 발음 구간의 실제 청취·음절 대응 검토가 필요하다.

Qwen을 직접 선택한 [SVP](<../outputs/bf1513c3-9663-4ab6-a5a1-7bb1ad29d974/Shooting Stars 여자 커버_LYRICS_FILLED.svp>)와 [보고서](<../outputs/bf1513c3-9663-4ab6-a5a1-7bb1ad29d974/Shooting Stars 여자 커버 - Verification.md>)도 별도 작업으로 보존했다. 이번 영어 곡에서는 Qwen 미배치가 116단어로 Large의 11단어보다 많았다. Qwen의 UNKNOWN 281음표·240단어는 단어 창만 제공하고 점수를 제공하지 않는 검토 정책까지 포함하므로 모델 정확도 수치로 직접 비교하지 않는다. 두 결과 모두 전체 가창 대응은 NOT_VERIFIED이며 실제 청취·음절 경계 검토가 필요하다.

Qwen의 [원시 반환](../work/model-upgrade/models-1794659257537/qwen-full-song-raw-bf1513c3-9663-4ab6-a5a1-7bb1ad29d974.json)과 [진단 기록](../work/model-upgrade/models-1794659257537/qwen-full-song-diagnostic-bf1513c3-9663-4ab6-a5a1-7bb1ad29d974.json)을 대조했다. 반환 240단위 중 정상 양수 길이·WAV 범위 내 시각은 193개, 길이 0은 46개, 양수 길이의 WAV 끝 초과는 1개였다. 실제 겹침·역전 쌍은 0개였다. 따라서 47단어의 시각만 UNKNOWN으로 보류하고 정상 193개는 원래 반환 시각을 유지했다. **가사 검토 표의 UNKNOWN 240단어**는 단어 관측을 음절·고정 음표에 대응할 때의 검토 정책까지 포함하며 **시각 관측 미확정 47단어**와 다른 수치다. [실제 최종 실행 기록](../work/model-upgrade/models-1794659257537/qwen-final-run.jsonl)에 작업·장치·보존 검사를 기록했다.

최종 [154개 회귀 검사 로그](../work/model-upgrade/models-1794659257537/final-regression-154.log), [Qwen CSV 검사](../work/model-upgrade/models-1794659257537/qwen-report-audit.json), [보호 파일 해시 검사](../work/model-upgrade/models-1794659257537/preservation-audit.json)에 근거를 남겼다. 구조 판정은 새 담당자 3개와 기존 정책·작업·표현 경계에 대해 COMPLETE 또는 NO_SPLIT_REQUIRED로 완료했으며, 실제 가창 정확도 판정과 분리한다.

## 연속 음표 구간 배치와 가사 교정

2026-11-14–15 후속 구현은 `word_note_groups_v1` 정책으로 단어별 연속 음표 구간과 음절·지속음을 함께 배치한다. 음절보다 음표가 적으면 원문의 정확한 조각으로 압축한 후보를 허용하고, 출처 없는 기본 가사가 `+` 체인에 끼는 출력을 검증으로 차단한다. CTC 문자 종료를 실제 발음 종료로 사용하지 않으며 다음 단어·미지원 토큰·악보 공백을 지속음 제안의 경계로 사용한다. 미대응·미배치와 배치 후 검토·사용자 확인을 분리하고 부분 초안 저장을 표시한다.

새 일반 곡 REVIEW_READY 초안에는 원문·음표 범위·단어·+/−·사용자 확인 교정기가 제공된다. 교정은 입력 서명·정확한 초안 버전·검토 문맥 해시와 원문 순서를 확인한 뒤 공용 기호 렌더러·최종 가사 검증·엄격 보존 검사를 통과해야 한다. 이전 초안은 불변이고 현재 버전은 manifest에서 선택한다. 복원·내보내기 때 모델을 다시 실행하지 않는다. 기존 COMPLETED와 Counting Stars 기존 분석 자료의 가사 대응을 새 정책으로 소급 변경하지 않으며 해당 캐시 옵션은 새 세부 품질 미상·교정 비활성이다.

책임 이전 6열 표, 호환·품질 스키마, 실제 Run Boy Run 집중 자료와 최종 검증은 [가사 배치 개선 기록](lyrics-placement-improvement-plan.md#6-책임-경계와-실제-배치)과 [검증 기록](lyrics-placement-improvement-plan.md#8-구현과-검증-기록)에 모아 관리한다. 이전 154개·CUDA 실행을 이번 구현의 검증 수치로 합산하지 않는다. Studio 열기·기호 해석·합성·청취와 실제 브라우저 화면은 NOT_RUN이며 전체 가창 대응은 NOT_VERIFIED다.

## ASR 1.7B 인식 대조 선택

2026-11-15 **Qwen3 ASR 1.7B + ForcedAligner 0.6B · 인식 대조**를 명시적인 모델 선택으로 추가했다. 자동 모델 기본값은 유지한다. ASR는 WAV를 인식하고 정렬 모델은 인식 문장의 단어 시각을 추정한다. 제공 TXT는 최종 가사의 기준으로 유지하며 전체 순서의 정확 대응이 없거나 반복 위치가 모호하면 UNKNOWN으로 보류한다. 기존 GUI의 입력 무효화·복원·교정·저장 계약과 음표 고정은 유지한다.

화면과 보고서는 ASR+단어 정렬을 CTC 문자 관측으로 설명하지 않는다. 문자 시각·신뢰도 점수를 만들지 않으며 저장 관측의 재사용과 새 추론을 구분한다. 새 구성 요소·책임 경계·가중치 이력·실제 실행·전체 검사 근거는 [무거운 모델 실험 기록](heavy-model-experiment.md)에 모아 관리한다. 과거 154개 또는 205개 통과를 이 확장의 새 검증 수치로 사용하지 않는다.
