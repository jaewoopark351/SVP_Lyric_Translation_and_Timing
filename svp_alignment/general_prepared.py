"""A calculated result for an uploaded song, independent of fixed song profiles."""

from dataclasses import dataclass


@dataclass
class GeneralPrepared:
    document: object
    updated: dict
    input_summary: dict
    comparison_rows: list
    lyric_rows: list
    report: str
    provenance: dict
    mode: str = "general"
    review_context: dict | None = None

    @property
    def inputs(self):
        return self.input_summary["paths"]

    @property
    def names(self):
        return tuple(self.input_summary["artifact_names"])

