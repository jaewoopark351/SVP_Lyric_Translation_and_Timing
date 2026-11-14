"""Adapt browser events to the server-owned job lifecycle."""

from __future__ import annotations

from hashlib import sha256
import json

import gradio as gr

from ..audio.model_catalog import DEFAULT_MODEL_CHOICE, saved_model_choice
from .presentation import (
    LYRIC_COLUMNS, NOTE_COLUMNS, REVIEW_STATES, filtered_lyrics, filtered_notes,
    fenced, input_text, lyrics_only, report_text, review_text, preview_interval,
    correction_syllable_number, current_placement_policy, selected_model, status_text, table_data,
)

OUTPUT_COUNT = 19


def input_signature(svp, txt, wav, language="auto", model_choice=DEFAULT_MODEL_CHOICE) -> str:
    values = [str(value or "").strip() for value in (svp, txt, wav)]
    values.append(language)
    values.append(model_choice)
    return sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def make_callbacks(manager, resolve_inputs=None, reset_inputs=None) -> dict:
    """The manager owns all mutable session/job state; closures only format events."""

    def session_id(request):
        identity = getattr(request, "session_hash", None)
        if not identity:
            raise ValueError("브라우저 세션을 확인할 수 없습니다. 화면을 새로고침하세요.")
        return identity

    def skipped():
        return tuple(gr.skip() for _ in range(OUTPUT_COUNT))

    def render(snapshot, signature, unknown_only=False, large_only=False, threshold=100, restore_paths=False, quality_filter="all"):
        state = snapshot.get("status")
        reviewed = state in REVIEW_STATES
        # A recovered job owns its saved inputs. Never return original external
        # paths through File outputs, which would expose/cache the full inputs.
        path_values = (None,) * 3 if restore_paths else (gr.skip(),) * 3
        return (
            snapshot.get("job_id"), signature, snapshot.get("job_id", ""), status_text(snapshot),
            input_text(snapshot), review_text(snapshot),
            table_data(filtered_notes(snapshot, unknown_only, large_only, threshold, quality_filter) if reviewed else []),
            table_data(filtered_lyrics(snapshot, unknown_only, quality_filter) if reviewed else [], LYRIC_COLUMNS),
            report_text(snapshot) if reviewed else "",
            snapshot.get("files", []) if state == "COMPLETED" else None,
            gr.update(interactive=state == "READY" and lyrics_only(snapshot) and selected_model(snapshot) and current_placement_policy(snapshot)),
            gr.update(interactive=state == "REVIEW_READY" and lyrics_only(snapshot) and selected_model(snapshot) and current_placement_policy(snapshot)),
            gr.update(interactive=state in {"READY", "RUNNING", "CANCEL_REQUESTED"}),
            None,
            *path_values,
            snapshot.get("input_summary", {}).get("language", "auto") if restore_paths else gr.skip(),
            saved_model_choice(snapshot.get("input_summary", {}), snapshot.get("summary", {}).get("provenance")) if restore_paths else gr.skip(),
        )

    def clear(message="입력이 변경됐습니다. 입력 검사를 다시 실행하세요."):
        return (None, None, "", message, "입력 검사 대기", "결과 생성 대기",
                table_data([]), table_data([], LYRIC_COLUMNS), "", None,
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False), None, gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip())

    def error(message):
        return clear("**작업을 진행하지 못했습니다.**\n\n" + fenced(message))

    def current(identity, revision, job_id):
        return manager.session_revision(identity) == revision and manager.current_session_job(identity) == job_id

    def checked_job(job_id, signature, svp, txt, wav, request, language="auto", model_choice=DEFAULT_MODEL_CHOICE):
        identity = session_id(request)
        if not job_id or signature != input_signature(svp, txt, wav, language, model_choice):
            raise ValueError("현재 입력의 검사가 필요합니다. 입력 검사를 다시 실행하세요.")
        if manager.current_session_job(identity) != job_id:
            raise ValueError("현재 세션과 작업이 연결되지 않았습니다. 입력 검사 또는 작업 불러오기를 실행하세요.")
        return identity, manager.session_revision(identity)

    def invalidate(request: gr.Request):
        manager.invalidate_session(session_id(request))
        return clear()

    def inspect_inputs(svp, txt, wav, unknown_only, large_only, threshold, request: gr.Request,
                       language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        identity = session_id(request)
        manager.invalidate_session(identity)
        revision = manager.session_revision(identity)
        try:
            paths = resolve_inputs(svp, txt, wav, request) if resolve_inputs is not None else (svp, txt, wav)
            snapshot = manager.inspect(*paths, language=language, model_choice=model_choice)
            if not manager.bind_session(identity, snapshot["job_id"], expected_revision=revision):
                return skipped()
            return render(snapshot, input_signature(svp, txt, wav, language, model_choice), unknown_only, large_only, threshold, quality_filter=quality_filter)
        except Exception as exc:
            return error(str(exc)) if manager.session_revision(identity) == revision else skipped()

    def run(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
            request: gr.Request, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all", progress=gr.Progress()):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
        except ValueError as exc:
            return error(str(exc))
        try:
            snapshot = manager.run(job_id, progress=lambda label, fraction: progress(fraction, desc=label))
            return render(snapshot, signature, unknown_only, large_only, threshold, quality_filter=quality_filter) if current(identity, revision, job_id) else skipped()
        except Exception as exc:
            return error(str(exc)) if current(identity, revision, job_id) else skipped()

    def cancel(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
               request: gr.Request, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            snapshot = manager.cancel(job_id)
            return render(snapshot, signature, unknown_only, large_only, threshold, quality_filter=quality_filter) if current(identity, revision, job_id) else skipped()
        except Exception as exc:
            return error(str(exc))

    def export(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
               request: gr.Request, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
        except ValueError as exc:
            return error(str(exc))
        try:
            snapshot = manager.export(job_id)
            return render(snapshot, signature, unknown_only, large_only, threshold, quality_filter=quality_filter) if current(identity, revision, job_id) else skipped()
        except Exception as exc:
            return error(str(exc)) if current(identity, revision, job_id) else skipped()

    def recover(saved_job_id, unknown_only, large_only, threshold, request: gr.Request, quality_filter="all"):
        identity = session_id(request)
        manager.invalidate_session(identity)
        revision = manager.session_revision(identity)
        if reset_inputs is not None:
            reset_inputs(identity)
        try:
            snapshot = manager.recover(str(saved_job_id or "").strip())
            if not manager.bind_session(identity, snapshot["job_id"], expected_revision=revision):
                return skipped()
            choice = saved_model_choice(snapshot.get("input_summary", {}), snapshot.get("summary", {}).get("provenance"))
            signature = input_signature(None, None, None, snapshot.get("input_summary", {}).get("language", "auto"), choice)
            return render(snapshot, signature, unknown_only, large_only, threshold, restore_paths=True, quality_filter=quality_filter)
        except Exception as exc:
            return error(str(exc)) if manager.session_revision(identity) == revision else skipped()

    def filter_rows(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
                    request: gr.Request, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        if not job_id:
            return table_data([]), table_data([], LYRIC_COLUMNS)
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            snapshot = manager.snapshot(job_id)
            if not current(identity, revision, job_id):
                return gr.skip(), gr.skip()
            return (table_data(filtered_notes(snapshot, unknown_only, large_only, threshold, quality_filter)),
                    table_data(filtered_lyrics(snapshot, unknown_only, quality_filter), LYRIC_COLUMNS))
        except ValueError as exc:
            gr.Warning(str(exc))
            return table_data([]), table_data([], LYRIC_COLUMNS)

    def preview(job_id, signature, svp, txt, wav, start, end, request: gr.Request,
                language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            clip = manager.preview(job_id, start, end)
            return (clip, "원본 보컬의 선택 구간입니다. 합성 결과가 아닙니다.") if current(identity, revision, job_id) else (gr.skip(), gr.skip())
        except Exception as exc:
            return None, "재생 구간을 만들지 못했습니다. " + fenced(exc)

    def select_note(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
                    request: gr.Request, event: gr.SelectData, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            snapshot = manager.snapshot(job_id)
            rows = filtered_notes(snapshot, unknown_only, large_only, threshold, quality_filter)
            interval = preview_interval(rows[event.index[0]], snapshot)
            return interval if current(identity, revision, job_id) else (gr.skip(), gr.skip())
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            gr.Warning(str(exc))
            return gr.skip(), gr.skip()

    def select_lyric(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
                     request: gr.Request, event: gr.SelectData, language="auto", model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            snapshot = manager.snapshot(job_id)
            row = filtered_lyrics(snapshot, unknown_only, quality_filter)[event.index[0]]
            if str(row.get("unknown_start_s", "")).strip():
                interval = preview_interval(row, snapshot)
            else:
                linked = {int(number.strip()) for number in str(row.get("note_numbers", "")).split("/") if number.strip()}
                notes = [note for note in snapshot["comparison_rows"] if int(note["note"]) in linked]
                interval = preview_interval({"old_start_s": min(float(note["old_start_s"]) for note in notes),
                                             "old_end_s": max(float(note["old_end_s"]) for note in notes)}, snapshot)
            return interval if current(identity, revision, job_id) else (gr.skip(), gr.skip())
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            gr.Warning(str(exc))
            return gr.skip(), gr.skip()

    def select_correction(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
                          request: gr.Request, event: gr.SelectData, language="auto",
                          model_choice=DEFAULT_MODEL_CHOICE, quality_filter="all"):
        """Bind a displayed note to an immutable draft revision before editing."""
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            snapshot = manager.snapshot(job_id)
            if (snapshot.get("status") != "REVIEW_READY"
                    or not snapshot.get("summary", {}).get("quality_known")
                    or not current_placement_policy(snapshot)):
                raise ValueError("이 작업은 가사를 교정할 수 없습니다. 새 작업의 저장 전 초안에서 선택하세요.")
            index = event.index[0]
            rows = filtered_notes(snapshot, unknown_only, large_only, threshold, quality_filter)
            if not isinstance(index, int) or index < 0 or index >= len(rows):
                raise ValueError("음표 행을 다시 선택하세요.")
            row = rows[index]
            token = {"job_id": job_id, "signature": signature, "session_revision": revision,
                     "draft_revision": snapshot["summary"]["draft_revision"],
                     "note_number": int(row["note"]), "note_id": row.get("note_id", "")}
            choices = []
            for word_index, word in enumerate(snapshot.get("lyric_rows", [])):
                actual_index = int(word.get("word_index", word_index))
                choices.append((f"{actual_index + 1}. {word.get('txt_word', '')} · {word.get('txt_line', '?')}행", actual_index))
            word_index = row.get("word_index")
            word_index = int(word_index) if word_index is not None and str(word_index).strip() else None
            if not current(identity, revision, job_id):
                return (gr.skip(),) * 8
            description = (f"**음표 {token['note_number']}** · 현재 가사: {row.get('new_lyrics', '')} "
                           f"· {row.get('txt_word', '미대응')}\n\n"
                           "원본 보컬을 듣고 원문 단어와 연결을 선택하세요. 음표의 시간·길이·음높이는 유지됩니다.")
            return (token, description, gr.update(choices=choices, value=word_index),
                    "CONFIRM", correction_syllable_number(row, snapshot), token["note_number"], False,
                    "교정 내용을 선택한 뒤 적용하세요.")
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            if "identity" in locals() and not current(identity, revision, job_id):
                return (gr.skip(),) * 8
            return (None, "음표 표에서 저장 전 초안의 행을 선택하세요.", gr.update(choices=[], value=None),
                    "CONFIRM", 1, None, False, fenced(exc))

    def reset_correction():
        return (None, "음표 비교 표의 행을 클릭하세요.", gr.update(choices=[], value=None),
                "CONFIRM", 1, None, False, "가사 교정 대기")

    def apply_correction(job_id, signature, svp, txt, wav, unknown_only, large_only, threshold,
                         correction, action, word_index, syllable_number, end_note_number, confirmed,
                         request: gr.Request, language="auto", model_choice=DEFAULT_MODEL_CHOICE,
                         quality_filter="all"):
        try:
            identity, revision = checked_job(job_id, signature, svp, txt, wav, request, language, model_choice)
            if (not isinstance(correction, dict) or correction.get("job_id") != job_id
                    or correction.get("signature") != signature
                    or correction.get("session_revision") != revision):
                raise ValueError("입력 또는 작업이 변경됐습니다. 음표 행을 다시 선택하세요.")
            snapshot = manager.snapshot(job_id)
            if correction.get("draft_revision") != snapshot.get("summary", {}).get("draft_revision"):
                raise ValueError("다른 교정이 적용됐습니다. 최신 음표 행을 다시 선택하세요.")
            if (snapshot.get("status") != "REVIEW_READY" or not current_placement_policy(snapshot)
                    or not snapshot.get("summary", {}).get("quality_known")):
                raise ValueError("이 작업은 가사를 교정할 수 없습니다. 새 작업의 저장 전 초안에서 선택하세요.")
            if action not in {"WORD_START", "NEXT_SYLLABLE", "SUSTAIN", "CONFIRM"}:
                raise ValueError("교정 방식을 다시 선택하세요.")
            if action == "CONFIRM" and not confirmed:
                raise ValueError("선택한 가사 대응을 확인한 뒤 확인란을 선택하세요.")
            syllable = None
            if action == "NEXT_SYLLABLE":
                syllable = int(syllable_number)
                if float(syllable_number) != syllable or syllable < 1:
                    raise ValueError("음절 번호는 1 이상의 정수여야 합니다.")
                syllable -= 1
            end_note = None
            if action == "WORD_START":
                end_note = int(end_note_number)
                if float(end_note_number) != end_note:
                    raise ValueError("범위 끝 음표 번호는 정수여야 합니다.")
            snapshot = manager.correct_lyrics(
                job_id, correction["note_number"], action,
                word_index=int(word_index) if word_index is not None else None,
                syllable_index=syllable, confirmed=bool(confirmed),
                expected_revision=correction["draft_revision"], end_note_number=end_note)
            if not current(identity, revision, job_id):
                return skipped() + (gr.skip(),) * 8
            return render(snapshot, signature, unknown_only, large_only, threshold, quality_filter=quality_filter) + (
                None, "교정을 적용했습니다. 다음 음표 행을 선택하세요.", gr.update(choices=[], value=None),
                "CONFIRM", 1, None, False, "가사와 기호 연결을 다시 검사했습니다. 저장은 아래에서 진행하세요.")
        except Exception as exc:
            if "identity" in locals() and not current(identity, revision, job_id):
                return skipped() + (gr.skip(),) * 8
            return skipped() + (gr.skip(),) * 7 + ("교정을 적용하지 못했습니다. " + fenced(exc),)

    return {"inspect": inspect_inputs, "run": run, "cancel": cancel, "export": export,
            "recover": recover, "invalidate": invalidate, "filter": filter_rows,
            "preview": preview, "select_note": select_note, "select_lyric": select_lyric,
            "select_correction": select_correction, "apply_correction": apply_correction,
            "reset_correction": reset_correction,
            "reset_view": clear, "skip_view": skipped}
