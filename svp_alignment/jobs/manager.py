"""Coordinate local jobs without storing runtime resources in Gradio state."""

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from svp_alignment.profiles.counting_stars import ROOT

from .artifacts import ArtifactStore
from .processing import inspect_job_inputs, prepare_job
from .preview import create_clip
from .sessions import SessionRegistry
from .state import JobState
from svp_alignment.audio.model_catalog import MODEL_CHOICES, saved_model_choice
from svp_alignment.alignment.general_matching import PLACEMENT_POLICY
from svp_alignment.verification.placement_quality import summarize_quality


REVIEW_STATUSES = frozenset({'REVIEW_READY', 'EXPORTING', 'COMPLETED'})
ACTIVE_STATUSES = frozenset({'VALIDATING', 'RUNNING', 'EXPORTING', 'CANCEL_REQUESTED'})


class JobManager:
    """Own identity, stage policy, cancellation, recovery and session binding."""

    def __init__(self, root=ROOT):
        self.store = ArtifactStore(root)
        self._jobs = {}
        self.sessions = SessionRegistry()
        self._lock = RLock()

    def _job(self, job_id):
        self.store.validate_id(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError('먼저 작업 ID로 작업을 복원하세요.')
        return job

    def _input_path(self, value):
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError('SVP, TXT, WAV 경로를 모두 지정하세요.')
        path = Path(str(value).strip()).expanduser()
        if not path.is_absolute():
            path = self.store.root / path
        return path.resolve(strict=True)

    def _save(self, job, status=None, stage=None, progress=None, error=None):
        with job.lock:
            if status is not None:
                job.status = status
            if stage is not None:
                job.stage = stage
            if progress is not None:
                job.progress = max(0.0, min(float(progress), 1.0))
            if error is not None:
                job.error = str(error)
            self.store.save_manifest(job)

    @staticmethod
    def _cancelled(job):
        if job.cancel_event.is_set():
            raise InterruptedError('작업이 취소됐습니다. 완료 결과는 공개되지 않습니다.')

    def _failure(self, job, error):
        cancelled = isinstance(error, InterruptedError) or job.cancel_event.is_set()
        self._save(job, status='CANCELLED' if cancelled else 'FAILED',
                   stage='취소 완료' if cancelled else '작업 실패', error=str(error))

    def _progress(self, job, callback):
        def update(label, fraction):
            self._cancelled(job)
            self._save(job, stage=label, progress=fraction)
            if callback is not None:
                callback(label, fraction)
            self._cancelled(job)
        return update

    @staticmethod
    def _same_inputs(bound, current, check_operation=True):
        if check_operation and bound.get('operation') != current.get('operation'):
            raise ValueError('이전 타이밍 수정 작업입니다. 파일을 다시 업로드하고 입력 검사를 실행하세요.')
        if check_operation and any(bound.get(key) != current.get(key)
                                   for key in ('model_choice', 'model_id')):
            raise ValueError('AI 모델 선택 또는 해석된 모델이 변경됐습니다. 입력을 다시 검사하세요.')
        if (check_operation and bound.get('mode') == 'general'
                and bound.get('placement_policy') != current.get('placement_policy')):
            raise ValueError('가사 배치 정책이 변경됐습니다. 파일을 다시 올리고 입력을 새로 검사하세요.')
        keys = ('paths', 'input_hashes', 'evidence_hashes', 'group_id')
        if (any(bound.get(key) != current.get(key) for key in keys)
                or bound.get('mode', 'counting_stars') != current.get('mode', 'counting_stars')
                or bound.get('language', 'auto') != current.get('language', 'auto')):
            raise ValueError('입력 또는 기존 분석 자료가 검사 이후 변경됐습니다. 다시 검사하세요.')

    def _revalidate(self, job, allow_legacy=False):
        paths = job.input_summary.get('paths')
        if not isinstance(paths, list) or len(paths) != 3:
            raise ValueError('원본 입력 기록이 없습니다. 다시 검사하세요.')
        current = inspect_job_inputs(tuple(Path(path) for path in paths),
                                     language=job.input_summary.get('language', 'auto'),
                                     model_choice=saved_model_choice(
                                         job.input_summary, job.summary.get('provenance')))
        self._same_inputs(job.input_summary, current, check_operation=not allow_legacy)
        return current

    @staticmethod
    def _require_lyrics_only(job):
        if job.input_summary.get('operation') != 'lyrics_only':
            raise ValueError('이전 타이밍 수정 작업입니다. 파일을 다시 업로드하고 입력 검사를 실행하세요.')
        if 'model_choice' not in job.input_summary:
            raise ValueError('모델 선택이 기록되지 않은 이전 작업입니다. 모델을 선택하고 입력을 다시 검사하세요.')
        if (job.input_summary.get('mode') == 'general'
                and job.input_summary.get('placement_policy') != PLACEMENT_POLICY):
            raise ValueError('이전 가사 배치 정책의 미완료 작업입니다. 입력을 새로 검사하세요.')

    @staticmethod
    def _review_summary(job, prepared, rows, lyrics):
        return {
            'note_count': len(rows), 'word_count': len(lyrics),
            'unknown_notes': sum(row['assignment'] == 'UNKNOWN' for row in rows),
            'unknown_words': sum(row['status'] == 'UNKNOWN' for row in lyrics),
            'unplaced_words': sum(not row['note_numbers'] for row in lyrics),
            'parse': 'PASS', 'preservation': 'PASS', 'operation': 'lyrics_only',
            'lyrics_only_preservation': 'PASS', 'timing': 'UNCHANGED',
            'model_choice': job.input_summary['model_choice'],
            'model_id': job.input_summary['model_id'],
            'analysis': 'FRESH' if job.input_summary.get('mode') == 'general' else 'CACHED',
            'fresh_analysis': 'COMPLETED' if job.input_summary.get('mode') == 'general' else 'NOT_RUN',
            'provenance': getattr(prepared, 'provenance', {}),
            'placement_policy': job.input_summary.get('placement_policy', ''),
            'draft_revision': job.draft_revision,
            **summarize_quality(rows, lyrics),
            'listening': 'NOT_RUN', 'studio': 'NOT_RUN', 'synthesis': 'NOT_RUN',
            'overall': 'NOT_VERIFIED',
        }

    def _require_current_revision(self, job):
        persisted = JobState.from_manifest(self.store.load_manifest(job.job_id))
        if any(getattr(persisted, key) != getattr(job, key) for key in
               ('status', 'draft_revision', 'review_context_hash', 'artifact_hashes')):
            raise ValueError('다른 요청에서 초안이 변경됐습니다. 작업 ID로 최신 작업을 다시 불러오세요.')
        # Inspection may keep tuples in memory; JSON persists them as lists.
        if persisted.input_summary != json.loads(json.dumps(job.input_summary)):
            raise ValueError('입력 기록이 변경됐습니다. 작업 ID로 최신 작업을 다시 불러오세요.')

    def inspect(self, svp, txt, wav, language='auto', model_choice='auto'):
        if language not in ('auto', 'eng', 'kor', 'jpn', 'zho', 'fra', 'deu', 'spa', 'mul'):
            raise ValueError('지원하는 가사 언어를 선택하세요.')
        if model_choice not in {value for _, value in MODEL_CHOICES}:
            raise ValueError('지원하는 AI 정렬 모델을 선택하세요.')
        job = JobState(str(uuid4()))
        self.store.create(job.job_id)
        with self._lock:
            self._jobs[job.job_id] = job
        self._save(job, status='VALIDATING', stage='업로드한 프로젝트·가사·오디오 검사', progress=0.0)
        try:
            paths = tuple(self._input_path(value) for value in (svp, txt, wav))
            job.input_summary = {'paths': [str(path) for path in paths]}
            summary = inspect_job_inputs(paths, language=language, model_choice=model_choice)
            self._cancelled(job)
            with job.lock:
                self._cancelled(job)
                job.input_summary = summary
                mode_label = ('검증된 기존 분석 자료 사용' if summary['mode'] == 'counting_stars'
                              else '이 곡의 보컬 WAV를 새로 분석')
                self._save(job, status='READY', stage='입력 검사 완료 · ' + mode_label, progress=1.0)
        except Exception as error:
            self._failure(job, error)
        return self.snapshot(job.job_id)

    def run(self, job_id, progress=None):
        job = self._job(job_id)
        with job.lock:
            if job.status != 'READY':
                raise ValueError('입력 검사를 완료한 READY 작업만 실행할 수 있습니다.')
            self._require_lyrics_only(job)
            self._save(job, status='RUNNING', stage='입력 재검사', progress=0.0, error='')
        try:
            self._revalidate(job)
            self._cancelled(job)
            update = self._progress(job, progress)
            paths = tuple(Path(path) for path in job.input_summary['paths'])
            prepared = prepare_job(paths, job.input_summary, self.store.job_folder(job_id),
                                   progress=lambda label, fraction: update(label, 0.8 * fraction),
                                   cancelled=job.cancel_event.is_set)
            update('SVP 및 비교표 초안 검증', 0.90)
            rows, lyrics, report, hashes = self.store.write_draft(job, prepared)
            self._revalidate(job)
            self._cancelled(job)
            with job.lock:
                self._cancelled(job)
                job.prepared = prepared
                job.comparison_rows = rows
                job.lyric_rows = lyrics
                job.report = report
                job.artifact_hashes = hashes
                job.review_context_hash = (self.store.context_hash(job)
                                           if getattr(prepared, 'review_context', None) is not None else '')
                job.summary = self._review_summary(job, prepared, rows, lyrics)
                self._save(job, status='REVIEW_READY', stage='검토 준비 완료 · UNKNOWN 확인 필요', progress=1.0)
        except Exception as error:
            self._failure(job, error)
        return self.snapshot(job_id)

    def cancel(self, job_id):
        job = self._job(job_id)
        with job.lock:
            if job.status in ACTIVE_STATUSES:
                return self._cancel_current(job_id)
        with self.store.revision_lock(job_id), job.lock:
            self._require_current_revision(job)
            return self._cancel_current(job_id)

    def _cancel_current(self, job_id):
        job = self._job(job_id)
        with job.lock:
            if job.status in ('COMPLETED', 'FAILED', 'CANCELLED'):
                return self.snapshot(job_id)
            job.cancel_event.set()
            if job.status in ACTIVE_STATUSES:
                self._save(job, status='CANCEL_REQUESTED', stage='취소 요청 · 현재 단계 종료 대기')
            else:
                self._save(job, status='CANCELLED', stage='취소 완료')
        return self.snapshot(job_id)

    def export(self, job_id):
        job = self._job(job_id)
        with self.store.revision_lock(job_id):
            with job.lock:
                self._require_current_revision(job)
            return self._export_current(job_id)

    def _export_current(self, job_id):
        job = self._job(job_id)
        with job.lock:
            if job.status != 'REVIEW_READY':
                raise ValueError('검토 준비가 완료된 작업만 저장할 수 있습니다.')
            self._require_lyrics_only(job)
            self._save(job, status='EXPORTING', stage='결과 저장 전 입력 재검사', progress=0.0)
        try:
            self._revalidate(job)
            self._cancelled(job)
            prepared = job.prepared
            if prepared is None:
                paths = tuple(Path(path) for path in job.input_summary['paths'])
                if job.review_context_hash:
                    from svp_alignment.general_pipeline import restore_song
                    prepared = restore_song(paths, job.input_summary, self.store.read_context(job))
                else:
                    prepared = prepare_job(paths, job.input_summary, self.store.job_folder(job_id),
                                           progress=self._progress(job, None),
                                           cancelled=job.cancel_event.is_set)
            self.store.validate_bundle(job, prepared=prepared)
            self._revalidate(job)
            # Cancel owns this same lock. A request arriving after commit sees
            # COMPLETED and cannot relabel a published result as CANCELLED.
            with job.lock:
                self._cancelled(job)
                self.store.publish(job, prepared)
                job.prepared = prepared
                partial = job.summary.get('placement_complete') is False
                self._save(job, status='COMPLETED',
                           stage='부분 초안 저장 완료' if partial else '새 결과 폴더 저장 완료', progress=1.0)
        except Exception as error:
            # A manifest write failure after commit still must not pretend a
            # cancellation removed the published directory. Recovery is strict.
            self._failure(job, error)
        return self.snapshot(job_id)

    def correct_lyrics(self, job_id, note_number, action, word_index=None, syllable_index=None,
                       confirmed=False, expected_revision=None, end_note_number=None):
        """Commit a new immutable review revision, leaving prior drafts intact."""
        job = self._job(job_id)
        with self.store.revision_lock(job_id), job.lock:
            self._require_current_revision(job)
            return self._correct_current(job_id, note_number, action, word_index, syllable_index,
                                         confirmed, expected_revision, end_note_number)

    def _correct_current(self, job_id, note_number, action, word_index=None, syllable_index=None,
                         confirmed=False, expected_revision=None, end_note_number=None):
        from svp_alignment.general_pipeline import restore_song
        job = self._job(job_id)
        with job.lock:
            if job.status != 'REVIEW_READY':
                raise ValueError('저장 전 검토 중인 작업만 교정할 수 있습니다. 완료 결과는 보존됩니다.')
            self._require_lyrics_only(job)
            if (not isinstance(expected_revision, int) or isinstance(expected_revision, bool)
                    or expected_revision != job.draft_revision):
                raise ValueError('초안이 변경됐습니다. 최신 표에서 음표를 다시 선택하세요.')
            self._revalidate(job)
            self._cancelled(job)
            context = self.store.read_context(job)
            edit = dict(note_number=note_number, action=action, word_index=word_index,
                        syllable_index=syllable_index, confirmed=confirmed,
                        end_note_number=end_note_number)
            paths = tuple(Path(path) for path in job.input_summary['paths'])
            prepared = restore_song(paths, job.input_summary, context, edit=edit)
            candidate = JobState.from_manifest(deepcopy(job.manifest()))
            candidate.draft_revision += 1
            while self.store.draft_folder(candidate).exists():
                candidate.draft_revision += 1
            rows, lyrics, report, hashes = self.store.write_draft(candidate, prepared)
            candidate.artifact_hashes = hashes
            candidate.review_context_hash = self.store.context_hash(candidate)
            candidate.summary = self._review_summary(candidate, prepared, rows, lyrics)
            candidate.stage, candidate.progress, candidate.error = '가사 교정 초안 검증 완료', 1.0, ''
            self.store.validate_bundle(candidate, prepared=prepared)
            self._revalidate(job)
            self._cancelled(job)
            # The atomic manifest replacement is the revision commit. Failed
            # validation/writes leave the existing job and its draft untouched.
            self.store.save_manifest(candidate)
            for name in ('draft_revision', 'review_context_hash', 'artifact_hashes', 'summary',
                         'stage', 'progress', 'error'):
                setattr(job, name, getattr(candidate, name))
            job.prepared = prepared
            job.comparison_rows, job.lyric_rows, job.report = rows, lyrics, report
        return self.snapshot(job_id)

    def snapshot(self, job_id):
        job = self._job(job_id)
        with job.lock:
            if job.status in REVIEW_STATUSES:
                try:
                    self.store.validate_bundle(job, completed=job.status == 'COMPLETED')
                except Exception as error:
                    self._failure(job, error)
            paths = job.input_summary.get('paths', [])
            review = job.status in REVIEW_STATUSES
            snapshot = {
                **job.manifest(),
                'paths': dict(zip(('svp', 'txt', 'wav'), paths)),
                'files': ([str(self.store.result_folder(job_id) / name) for name in self.store.names(job)]
                          if job.status == 'COMPLETED' else []),
                'comparison_rows': job.comparison_rows if review else [],
                'lyric_rows': job.lyric_rows if review else [],
                'unknown_rows': ([row for row in job.comparison_rows
                                  if row['assignment'] == 'UNKNOWN'] if review else []),
                'report': job.report if review else '',
            }
            return deepcopy(snapshot)

    def recover(self, job_id):
        self.store.validate_id(job_id)
        with self._lock:
            existing = self._jobs.get(job_id)
            if existing is None:
                job = JobState.from_manifest(self.store.load_manifest(job_id))
                job.lock.acquire()
                self._jobs[job_id] = job
        if existing is not None:
            with self.store.revision_lock(job_id), existing.lock:
                persisted = JobState.from_manifest(self.store.load_manifest(job_id))
                if (existing.status in ('READY', *REVIEW_STATUSES)
                        and persisted.status in ('READY', *REVIEW_STATUSES)
                        and (persisted.draft_revision != existing.draft_revision
                             or persisted.status != existing.status)):
                    rows, lyrics, report = (self.store.read_review(
                        persisted, completed=persisted.status == 'COMPLETED')
                        if persisted.status in REVIEW_STATUSES else ([], [], ''))
                    for key in ('status', 'stage', 'progress', 'error', 'input_summary', 'summary',
                                'artifact_hashes', 'draft_revision', 'review_context_hash'):
                        setattr(existing, key, getattr(persisted, key))
                    existing.prepared = None
                    existing.comparison_rows, existing.lyric_rows, existing.report = rows, lyrics, report
            return self.snapshot(job_id)
        try:
            if job.status in ACTIVE_STATUSES or job.status == 'CREATED':
                if job.status == 'CANCEL_REQUESTED':
                    job.cancel_event.set()
                    self._save(job, status='CANCELLED', stage='서버 중단 전 취소 요청 확인',
                               error='서버가 중단되어 작업이 완료되지 않았습니다.')
                else:
                    self._save(job, status='FAILED', stage='서버 중단으로 작업 미완료',
                               error='서버 재시작 전에 중단된 작업입니다. 입력을 다시 검사하세요.')
            elif job.status in REVIEW_STATUSES:
                job.comparison_rows, job.lyric_rows, job.report = self.store.read_review(
                    job, completed=job.status == 'COMPLETED')
            elif job.status == 'READY':
                self._revalidate(job)
        except Exception as error:
            self._failure(job, error)
        finally:
            job.lock.release()
        return self.snapshot(job_id)

    def preview(self, job_id, start, end):
        job = self._job(job_id)
        with job.lock:
            if job.status not in ('READY', *REVIEW_STATUSES):
                raise ValueError('검사된 작업의 원본 WAV만 미리 들을 수 있습니다.')
            self._revalidate(job, allow_legacy=(job.input_summary.get('operation') != 'lyrics_only'
                                              or 'model_choice' not in job.input_summary
                                              or (job.input_summary.get('mode') == 'general'
                                                  and job.input_summary.get('placement_policy') != PLACEMENT_POLICY)))
            return create_clip(job.input_summary['paths'][2],
                               self.store.preview_folder(job_id),
                               start, end, float(job.input_summary['duration']))

    def session_revision(self, session_id):
        return self.sessions.revision(session_id)

    def invalidate_session(self, session_id):
        self.sessions.invalidate(session_id)

    def bind_session(self, session_id, job_id, expected_revision=None):
        self._job(job_id)
        return self.sessions.bind(session_id, job_id, expected_revision)

    def current_session_job(self, session_id):
        return self.sessions.current_job(session_id)
