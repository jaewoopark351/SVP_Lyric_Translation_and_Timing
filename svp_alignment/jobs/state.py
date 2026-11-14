"""Server-owned state for one local alignment job."""

from dataclasses import dataclass, field
from threading import Event, RLock
from typing import Any


STATUSES = frozenset({
    'CREATED', 'VALIDATING', 'READY', 'RUNNING', 'REVIEW_READY', 'EXPORTING',
    'COMPLETED', 'FAILED', 'CANCEL_REQUESTED', 'CANCELLED',
})


@dataclass
class JobState:
    job_id: str
    status: str = 'CREATED'
    stage: str = '작업 생성'
    progress: float = 0.0
    error: str = ''
    input_summary: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    artifact_hashes: dict = field(default_factory=dict)
    draft_revision: int = 0
    review_context_hash: str = ''
    prepared: Any = field(default=None, repr=False)
    comparison_rows: list = field(default_factory=list, repr=False)
    lyric_rows: list = field(default_factory=list, repr=False)
    report: str = field(default='', repr=False)
    cancel_event: Event = field(default_factory=Event, repr=False)
    lock: Any = field(default_factory=RLock, repr=False)

    def manifest(self):
        """Persist only small JSON data; runtime resources stay on the server."""
        return {
            'schema': 1,
            'job_id': self.job_id,
            'status': self.status,
            'stage': self.stage,
            'progress': self.progress,
            'error': self.error,
            'input_summary': self.input_summary,
            'summary': self.summary,
            'artifact_hashes': self.artifact_hashes,
            'draft_revision': self.draft_revision,
            'review_context_hash': self.review_context_hash,
        }

    @classmethod
    def from_manifest(cls, manifest):
        if manifest.get('schema') != 1 or manifest.get('status') not in STATUSES:
            raise ValueError('지원하지 않는 작업 기록입니다.')
        for key in ('input_summary', 'summary', 'artifact_hashes'):
            if not isinstance(manifest.get(key), dict):
                raise ValueError('손상된 작업 기록입니다.')
        revision = manifest.get('draft_revision', 0)
        context_hash = manifest.get('review_context_hash', '')
        if (not isinstance(revision, int) or isinstance(revision, bool)
                or not 0 <= revision <= 1_000_000
                or not isinstance(context_hash, str)
                or (context_hash and (len(context_hash) != 64
                                      or any(c not in '0123456789abcdef' for c in context_hash)))):
            raise ValueError('손상된 초안 수정 기록입니다.')
        return cls(draft_revision=revision, review_context_hash=context_hash,
                   **{name: manifest[name] for name in (
            'job_id', 'status', 'stage', 'progress', 'error', 'input_summary',
            'summary', 'artifact_hashes',
        )})
