# SVP 가사 번역 및 타이밍

Synthesizer V의 SVP 음표에 가사를 넣는 작업 공간입니다. **GUI는 기존 음표를 고정한 채 `lyrics`만 변경합니다.** 음표의 시작·길이·음높이·개수·순서와 그 밖의 프로젝트 필드는 그대로 유지합니다. 업로드한 곡의 WAV·TXT를 선택한 모델로 분석해 고정된 음표에 가사를 대응시킵니다. 기본 모델 선택은 영어 Wav2Vec2 Large와 지원 언어의 Qwen3-ForcedAligner이며, GUI에서 다른 모델도 고를 수 있습니다. Counting Stars 기존 자료는 별도 옵션을 선택한 경우에만 사용합니다. 기존 Counting Stars CLI의 타이밍 조정 기능은 별도 계약으로 유지합니다.

## 실행 환경

- Windows 64비트, Python 3.10
- 프로젝트 루트의 `.venv` 사용
- 새 음성 분석: 분석 모델과 원본 보컬 WAV 필요. CUDA 사용 가능 시 GPU를 사용하고, 없거나 GPU 메모리가 부족하면 CPU로 계산
- 모델이 없으면 최초 실행 때 인터넷 다운로드 필요

`requirements.txt`는 Windows/Python 3.10용 CUDA 12.8 PyTorch wheel과 설치 검증한 패키지 버전을 고정합니다. 기존 정렬 코드의 `forced_align`, `merge_tokens`, `MMS_FA` API를 사용하기 위해 `torch`와 `torchaudio`를 2.8.0으로 유지합니다. [공식 이전 버전 설치법](https://pytorch.org/get-started/previous-versions/), [TorchAudio API 제거 안내](https://docs.pytorch.org/audio/2.9.0/tutorials/ctc_forced_alignment_api_tutorial.html).

## 가상환경 설치

프로젝트 루트에서 PowerShell을 열고 다음 명령을 실행합니다. `py`에 Python 3.10이 등록돼 있어야 합니다.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

현재 PC에서 Python Launcher(`py`) 대신 확인된 Conda의 Python 3.10을 사용하려면 첫 명령을 다음으로 바꿉니다. `.venv`가 이미 있으면 생성 단계는 생략합니다.

```powershell
& "C:\Users\jaewo\.conda\envs\lavi_singer\python.exe" -m venv .venv
```


이 PC에서 새 환경의 구형 pip가 `CERTIFICATE_VERIFY_FAILED`로 업데이트에 실패하면, Windows 신뢰 인증서를 지원하는 기존 Conda의 pip로 대상 `.venv`만 업데이트할 수 있습니다.

```powershell
& "C:\Users\jaewo\.conda\envs\lavi_singer\python.exe" -m pip --python .\.venv\Scripts\python.exe install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

가상환경 활성화는 선택 사항입니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip list
deactivate
```

현재 PC에서는 PowerShell 실행 정책으로 `Activate.ps1` 실행이 제한됩니다. 위 설치 명령처럼 `.venv\Scripts\python.exe`를 직접 지정하면 활성화 없이 사용할 수 있습니다. 시스템 실행 정책을 변경할 필요는 없습니다.

## 실행 확인

현재 PC에서 `pip check`, 직접 의존성 import, CTC 정렬, 작은 Whisper 모델 순전파 및 RTX 5070 Ti의 CUDA 텐서 연산을 확인했습니다. 자세한 결과는 [설치 검증 기록](docs/python-environment.md)에 있습니다.

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import numpy, scipy, soundfile, parselmouth, torch, torchaudio; from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline; print(torch.__version__, torchaudio.__version__, torch.cuda.is_available())"
.\.venv\Scripts\python.exe .\work\counting_stars\run.py --help
```

## Gradio GUI 실행

탐색기에서 프로젝트 폴더의 [Start_GUI.bat](Start_GUI.bat)를 더블클릭하면 앱과 브라우저가 열립니다. 실행 창은 사용 중 열어 두고, 종료할 때 그 창에서 `Ctrl+C`를 누릅니다. 배치 작업 종료 여부를 물으면 `Y`를 입력합니다. 브라우저 탭만 닫으면 서버는 계속 실행됩니다. 실행 오류가 나면 창에 표시된 내용을 확인한 뒤 아무 키나 눌러 닫습니다.

터미널에서도 실행할 수 있고, 앱 옵션을 그대로 전달할 수 있습니다. 이미 실행 중인 앱이 포트를 사용하고 있으면 기존 서버를 종료하거나 다른 포트를 지정합니다.

```powershell
.\Start_GUI.bat
.\Start_GUI.bat --port 28671 --no-browser
```

Python을 직접 실행하려면 프로젝트 루트에서 다음 명령을 사용합니다. 기본 주소는 `http://127.0.0.1:28670`이며 브라우저가 자동으로 열립니다.

```powershell
.\.venv\Scripts\python.exe .\app.py
```

포트를 바꾸거나 브라우저 자동 열기를 생략할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe .\app.py --port 28671 --no-browser
```

1. **원본 SVP**, **가사 TXT**, **원본 보컬 WAV** 칸에 각 파일을 드래그하거나 클릭해 선택합니다. 업로드하면 곧바로 프로젝트의 `work/uploads/<고유 ID>/<원래 파일명>`에 복사됩니다. 세 파일의 업로드가 끝나면 **가사 언어**와 **AI 정렬 모델**을 선택하고 **입력 검사**를 누릅니다. 기본값 **자동 · 영어 Large / 지원 언어 Qwen**은 언어에 맞는 모델을 고릅니다. 더 큰 인식 모델을 비교하려면 **Qwen3 ASR 1.7B + ForcedAligner 0.6B · 인식 대조**를 직접 선택합니다.
2. **기존 음표에 가사 넣기**를 누릅니다. WAV·TXT의 관측을 바탕으로 단어가 사용할 연속 음표를 정하고 음절·지속음을 함께 배치합니다. **기존 음표의 위치와 길이는 바꾸지 않습니다.** 음표가 적으면 원문 조각으로 압축한 후보를 만들며 실제 발음 확인 전에는 검토 대상으로 남깁니다.
3. 미대응·미배치·배치 후 검토·기호 위험 등의 필터로 표를 확인합니다. 행을 선택하거나 시작·끝 초를 지정해 원본 보컬 구간을 최대 30초까지 들을 수 있습니다.
4. 새 일반 곡 초안에서는 원문 단어와 음표 범위를 선택해 단어 시작·다음 음절 `+`·지속음 `-`를 교정하거나 확인합니다. 적용하면 새 초안 버전으로 저장하고 원문 순서·기호 연결·가사 외 보존을 다시 검사합니다. 비교표 자체는 읽기 전용이며 음표 시간·음높이 편집은 제공하지 않습니다.
5. **새 결과 저장 · 다운로드 준비**를 눌러 `outputs/<작업 ID>/`에 새 SVP·CSV 2개·보고서를 저장합니다. 미대응 음표나 미배치 단어가 남으면 **부분 초안 저장 완료**로 표시합니다. 자동 배치 완료 후보도 청취·합성 확인 완료를 뜻하지 않습니다.
6. 새로고침 뒤에는 복사해 둔 작업 ID로 작업을 불러옵니다. 업로드 칸은 비워지지만 현재 정책 작업은 저장된 입력·모델·언어·초안 버전으로 계속 진행할 수 있습니다. 이전 배치 정책이나 모델 기록이 없는 일반 곡 미완료 작업은 세 파일을 다시 올려 검사합니다. 보관 경로는 검사 상세에 표시됩니다. 새 입력 검사는 세 파일을 다시 올려 시작합니다.

업로드한 파일은 매번 새 폴더에 저장해 같은 이름의 파일도 덮어쓰지 않습니다. 외부 원본은 수정하지 않으며, 입력을 교체하거나 앱을 종료해도 저장된 복사본을 자동으로 삭제하지 않습니다. SVP 내부의 오디오 경로 문자열도 보존합니다. 일반 곡은 연결 파일이 없거나 원래 상대 경로를 확인할 수 없어도 경고를 표시하고 업로드 WAV로 분석합니다. 저장한 SVP에서 연결 오디오를 재생하려면 기존 참조 위치를 확인해야 합니다. 기본 **자동** 모델은 Counting Stars도 새로 분석합니다. **Counting Stars 기존 분석 자료** 옵션은 해당 입력의 해시·기존 관측 자료·연결 오디오까지 확인한 뒤에만 사용합니다. 조건에 맞지 않으면 사유를 표시하고 중단하며 다른 모델로 자동 전환하지 않습니다. 기존 CLI는 원래 검증 계약을 유지합니다.

모델·언어 또는 파일을 바꾸면 이전 검사·결과 연결을 해제하므로 다시 검사합니다. `UNKNOWN`과 별개로 **미대응 원문 유지**, **배치 후 검토 필요**, **사용자 확인**을 구분합니다. 원문에 실제 `la`가 있으면 정상 가사로 배치하며 남은 `la`를 일괄 `-`로 바꾸지 않습니다. 저장 전후 SVP를 다시 읽어 `+`·`-`의 원문 연결과 `lyrics` 외 모든 필드의 동일성을 검사합니다. 전체 가창 대응은 `NOT_VERIFIED`이며 사용자 확인도 Studio 열기·합성 재생을 자동 통과시키지 않습니다. 입력 변경·취소·오류가 발생한 작업의 결과는 다운로드로 공개하지 않습니다.

교정은 새 일반 곡의 검토 중 초안에서만 가능합니다. **Counting Stars 기존 분석 자료** 옵션은 기존 대응을 유지하므로 새 세부 품질은 미상이며 교정기가 비활성화됩니다. 기존 완료 결과는 읽기 전용으로 보존합니다. 두 화면에서 같은 초안을 열었다면 먼저 적용한 교정 뒤의 오래된 화면은 거부되므로 작업을 다시 불러옵니다.

정책 변경 전에 만든 `_TIMING_FIXED.svp` 결과 파일과 계산 내용은 새 정책 결과로 덮어쓰지 않습니다. 완료한 이전 작업은 **이전 타이밍 수정 작업**으로 표시해 기존 파일 내용 그대로 복원할 수 있습니다. 이전 정책 또는 모델 선택 추가 전에 검사·계산만 마친 미완료 작업은 실행·저장할 수 없으므로 파일 세 개를 다시 올려 모델을 선택하고 검사합니다. 기존 완료 작업은 당시 모델과 결과를 그대로 복원합니다. 작업 상태 기록에는 재검사 요구나 중단 상태를 갱신할 수 있습니다.

GUI를 종료하려면 실행한 터미널에서 `Ctrl+C`를 누릅니다. 기존 CLI 사용법도 유지됩니다.

## GUI 음성 분석과 지원 범위

**AI 정렬 모델**에서 모델을 선택합니다. 기본 **자동 · 영어 Large / 지원 언어 Qwen**은 영어에 Wav2Vec2 Large를, 명시한 지원 비영어 언어에 Qwen3-ForcedAligner를 사용합니다. 언어를 자동으로 두고 비ASCII 가사만으로 언어를 확정할 수 없으면 MMS를 사용합니다. 한국어·일본어 곡은 **가사 언어**를 직접 지정하면 Qwen 경로를 선택할 수 있습니다. 언어 선택은 번역 기능이 아닙니다. Qwen 계열을 직접 선택한 비ASCII 가사는 지원 언어를 지정해야 합니다. **단독 ForcedAligner 0.6B와 ASR 1.7B 조합은 앱에서 WAV 300초 이하**를 지원하며 긴 곡은 영어 Large 또는 MMS를 선택합니다. ASR 조합의 검증 범위는 [무거운 모델 실험 기록](docs/heavy-model-experiment.md)을 참고합니다.

| 선택 | 사용하는 모델과 용도 |
| --- | --- |
| 자동 · 영어 Large / 지원 언어 Qwen | 영어 Large, 지원 비영어 Qwen, 언어 미확정 다국어 MMS로 선택 |
| Wav2Vec2 Large LV60K · 영어 | `WAV2VEC2_ASR_LARGE_LV60K_960H`, 영어의 새 기본 모델 |
| Qwen3 ForcedAligner 0.6B · 다국어 | `Qwen/Qwen3-ForcedAligner-0.6B`, 영어·한국어·일본어·중국어·프랑스어·독일어·스페인어의 명시 언어 정렬 |
| Qwen3 ASR 1.7B + ForcedAligner 0.6B · 인식 대조 | WAV를 1.7B로 인식하고 인식 문장을 0.6B로 단어 정렬한 뒤 제공 TXT와 대응. TXT를 인식문으로 바꾸지 않으며 미대응·모호한 단어는 UNKNOWN |
| MMS FA · 다국어 | 기존 다국어 CTC 모델과 uroman |
| Wav2Vec2 Base · 영어 | 기존 `WAV2VEC2_ASR_BASE_960H`, 속도·결과 비교용 |
| Counting Stars 기존 분석 자료 | 해당 입력과 관측 자료의 검사를 통과한 경우에만 기존 자료 재사용. 새 모델 추론 없음 |

Large의 학습 범위는 [TorchAudio 공식 설명](https://docs.pytorch.org/audio/2.8/generated/torchaudio.pipelines.WAV2VEC2_ASR_LARGE_LV60K_960H.html)을 따릅니다. Qwen 강제 정렬 모델의 공식 지원은 11개 언어의 음성 정렬이며, 이 앱에서는 GUI가 제공하는 언어만 지정합니다. 가창 정확도는 실제 곡으로 검토해야 합니다. [Qwen 공식 모델 설명](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)

ASR 1.7B 조합은 기존 `qwen-asr` 설치를 사용하고 최초 실행 때 추가 가중치를 내려받습니다. 제공 TXT는 인식 정답으로 입력하지 않으며 최종 가사의 기준으로 유지합니다. 두 모델의 ID·가중치 해시와 원시 인식문·단어 관측 해시를 이력에 남깁니다. 이 경로도 단어 시각만 제공하므로 내부 음절·`+`·`-` 정확도는 청취 검토가 필요합니다. 모델이 커졌다는 이유만으로 기존 Large보다 정확하다고 판정하지 않습니다.

**Run Boy Run 실제 시험에서는 무거운 조합의 미배치가 78개로 기존 Large의 6개보다 많았습니다.** 원본 음표는 보존했지만 배치 결과가 나빠져 영어 자동 기본값은 Large를 유지합니다. 새 조합은 비교용 선택으로 제공하며 [실험 결과와 한계](docs/heavy-model-experiment.md#run-boy-run-실제-gpu-비교)를 확인하세요.

- 모델 파일이 없으면 선택한 모델의 최초 분석 중 다운로드합니다. 선택한 모델·실제 모델 ID·입력·가중치 해시와 설정을 작업 이력에 기록해 다른 모델의 관측 결과와 혼용하지 않습니다.
- WAV는 SoundFile로 읽고 모델 입력만 16 kHz 모노로 변환합니다. TXT 원문과 반복을 보존하며 UTF-8·UTF-16 BOM·CP949를 읽습니다. 원본 파일은 변경하지 않습니다.
- 단일 보컬 트랙의 실제 참조 음표, 가변 템포·그룹 오프셋을 처리합니다. 여러 보컬 트랙에서 대상이 모호하거나 같은 그룹을 여러 번 참조하거나 참조 범위가 음표를 잘라 내는 구조는 안내 후 중단합니다.
- 새 GUI 결과는 모든 곡에 대해 `outputs/<작업 ID>/<원본 SVP 이름>_LYRICS_FILLED.svp`와 비교 CSV 두 개·보고서입니다. Counting Stars 기존 자료를 사용해도 음표는 고정하고 가사 대응만 적용하며 같은 이름 규칙을 사용합니다.

새 분석은 별도 작업 프로세스에서 실행합니다. **취소 요청** 뒤 실제 프로세스가 종료될 때까지 기다린 후 취소 상태로 전환합니다. 번역·수동 음표 편집·보컬 합성은 제공하지 않습니다. 모델별 환경·캐시·설치 및 검증 상태는 [Python 환경](docs/python-environment.md#큰-모델과-모델-선택-환경)과 [모델 선택 확장 기록](docs/gradio-gui-implementation.md#큰-모델과-gui-모델-선택)을 참고합니다.

## 기존 Counting Stars 분석 자료로 결과 재생성

```powershell
.\.venv\Scripts\python.exe .\work\counting_stars\run.py --output .\outputs\counting_stars_rerun
```

이 진입점은 **기존 타이밍 조정 CLI**입니다. `onset`·`duration`·`lyrics`를 수정할 수 있는 기존 Counting Stars 계약과 `_TIMING_FIXED.svp` 결과 이름을 유지하며, 현재 GUI의 가사 전용 처리와 구분합니다. 기존 `work/acoustic`의 JSON과 `work/pitch`의 CSV를 사용하며 외부 패키지를 통한 모델 추론을 다시 수행하지 않습니다. 같은 이름의 결과가 있으면 중단하며, 원본 SVP·TXT·WAV와 기존 결과를 보존합니다.

기본 원본 폴더는 `E:/동영상_편집/AI_커버/OneRepublic - Counting Stars 힝구`입니다. 다른 위치에 같은 원본 파일이 있다면 `--source "원본 폴더"`를 지정합니다. 이 기존 CLI는 파일명, 원본 해시, 715개 음표 및 120 BPM 등을 고정 검증합니다. 다른 곡은 GUI의 업로드 분석을 사용합니다. 원본 오디오 연결 경로도 접근 가능해야 합니다.

## 기존 음성 재분석 스크립트

아래는 기존 Counting Stars 분석 스크립트에 대한 설명입니다. GUI의 일반 곡 분석은 `svp_alignment/audio/`를 사용하며 이 스크립트나 특정 Whisper 캐시에 의존하지 않습니다.

`work/acoustic`과 `work/pitch`의 직접 의존성은 `numpy`, `scipy`, `soundfile`, `torch`, `torchaudio`, `transformers`, `praat-parselmouth`입니다. `requirements.txt`에는 이 패키지와 설치된 하위 의존성이 포함됩니다.

Whisper 코드는 `cuda:0`, FP16 및 사용자 홈의 특정 `whisper-large-v3` 모델 캐시 경로를 사용합니다. `MODEL`은 `C:/Users/jaewo/.../snapshots/06f233fe06e710322aca913c1bc4249a0d71fce1` 절대 경로로 고정돼 있으므로 다른 PC에서는 두 Whisper 스크립트의 해당 경로를 조정해야 합니다. `local_files_only=True`이므로 패키지 설치와 별도로 모델 파일이 준비돼 있어야 합니다. CTC 코드는 emissions 캐시가 없으면 모델 다운로드와 GPU 추론을 수행합니다. 재분석 스크립트는 `work/`의 분석 자료를 갱신할 수 있습니다.

## GUI 구현 범위와 문서

로컬 Gradio GUI와 모델을 선택하는 새 음성 분석을 구현했으며, GUI의 변경 범위를 가사만으로 제한합니다. [GUI 계획](docs/gradio-gui-plan.md)과 [구현·검증 기록](docs/gradio-gui-implementation.md)에 현재 계약과 정책 변경 전 검증 이력을 구분해 기록했습니다. 실제 브라우저 화면 자동 검증은 URL 확인이 불가능하다는 도구의 안전 검사로 중단됐으며, 화면 확인은 미검증 상태로 남겨 두었습니다.

Run Boy Run에서 확인한 `la` 잔존·단어 미배치·`+` 연결 위험에 대응해 연속 음표 구간 기반 배치, 원문·최종 기호 연결 검증, 초안 교정과 품질 분류를 구현했습니다. `COMPLETED`는 기술적 저장 상태이며 부분 초안·자동 배치 완료 후보·가창 미검증을 별도로 표시합니다. 근거·정책·검증과 남은 한계는 [가사 배치 개선 분석 및 구현 기록](docs/lyrics-placement-improvement-plan.md)을 참고합니다.

## 폴더

| 경로 | 용도 |
| --- | --- |
| `.venv/` | 프로젝트 전용 Python과 설치 패키지 |
| `app.py` | 로컬 Gradio 실행 진입점 |
| `svp_alignment/` | 공용 정렬·검증·작업 상태·GUI 코드 |
| `tests/` | 작업 수명·UI 콜백·기존 CLI 회귀 검사 |
| `work/uploads/` | 드래그·선택한 입력 파일의 프로젝트 내부 보관본 |
| `work/models/` | 음성 정렬 모델 캐시와 작업 간 잠금 |
| `work/gradio/` | 작업별 상태·새 음성 분석·초안·미리듣기 자료 |
| `work/counting_stars/` | 기존 CLI와 import 호환 진입점 |
| `work/acoustic/` | CTC/Whisper 분석 코드와 관측 자료 |
| `work/pitch/` | 파형·피치 분석 코드와 관측 자료 |
| `outputs/` | 전달용 SVP와 검증 보고서 |
| `docs/` | 작업 명세와 환경 기록 |

[프로젝트 지침](AGENTS.md) · [Counting Stars 작업 명세](docs/counting-stars-vocal-alignment.md) · [설치 검증 기록](docs/python-environment.md)
