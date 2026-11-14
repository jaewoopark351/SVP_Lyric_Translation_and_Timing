"""Counting Stars command-line entry point."""

import argparse
from pathlib import Path

from svp_alignment.legacy import prepare, run
from svp_alignment.profiles.counting_stars import ROOT, SOURCE


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs")
    parser.add_argument("--studio-status", default="검증 대기.")
    parser.add_argument("--report-only", action="store_true")
    options = parser.parse_args(argv)
    run(options.source.resolve(strict=True), options.output.resolve(), options.studio_status, options.report_only)


if __name__ == "__main__":
    main()
