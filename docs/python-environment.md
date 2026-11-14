# 프로젝트 Python 가상환경

설치·활성화·패키지 설치 및 실행 방법은 [README](../README.md#가상환경-설치)에 있습니다. 전체 패키지 버전은 [requirements.txt](../requirements.txt)를 기준으로 재설치합니다.

## 환경

- 확인 날짜: 2026-11-14
- Windows 64비트, 프로젝트 내부 `.venv`
- Python 3.10.22, pip 26.3
- 외부 환경의 site-packages 미상속 (`include-system-site-packages = false`)
- 기반 Python: `C:\Users\jaewo\.conda\envs\lavi_singer\python.exe`

기반 Python의 설치 위치가 바뀌면 `.venv`를 다시 만들어야 합니다. PowerShell 실행 정책 변경 없이 `.venv\Scripts\python.exe`를 직접 지정해서 사용할 수 있습니다.

## 기존 분석·GUI 직접 의존성

| 패키지 | 설치 버전 |
| --- | --- |
| `numpy` | `1.26.4` |
| `scipy` | `1.15.3` |
| `soundfile` | `0.13.1` |
| `praat-parselmouth` | `0.4.6` |
| `torch` | `2.8.0+cu128` |
| `torchaudio` | `2.8.0+cu128` |
| `transformers` | `4.57.6` |
| `gradio` | `6.17.3` |
| `uroman` | `1.3.1.1` |

분석용 런타임 30개에 Gradio 의존성을 추가한 68개 환경에서, 일반 곡 다국어 정렬의 원문 로마자화에 필요한 `uroman==1.3.1.1`을 추가했습니다. 기존 Base/MMS 분석·GUI 환경의 직접·하위 의존성 총 69개를 `requirements.txt`에 고정했습니다. 기존 분석 패키지 버전은 유지했습니다. 설치 도구인 pip와 setuptools는 해당 목록에서 제외합니다.

## 분석 환경 최초 설치 검증 결과

| 검사 | 결과 |
| --- | --- |
| 가상환경 격리 | `PASS` |
| `pip check` | `PASS` — No broken requirements found |
| requirements와 설치된 버전·직접 wheel URL 및 해시 대조 | `PASS` — 런타임 패키지 30개 일치 |
| 직접 의존성 7개와 Transformers 실행 클래스 import | `PASS` |
| SciPy 리샘플링 | `PASS` — 16 kHz 사인파를 8 kHz로 변환 |
| SoundFile WAV 왕복 | `PASS` — 메모리에서 쓰기·읽기 |
| Praat 피치 추정 | `PASS` — 440 Hz 사인파 |
| TorchAudio `MMS_FA` 레이블 접근 | `PASS` — 모델 다운로드 없음 |
| `forced_align`, `merge_tokens` | `PASS` — 작은 합성 입력의 토큰 순서 확인 |
| Whisper 모델 순전파 | `PASS` — 작은 무작위 초기화 모델, 가중치 다운로드 없음 |
| CUDA 텐서 연산 | `PASS` — NVIDIA GeForce RTX 5070 Ti, CUDA 12.8 |
| `work/counting_stars/run.py --help` | `PASS` |
| 최초 설치 시 전체 음원 재분석·결과 재생성 | `NOT_RUN` — 당시 범위는 환경 설치와 문서화. 후속 GUI 구현의 재생성 검증은 아래 구현 기록 참조 |

가상환경의 구형 pip에서 발생한 HTTPS 인증서 오류는 Windows 신뢰 인증서를 이용해 pip를 업데이트하여 해결했습니다. 시스템 인증서 설정이나 PowerShell 실행 정책은 변경하지 않았습니다.

## Gradio GUI 환경

기존 분석 패키지 버전을 제약 조건으로 고정한 resolver 검사에서 Gradio 6.17.3을 선택하고 설치했습니다. GUI 실행은 [README](../README.md#gradio-gui-실행), 코드·검증 결과는 [GUI 구현 기록](gradio-gui-implementation.md)에 있습니다. `pip check`와 앱 구성 및 콜백 검증을 수행하며, 브라우저의 실제 화면 검증 결과와 구분합니다.

## 일반 곡 CTC 분석 환경 이력

다음은 모델 선택 확장 전 Base/MMS 환경의 구현·검증 이력입니다. 현재 모델 선택·설치 계약은 아래 큰 모델 절을 따릅니다. GUI는 기존 음표를 고정하고 `lyrics`만 변경하며, 모델은 고정 음표에 가사를 대응시키는 발음 시각 근거를 제공합니다. 당시 기존 Counting Stars 입력 해시와 기존 관측 자료·연결 오디오 검사까지 통과한 경우 저장된 가사 대응 자료를 사용합니다. 캐시 조건이 맞지 않으면 실패 사유를 경고에 남기고 다른 입력과 마찬가지로 업로드 WAV·TXT의 새 CTC 강제 정렬을 수행합니다. 기존 타이밍 조정 CLI의 검증 계약은 유지합니다. 영어는 `WAV2VEC2_ASR_BASE_960H`, 다국어는 `MMS_FA`와 uroman을 사용합니다. 모델 선택과 언어 설정은 작업 이력에 기록하며 원문 TXT를 수정하지 않습니다.

모델이 없으면 실행 중 공식 모델 주소에서 영어 약 377.7 MB 또는 MMS 약 1.18 GiB를 다운로드합니다. 새 모델 캐시는 `work/models/torchaudio/`에 저장하고 기존 지원 캐시는 읽기 전용으로 재사용합니다. 모델 파일의 SHA-256, 입력 해시, 설정, 패키지 버전과 실제 장치를 작업별 `work/gradio/<작업 ID>/audio/` 관측 자료에 기록합니다. 기존 모델 파일을 덮어쓰지 않으며 작업 간 FileLock을 사용합니다.

CUDA가 사용 가능하면 GPU로 계산하고 CPU 경로와 GPU 메모리 부족 시 CPU 재시도도 구현했습니다. 실제 Shooting Stars의 영어 전체 WAV를 CUDA에서 처리한 결과는 **이전 타이밍 수정 정책의 실행 이력**입니다. CPU 전체 추론과 MMS 실제 가창 추론은 아직 실행하지 않았으므로 해당 품질을 통과로 표시하지 않습니다. 가사 전용 변경 전에 전체 108개 회귀 검사가 35.864초에, 추가 경계 수정 후 당시 최종 116개가 44.152초에 통과했고 `pip check`도 `No broken requirements found.`로 통과했습니다. 이 수치를 현재 가사 전용 정책의 검증으로 사용하지 않습니다. 이전 결과는 [일반 곡 확장 검증](gradio-gui-implementation.md#일반-곡-확장-검증), 신규 검증 상태는 [가사 전용 변경](gradio-gui-implementation.md#음표-고정가사-전용-변경)에 따로 기록합니다.

가사 전용 변경 후에도 Shooting Stars의 227.07초 WAV를 CUDA에서 새로 분석했습니다. 새 작업 `a7da05ed-9aa2-426d-a772-032b84ecb955`는 저장 포함 21.542초에 완료했고, 음표 시작·길이·음높이 변경 없이 가사 263개만 변경했습니다. 이 실행 역시 CPU 전체 추론·MMS 실제 가창 품질·청취 검증을 대신하지 않습니다.

가사 전용 변경 후 전체 **127개 회귀 검사(64.526초)**와 `pip check`가 통과했습니다. 모델·의존성 버전은 변경하지 않았습니다. 이 시점의 검증과 이전 정책의 실행 이력은 GUI 구현 기록의 각각 다른 절에서 확인합니다.

## 큰 모델과 모델 선택 환경

모델 선택 확장의 기본값은 `auto`입니다. 영어는 `WAV2VEC2_ASR_LARGE_LV60K_960H`, 지원 비영어 언어를 명시하면 `Qwen/Qwen3-ForcedAligner-0.6B`, 언어 자동의 비ASCII 가사나 다국어는 `MMS_FA`를 사용합니다. GUI에서 Large·Qwen·MMS·기존 Base를 직접 선택할 수 있습니다. 기존 Counting Stars 관측 재사용도 별도 선택이며, 기본 자동에서는 해당 곡도 새 모델로 분석합니다.

Qwen의 공식 `qwen-asr==0.0.6`은 프로젝트의 같은 `.venv`에서 사용합니다. 별도 Python 환경이나 외부 API를 사용하지 않습니다. 설치는 README의 `requirements.txt` 설치 명령을 따릅니다. `requirements.txt`에는 기존 69개 버전을 유지하면서 Qwen 런타임 28개를 추가해 총 97개를 고정했습니다. 추가 패키지에는 `qwen-asr==0.0.6`, `qwen-omni-utils==0.0.9`, `accelerate==1.12.0`, `nagisa==0.2.11`, `soynlp==0.0.493`이 포함됩니다. 설치 후 기존 71개(런타임 69개와 pip/setuptools)의 버전 변경은 0개였으며 현재 총 99개 중 런타임 97개가 requirements에 일치합니다. `pip check`는 `No broken requirements found.`로 통과했습니다. 이전 69개·127개 통과는 이번 환경 변경의 검증으로 간주하지 않습니다.

| 모델 | 새 캐시 위치와 제약 |
| --- | --- |
| 영어 Large / 영어 Base / MMS | `work/models/torchaudio/`. 기존 지원 캐시는 읽기 전용 재사용. Large 1,262,046,195 bytes(약 1.26 GB), Base 약 377.7 MB, MMS 약 1.18 GiB. 선택 모델이 없으면 최초 실행 때 다운로드 |
| Qwen3-ForcedAligner 0.6B | `work/models/qwen/1c85775dfe71a2a90e6aeea682c6eb9df3d8848b/`. 고정 revision의 8개 공개 파일 1,840,013,484 bytes(약 1.84 GB)와 `snapshot.json`. 가중치 SHA-256 및 파일별 해시 검사. 한 번에 300초 이하 WAV |

영어 Large의 실제 다운로드 파일은 1,262,046,195 bytes이며 SHA-256은 `7a88965716fbd598a595209bf45c1210a18a6935cfb0cf53527fc986c5543ac7`입니다. Qwen 8개 파일과 revision manifest의 전체 fingerprint는 `45c4a57b2f9cbaea7344d0363e47fdb2e15dde660a6f6f2ac34961d3a2054fa8`입니다. 모델 다운로드 완료와 실제 추론 검증은 구분합니다.

모델 선택 UI와 입력 검사는 모델을 GPU에 로드하지 않습니다. 실행 단계의 별도 worker가 CUDA/CPU 텐서를 소유하며 취소 시 실제 PID 종료·대기를 마친 뒤 작업 간 잠금을 해제합니다. GPU가 사용 가능하면 CUDA를 사용하고 메모리 부족 시 같은 모델을 CPU에서 다시 계산합니다. 선택한 모델을 실패 시 다른 모델로 바꾸지 않습니다.

모델 선택값과 실제 모델 ID·revision·입력 해시·가중치 해시·설정·패키지 버전·실제 장치를 관측 이력에 기록합니다. 모델이나 언어를 바꾸면 기존 검사 연결을 해제하며 재검사가 필요합니다. 같은 작업의 관측 캐시도 모델 선택과 실제 모델·원본·설정·버전이 모두 같아야 재사용합니다.

Qwen은 제공된 가사를 단어 단위 시각에 대응시키는 관측을 사용합니다. 공식 반환 시각 중 범위 밖·길이 0·겹침·역전 등은 프로젝트 변환에서 보정하지 않고 해당 단어를 UNKNOWN으로 남깁니다. 반환 원문이 입력 문자·순서·반복과 다르면 중단합니다. 원시 관측은 작업 attempt의 `qwen-observations.json`과 provenance의 파일 해시로 보존합니다. 공개 정렬 API가 반환하지 않는 CTC 문자 점수·문자별 경계를 만들어 넣지 않습니다. `p=None`, `chars=[]`, `score_unavailable=True`를 기록하며 점수 미제공과 내부 음절 경계 등 불확실성을 UNKNOWN으로 남깁니다. Qwen 공식 지원은 11개 언어의 음성이며 실제 가창 품질은 별도 청취 검토 대상입니다. [공식 모델 설명](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)

신규 모델 실제 추론·환경·회귀 검증 결과는 [큰 모델과 GUI 모델 선택](gradio-gui-implementation.md#큰-모델과-gui-모델-선택)에 기록합니다. 신규 환경에서 `qwen-asr` 실제 import와 ForcedAlignProcessor의 영어·한국어·일본어 토큰화를 통과했습니다. 한국어 사전 17,968개 항목이 설치 wheel의 자산에 포함된 것도 확인했습니다. 이는 모델 가중치의 실제 가창 추론·정확도 검증과 구분합니다.

실제 자동 모델 선택은 영어 Large를 사용해 Shooting Stars 227.07초 WAV를 CUDA에서 새로 처리했습니다(작업 `f7e1c1aa-07d7-405e-a11e-560899ea08da`, 저장 포함 34.4초). 음표 시작·길이·음높이 변경 0개와 lyrics 외 JSON 전체 동일성을 확인했습니다. 이 실행을 CPU·MMS·다국어 가창 정확도 검증으로 간주하지 않으며 Large가 Base보다 정확하다고 자동 판정하지 않습니다.

신규 환경의 설치 버전·원래 버전 불변·requirements 대조 근거는 [환경 검사 기록](../work/model-upgrade/models-1794659257537/environment-audit.json)에 있습니다. 프로덕션 Python 54개 AST/컴파일 및 공개 타입 배치 검사도 통과했습니다.

Qwen도 같은 Shooting Stars WAV에서 실제 CUDA 실행·저장을 완료했습니다(작업 `bf1513c3-9663-4ab6-a5a1-7bb1ad29d974`, 37.576초). 음표 시작·길이·음높이 변경 0개와 lyrics 외 JSON 전체 동일성을 확인했습니다. 이번 영어 곡의 Qwen은 240단어 중 124배치·116미배치였으므로 영어 기본값은 Large를 유지합니다. Qwen의 전체 UNKNOWN 검토 정책을 정확도 통과로 해석하지 않습니다. 다국어 가창·CPU 전체 추론은 여전히 NOT_RUN입니다.

최종 전체 **154개 회귀 검사(70.019초)**와 pip check를 통과했습니다. 기존 CLI 바이트 호환, 가사 외 필드 완전 보존과 모델 선택·복원·취소·캐시 계약을 포함합니다. [최종 회귀 로그](../work/model-upgrade/models-1794659257537/final-regression-154.log)와 [보호 파일 검사](../work/model-upgrade/models-1794659257537/preservation-audit.json)를 참고합니다.

## ASR 1.7B 실험 환경

2026-11-15 추가한 명시 선택 **Qwen3 ASR 1.7B + ForcedAligner 0.6B**도 같은 `.venv`의 `qwen-asr==0.0.6`을 사용합니다. 패키지나 `requirements.txt` 변경 없이 원래 `Qwen/Qwen3-ASR-1.7B` 체크포인트와 기존 정렬 모델을 조합합니다. `-hf` 이름의 별도 체크포인트를 불러오기 위해 Transformers를 업그레이드하지 않습니다. 모델 가중치는 프로젝트 `work/models/`에 두고 두 구성 요소를 각각 revision·파일 해시로 검증합니다.

ASR가 제공 TXT를 정답으로 읽지 않고 WAV를 인식하므로 오인식·반복 누락이 있을 수 있습니다. 인식문과 단어 시각 원본을 저장한 뒤 TXT와 순서대로 대응하며 가사의 기준은 TXT로 유지합니다. 새 선택의 설치·다운로드·실제 GPU 추론·회귀 검사와 한계는 [무거운 모델 실험 기록](heavy-model-experiment.md)을 참고합니다. 기존 단독 ForcedAligner의 CUDA 실행 기록은 새 ASR 모델 검증을 대신하지 않습니다.
