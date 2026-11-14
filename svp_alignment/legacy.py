"""Preserve the Counting Stars command-line artifact contract."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from svp_alignment.jobs.artifacts import write_bundle
from svp_alignment.pipeline import prepare_paths
from svp_alignment.profiles.counting_stars import ROOT, SOURCE, PROJECT, TARGET, NOTES, LYRICS, REPORT, UNPLACED
from svp_alignment.svp import read_svp
from svp_alignment.verification.preservation import verify_inputs, verify_svp
from svp_alignment.verification.reporting import lyric_rows, markdown, note_rows


def prepare(input_folder):
    """Return the original 12-field preparation tuple for legacy callers."""
    folder = Path(input_folder)
    return prepare_paths(folder / PROJECT, folder / "OneRepublic - Counting Stars.txt",
                         folder / "1_OneRepublic - Counting Stars_(Vocals).wav").as_legacy_tuple()


def run(input_folder, output, studio_status, report_only):
    """Generate the four legacy files without replacing existing results."""
    folder, output = Path(input_folder), Path(output)
    prepared = prepare_paths(folder / PROJECT, folder / "OneRepublic - Counting Stars.txt",
                             folder / "1_OneRepublic - Counting Stars_(Vocals).wav")
    destination = output / TARGET
    if report_only:
        assert read_svp(destination) == (prepared.updated, prepared.suffix)
        before, after = verify_svp(prepared.original, prepared.suffix, destination, prepared.duration)
        rows = note_rows(before, after, prepared.assignments, prepared.continuations,
                         prepared.syllables, prepared.evidence, prepared.unknown)
        lyrics = lyric_rows(prepared.words, prepared.syllables, prepared.assignments, after,
                            prepared.unknown, UNPLACED)
        report = markdown(rows, lyrics, prepared.inputs[-1], prepared.audio, UNPLACED, studio_status)
        report_path = output / REPORT
        expected = markdown(rows, lyrics, prepared.inputs[-1], prepared.audio, UNPLACED, "검증 대기.")
        assert report_path.read_text(encoding="utf-8") == expected, "Current report differs from the generated pending report"
        pending = report_path.with_suffix(".pending.md")
        with pending.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(report)
        pending.replace(report_path)
        return
    for name in (TARGET, NOTES, LYRICS, REPORT):
        if (output / name).exists():
            raise FileExistsError(output / name)
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".counting-stars-", dir=output) as temporary:
        draft = Path(temporary)
        rows, lyrics, _ = write_bundle(prepared, draft, studio_status)
        verify_inputs(prepared.inputs)
        for name in (TARGET, NOTES, LYRICS, REPORT):
            (draft / name).rename(output / name)
    print(json.dumps({"note_rows": len(rows), "lyric_rows": len(lyrics), "output": str(output)}, ensure_ascii=True))
