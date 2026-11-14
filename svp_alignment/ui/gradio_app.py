"""Build the local uploaded-song alignment and review screen."""

from __future__ import annotations

import gradio as gr

from ..audio.model_catalog import DEFAULT_MODEL_CHOICE, MODEL_CHOICES
from ..jobs.manager import JobManager
from ..jobs.input_selection import InputSelectionRegistry
from ..jobs.uploads import UploadStore
from ..profiles.counting_stars import ROOT
from .callbacks import make_callbacks
from .presentation import LYRIC_COLUMNS, NOTE_COLUMNS, QUALITY_FILTERS, table_data
from .upload_callbacks import make_upload_callbacks, resolve_uploaded_inputs


def build_app(manager=None, upload_store=None) -> gr.Blocks:
    """Return a screen without starting a server, allowing direct integration checks."""
    manager = manager if manager is not None else JobManager(root=ROOT)
    upload_store = upload_store if upload_store is not None else UploadStore(root=manager.store.root)
    selections = InputSelectionRegistry()
    callbacks = make_callbacks(
        manager,
        resolve_inputs=lambda svp, txt, wav, request: resolve_uploaded_inputs(
            upload_store, selections, svp, txt, wav, request),
        reset_inputs=selections.reset,
    )
    upload_callbacks = make_upload_callbacks(
        manager, upload_store, selections, callbacks["reset_view"], callbacks["skip_view"])

    with gr.Blocks(title="SVP 기존 음표에 가사 넣기", analytics_enabled=False) as app:
        job_state = gr.State(None)
        signature_state = gr.State(None)
        correction_state = gr.State(None)
        gr.Markdown("# SVP 기존 음표에 가사 넣기\n음표는 그대로 유지하고 가사만 입력")
        gr.Markdown(
            "원본 SVP·TXT·보컬 WAV를 아래에 드래그하거나 클릭해서 선택하세요. "
            "업로드한 파일은 프로젝트 내부에 복사해 보관하고, 결과는 별도 파일로 저장합니다. "
            "보컬 WAV의 발음 시각을 참고해 기존 음표에 가사를 대응시킵니다. "
            "음표의 시작·길이·음높이·개수·순서와 나머지 프로젝트 설정은 유지하고 가사만 변경합니다. "
            "원본 파일은 읽기 전용이며 번역·보컬 합성은 별도 작업입니다."
        )
        with gr.Accordion("1. 원본 파일과 입력 검사", open=True):
            svp = gr.File(label="원본 SVP · 드래그하거나 클릭", file_types=[".svp"],
                          file_count="single", type="filepath", elem_id="svp-upload")
            txt = gr.File(label="가사 TXT · 드래그하거나 클릭", file_types=[".txt"],
                          file_count="single", type="filepath", elem_id="txt-upload")
            wav = gr.File(label="원본 보컬 WAV · 드래그하거나 클릭", file_types=[".wav"],
                          file_count="single", type="filepath", elem_id="wav-upload")
            with gr.Row():
                language = gr.Dropdown(
                    choices=[("자동 · ASCII 가사는 영어", "auto"), ("영어", "eng"),
                             ("한국어", "kor"), ("일본어", "jpn"), ("중국어", "zho"),
                             ("프랑스어", "fra"), ("독일어", "deu"), ("스페인어", "spa"),
                             ("다국어 · 기타", "mul")],
                    value="auto", label="가사 언어", elem_id="language")
                model = gr.Dropdown(
                    choices=MODEL_CHOICES, value=DEFAULT_MODEL_CHOICE,
                    label="AI 정렬 모델", elem_id="model-choice")
            gr.Markdown(
                "자동 선택은 영어에 Wav2Vec2 Large, 직접 지정한 지원 언어에 Qwen3 강제 정렬 모델을 사용합니다. "
                "비영어 가사에서 언어가 자동·기타이면 MMS FA를 사용합니다. "
                "Qwen3 ASR 1.7B + ForcedAligner 0.6B는 별도로 선택하는 무거운 실험 모델입니다. "
                "WAV 인식문과 제공 TXT의 대응을 비교하며 가사는 TXT를 유지합니다. "
                "AI 모델은 처음 사용할 때 내려받습니다. 모델이나 언어를 바꾸면 입력 검사를 다시 실행하세요. "
                "Counting Stars 기존 관측 재사용은 새 AI 분석을 실행하지 않는 별도 선택입니다.")
            gr.Markdown(
                "파일은 프로젝트 work/uploads/에 원래 이름으로 보관됩니다. "
                "같은 이름의 파일도 덮어쓰지 않습니다. 파일 3개의 업로드가 끝나면 입력 검사를 누르세요.\n\n"
                "SVP에 연결된 오디오의 기존 경로는 유지됩니다. 연결 파일이 없으면 경고를 표시합니다. "
                "가사 대응 후보는 UNKNOWN과 함께 검토하고 실제 보컬 재생으로 확인하세요."
            )
            inspect_button = gr.Button("입력 검사", variant="primary", elem_id="inspect")
            with gr.Accordion("검사 상세: 해시·그룹·오디오·분석 자료", open=False):
                input_info = gr.Markdown("입력 검사 대기", elem_id="input-info")
        with gr.Row():
            run_button = gr.Button("기존 음표에 가사 넣기", variant="primary", interactive=False, elem_id="run")
            cancel_button = gr.Button("취소 요청", interactive=False, elem_id="cancel")
        status = gr.Markdown("입력 검사 대기", elem_id="status")
        job_display = gr.Textbox(label="현재 작업 ID · 새로고침 전에 복사하세요", interactive=False, elem_id="job-id")
        with gr.Accordion("저장된 작업 불러오기", open=False):
            saved_job_id = gr.Textbox(label="작업 ID", placeholder="이전에 복사한 작업 ID", elem_id="recover-id")
            recover_button = gr.Button("작업 불러오기", elem_id="recover")
            gr.Markdown(
                "현재 가사 배치 방식과 모델 선택이 기록된 새 작업은 보관된 입력으로 계속 검토·저장할 수 있습니다. "
                "이전 배치 방식의 작업은 다시 입력 검사하고, 기존 Counting Stars 관측 재사용 작업은 이전 결과를 검토할 수 있습니다. "
                "모델 선택 기록이 없는 이전 작업은 파일을 다시 올리고 입력 검사를 실행하세요. "
                "이전 타이밍 수정 작업은 표시를 확인하고, 가사 전용 결과가 필요하면 입력 검사를 다시 실행하세요. "
                "업로드 칸은 비워 두며 새 입력 검사를 하려면 세 파일을 다시 올리세요. "
                "서버 재시작으로 중단된 작업은 완료로 표시하지 않습니다."
            )
        gr.Markdown("## 2. 결과 검토")
        review_summary = gr.Markdown("결과 생성 대기", elem_id="review-summary")
        quality_filter = gr.Dropdown(choices=QUALITY_FILTERS, value="all", label="검토 항목", elem_id="quality-filter")
        with gr.Row():
            unknown_only = gr.Checkbox(label="UNKNOWN만 보기 · 음표와 가사 모두", value=False, elem_id="unknown-filter")
            large_only = gr.Checkbox(label="큰 오차 음표만 보기", value=False, elem_id="error-filter")
            threshold = gr.Number(value=100, minimum=0, label="큰 오차 기준 (ms, 이상)", precision=0, elem_id="error-threshold")
        gr.Markdown(
            "새 작업의 원본·결과 음표 시작과 길이는 동일합니다. "
            "큰 오차 필터는 고정된 음표와 관측 발음의 차이를 표시하며, 근거가 없는 오차는 빈칸입니다. "
            "이전 타이밍 수정 작업을 불러오면 해당 작업의 변경 전·후 값을 표시합니다.")
        with gr.Tabs():
            with gr.Tab("음표 비교"):
                notes = gr.Dataframe(value=table_data([]), headers=[label for _, label in NOTE_COLUMNS],
                                     datatype="str", type="array", interactive=False,
                                     max_height=420, label="원본·결과 가사와 음표 보존 비교 · 행을 클릭하면 재생 구간 선택",
                                     elem_id="notes-table")
            with gr.Tab("가사 검증"):
                lyrics = gr.Dataframe(value=table_data([], LYRIC_COLUMNS), headers=[label for _, label in LYRIC_COLUMNS],
                                      datatype="str", type="array", interactive=False,
                                      max_height=420, label="TXT 순서·반복·누락 · 행을 클릭하면 재생 구간 선택",
                                      elem_id="lyrics-table")
            with gr.Tab("검증 보고서"):
                report = gr.Markdown("", elem_id="report")
        with gr.Accordion("선택 음표의 가사 교정", open=True):
            correction_note = gr.Markdown("음표 비교 표의 행을 클릭하세요.", elem_id="correction-note")
            correction_word = gr.Dropdown(choices=[], label="TXT 단어 선택 · 순서와 반복 구분", elem_id="correction-word")
            correction_action = gr.Dropdown(
                choices=[("현재 배치 확인", "CONFIRM"), ("선택 단어 배치", "WORD_START"),
                         ("+ · 다음 음절", "NEXT_SYLLABLE"), ("- · 앞 음절 지속", "SUSTAIN")],
                value="CONFIRM", label="교정 방식", elem_id="correction-action")
            with gr.Row():
                correction_syllable = gr.Number(value=1, minimum=1, precision=0,
                                                label="다음 음절 번호 · 1부터", elem_id="correction-syllable")
                correction_end = gr.Number(value=None, minimum=1, precision=0,
                                           label="단어 배치 범위 끝 음표 번호", elem_id="correction-end")
            correction_confirmed = gr.Checkbox(value=False, label="선택한 가사 대응을 확인했음", elem_id="correction-confirmed")
            gr.Markdown(
                "단어 배치는 선택한 음표부터 범위 끝까지 원문 단어를 대응합니다. "
                "+는 같은 단어의 다음 음절, -는 앞 음절의 지속입니다. "
                "교정은 저장 전 초안에서 가능하며, 이미 저장한 결과를 바꾸지 않습니다.")
            correction_button = gr.Button("가사 교정·확인 적용", elem_id="apply-correction")
            correction_status = gr.Markdown("가사 교정 대기", elem_id="correction-status")
        with gr.Accordion("원본 보컬 구간 듣기", open=True):
            with gr.Row():
                clip_start = gr.Number(value=0, minimum=0, precision=3, label="보컬 WAV 시작 (초)", elem_id="clip-start")
                clip_end = gr.Number(value=5, minimum=0, precision=3, label="보컬 WAV 종료 (초)", elem_id="clip-end")
                preview_button = gr.Button("선택 구간 준비", elem_id="preview")
            audio = gr.Audio(label="원본 보컬 · 최대 30초", type="filepath", interactive=False,
                             buttons=[], elem_id="source-audio")
            preview_status = gr.Markdown("표에서 행을 클릭하거나 시작·종료 초를 입력한 뒤 선택 구간을 준비하세요.")
        gr.Markdown("## 3. 새 결과 저장")
        gr.Markdown(
            "검토한 가사 전용 작업을 프로젝트 outputs/<작업 ID>/에 "
            "<원본 이름>_LYRICS_FILLED.svp와 검증 자료로 저장합니다. 기존 파일은 덮어쓰지 않습니다.")
        gr.Markdown("미해결 항목이 남아 있어도 부분 초안으로 저장할 수 있습니다. 파일 저장은 가창 확인 완료를 뜻하지 않습니다.")
        export_button = gr.Button("새 결과 저장 · 다운로드 준비", variant="primary", interactive=False, elem_id="export")
        downloads = gr.File(label="새 SVP · 음표 비교 CSV · 가사 검증 CSV · Markdown 보고서",
                            file_count="multiple", type="filepath", interactive=False, elem_id="downloads")

        paths = [svp, txt, wav]
        filters = [unknown_only, large_only, threshold]
        bound_inputs = [job_state, signature_state, *paths, *filters, language, model, quality_filter]
        outputs = [job_state, signature_state, job_display, status, input_info, review_summary,
                   notes, lyrics, report, downloads, run_button, export_button, cancel_button,
                   audio, *paths, language, model]
        serial = dict(concurrency_id="svp-alignment", concurrency_limit=1, api_visibility="private")
        for kind, component in zip(("svp", "txt", "wav"), paths):
            component.upload(upload_callbacks[f"upload_{kind}"], inputs=component,
                             outputs=outputs, queue=False, api_visibility="private",
                             show_progress="minimal", trigger_mode="multiple")
            component.clear(upload_callbacks[f"clear_{kind}"], outputs=outputs,
                            queue=False, api_visibility="private", show_progress="hidden")
        language.input(callbacks["invalidate"], outputs=outputs, queue=False, api_visibility="private",
                       show_progress="hidden")
        model.input(callbacks["invalidate"], outputs=outputs, queue=False, api_visibility="private",
                    show_progress="hidden")
        inspect_button.click(callbacks["inspect"], inputs=[*paths, *filters, language, model, quality_filter], outputs=outputs, **serial)
        run_button.click(callbacks["run"], inputs=bound_inputs, outputs=outputs, **serial)
        cancel_button.click(callbacks["cancel"], inputs=bound_inputs, outputs=outputs,
                            queue=False, api_visibility="private", show_progress="hidden")
        export_button.click(callbacks["export"], inputs=bound_inputs, outputs=outputs, **serial)
        recover_button.click(callbacks["recover"], inputs=[saved_job_id, *filters, quality_filter], outputs=outputs, **serial)
        for component in [*filters, quality_filter]:
            component.change(callbacks["filter"], inputs=bound_inputs, outputs=[notes, lyrics],
                             queue=False, api_visibility="private", show_progress="hidden")
        notes.select(callbacks["select_note"], inputs=bound_inputs, outputs=[clip_start, clip_end],
                     queue=False, api_visibility="private", show_progress="hidden")
        correction_outputs = [correction_state, correction_note, correction_word, correction_action,
                              correction_syllable, correction_end, correction_confirmed, correction_status]
        job_state.change(callbacks["reset_correction"], outputs=correction_outputs,
                         queue=False, api_visibility="private", show_progress="hidden")
        notes.select(callbacks["select_correction"], inputs=bound_inputs, outputs=correction_outputs,
                     queue=False, api_visibility="private", show_progress="hidden")
        correction_button.click(
            callbacks["apply_correction"],
            inputs=[job_state, signature_state, *paths, *filters, correction_state, correction_action,
                    correction_word, correction_syllable, correction_end, correction_confirmed,
                    language, model, quality_filter],
            outputs=[*outputs, *correction_outputs], **serial)
        lyrics.select(callbacks["select_lyric"], inputs=bound_inputs, outputs=[clip_start, clip_end],
                      queue=False, api_visibility="private", show_progress="hidden")
        preview_button.click(callbacks["preview"], inputs=[job_state, signature_state, *paths, clip_start, clip_end, language, model],
                             outputs=[audio, preview_status], concurrency_id="svp-audio-preview",
                             concurrency_limit=2, api_visibility="private")
    app.queue(max_size=16, default_concurrency_limit=1)
    return app
