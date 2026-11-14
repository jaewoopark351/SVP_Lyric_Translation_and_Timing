"""Start the project's local Gradio interface."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="SVP 가사·타이밍 보정 로컬 Gradio GUI")
    parser.add_argument("--port", type=int, default=28670, help="로컬 포트 (기본값: 28670)")
    parser.add_argument("--no-browser", action="store_true", help="브라우저 자동 열기 생략")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port는 1부터 65535 사이여야 합니다.")
    # Configure caches before importing Gradio; external environment values never broaden file access.
    cache = (PROJECT_ROOT / "work" / "gradio_cache").resolve()
    if not cache.is_relative_to(PROJECT_ROOT.resolve()):
        parser.error("Gradio 캐시가 프로젝트 내부 경로가 아닙니다.")
    os.environ["GRADIO_TEMP_DIR"] = str(cache)
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    from svp_alignment.ui.gradio_app import build_app

    app = build_app()
    app.launch(server_name="127.0.0.1", server_port=args.port, share=False,
               inbrowser=not args.no_browser, allowed_paths=[], show_error=False,
               strict_cors=True)


if __name__ == "__main__":
    main()
