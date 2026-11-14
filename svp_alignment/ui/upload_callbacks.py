"""Connect user file selections to durable project input copies."""

from pathlib import Path

import gradio as gr

KINDS = ("svp", "txt", "wav")
LABELS = {"svp": "SVP", "txt": "TXT", "wav": "WAV"}


def browser_session(request):
    identity = getattr(request, "session_hash", None)
    if not identity:
        raise ValueError("브라우저 세션을 확인할 수 없습니다. 화면을 새로고침하세요.")
    return identity


def resolve_uploaded_inputs(store, selections, svp, txt, wav, request):
    """Only inspect copies bound to the three currently displayed selections."""
    paths = selections.resolve(browser_session(request), (svp, txt, wav))
    if not all(store.managed(path, kind) for path, kind in zip(paths, KINDS)):
        raise ValueError("보관한 입력 파일이 없거나 변경됐습니다. 파일을 다시 업로드하세요.")
    return paths


def make_upload_callbacks(manager, store, selections, reset_view, skip_view):
    """Delegate selection generations, persistence, and job state to their owners."""
    callbacks = {}
    for kind in KINDS:
        def make_upload(selected_kind):
            def upload_file(value, request: gr.Request):
                identity = browser_session(request)
                manager.invalidate_session(identity)
                revision = manager.session_revision(identity)
                token = selections.begin(identity, selected_kind, value)
                try:
                    destination = store.save(value, selected_kind)
                    if not selections.bind(identity, selected_kind, token, destination):
                        return skip_view()
                    message = (
                        f"**{LABELS[selected_kind]} 파일 보관 완료:** {Path(destination).name}\n\n"
                        "파일 3개를 모두 올린 뒤 입력 검사를 실행하세요. "
                        "교체 전 파일도 프로젝트 내부에 보관됩니다."
                    )
                except Exception as exc:
                    message = f"**{LABELS[selected_kind]} 업로드 실패**\n\n{exc}"
                if manager.session_revision(identity) != revision:
                    return skip_view()
                return reset_view(message)
            upload_file.__name__ = f"upload_{selected_kind}"
            return upload_file

        def make_clear(selected_kind):
            def clear_file(request: gr.Request):
                identity = browser_session(request)
                manager.invalidate_session(identity)
                selections.clear(identity, selected_kind)
                return reset_view(
                    f"{LABELS[selected_kind]} 선택을 해제했습니다. 파일을 다시 올리고 입력 검사를 실행하세요. "
                    "이미 보관한 파일은 유지됩니다."
                )
            clear_file.__name__ = f"clear_{selected_kind}"
            return clear_file

        callbacks[f"upload_{kind}"] = make_upload(kind)
        callbacks[f"clear_{kind}"] = make_clear(kind)
    return callbacks
