"""Validated draft, manifest, scoped preview, and public result persistence."""

import csv
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path

from filelock import FileLock

from svp_alignment.profiles.counting_stars import TARGET, NOTES, LYRICS, REPORT, UNPLACED
from svp_alignment.svp import read_svp, write_svp
from svp_alignment.verification.lyrics import verify_lyrics
from svp_alignment.verification.preservation import verify_svp
from svp_alignment.project import read_project
from svp_alignment.verification.lyrics_only import verify_lyrics_only
from svp_alignment.verification.reporting import (
    gui_markdown, lyric_rows, markdown, note_rows, write_csv,
)


NAMES = (TARGET, NOTES, LYRICS, REPORT)


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_bundle(prepared, folder, studio_status='검증 대기.'):
    """Write one new legacy-compatible bundle; caller owns publication."""
    folder = Path(folder)
    for name in NAMES:
        if (folder / name).exists():
            raise FileExistsError(folder / name)
    folder.mkdir(parents=True, exist_ok=True)
    write_svp(folder / TARGET, prepared.updated, prepared.suffix)
    before, after = verify_svp(
        prepared.original, prepared.suffix, folder / TARGET, prepared.duration)
    placed = verify_lyrics(after, prepared.assignments, prepared.continuations,
                           prepared.syllables, prepared.words, UNPLACED)
    if placed != 515:
        raise ValueError('Counting Stars 가사 배치 수가 기존 프로필과 다릅니다.')
    rows = note_rows(before, after, prepared.assignments, prepared.continuations,
                     prepared.syllables, prepared.evidence, prepared.unknown)
    lyrics = lyric_rows(prepared.words, prepared.syllables, prepared.assignments,
                        after, prepared.unknown, UNPLACED)
    write_csv(folder / NOTES, rows)
    write_csv(folder / LYRICS, lyrics)
    report = markdown(rows, lyrics, prepared.inputs[-1], prepared.audio, UNPLACED, studio_status)
    with (folder / REPORT).open('x', encoding='utf-8') as stream:
        stream.write(report)
    return rows, lyrics, report


class ArtifactStore:
    """Own the filesystem lifetime of one manager's job artifacts."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.work = self.root / 'work' / 'gradio'
        self.output = self.root / 'outputs'

    @staticmethod
    def validate_id(job_id):
        if not isinstance(job_id, str):
            raise ValueError('작업 ID가 필요합니다.')
        try:
            parsed = uuid.UUID(job_id)
        except (ValueError, AttributeError) as error:
            raise ValueError('올바른 작업 ID가 아닙니다.') from error
        if parsed.version != 4 or str(parsed) != job_id:
            raise ValueError('올바른 작업 ID가 아닙니다.')
        return job_id

    def _within_root(self, path):
        path = Path(path)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError('작업 경로가 프로젝트 밖을 가리킵니다.')
        if resolved != path.absolute():
            raise ValueError('작업 저장 경로에 심볼릭 링크 또는 정션을 사용할 수 없습니다.')
        return resolved

    def job_folder(self, job_id):
        self.validate_id(job_id)
        return self._within_root(self.work / job_id)

    def result_folder(self, job_id):
        self.validate_id(job_id)
        return self._within_root(self.output / job_id)

    def preview_folder(self, job_id):
        return self._within_root(self.job_folder(job_id) / 'preview')

    def draft_folder(self, job):
        revision = job.draft_revision
        if (not isinstance(revision, int) or isinstance(revision, bool)
                or not 0 <= revision <= 1_000_000):
            raise ValueError('올바른 초안 수정 번호가 아닙니다.')
        name = 'draft' if revision == 0 else f'draft-{revision:06d}'
        return self._within_root(self.job_folder(job.job_id) / name)

    def context_hash(self, job):
        path = self._within_root(self.draft_folder(job) / 'review-context.json')
        return digest_file(path) if path.is_file() else ''

    def revision_lock(self, job_id):
        return FileLock(str(self._within_root(self.job_folder(job_id) / 'review.lock')), timeout=10)

    def read_context(self, job):
        self.validate_bundle(job)
        if not job.review_context_hash:
            raise ValueError('교정 근거가 없는 이전 작업입니다. 새 입력 검사로 시작하세요.')
        path = self._within_root(self.draft_folder(job) / 'review-context.json')
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('교정 근거 파일이 없거나 너무 큽니다.')
        if digest_file(path) != job.review_context_hash:
            raise ValueError('교정 근거 파일이 변경됐습니다.')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def names(job):
        names = tuple(job.input_summary.get('artifact_names', NAMES))
        if (len(names) != 4 or len(set(names)) != 4
                or any(not isinstance(name, str) or not name or name in ('.', '..')
                       or any(char in name for char in '/\\:') or Path(name).name != name
                       for name in names)
                or tuple(Path(name).suffix.lower() for name in names) != ('.svp', '.csv', '.csv', '.md')):
            raise ValueError('결과 파일 이름 기록이 올바르지 않습니다.')
        return names

    def create(self, job_id):
        folder = self.job_folder(job_id)
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.mkdir(exist_ok=False)

    def save_manifest(self, job):
        folder = self.job_folder(job.job_id)
        encoded = json.dumps(job.manifest(), ensure_ascii=False, allow_nan=False, indent=2)
        scratch = folder / ('.manifest-' + uuid.uuid4().hex + '.json')
        try:
            with scratch.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            scratch.replace(folder / 'manifest.json')
        finally:
            scratch.unlink(missing_ok=True)

    def load_manifest(self, job_id):
        path = self.job_folder(job_id) / 'manifest.json'
        if not path.is_file() or path.is_symlink():
            raise ValueError('작업 기록을 찾을 수 없습니다.')
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('작업 기록 크기가 올바르지 않습니다.')
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('job_id') != job_id:
            raise ValueError('작업 ID와 기록이 일치하지 않습니다.')
        return manifest

    def write_draft(self, job, prepared):
        folder = self.draft_folder(job)
        folder.mkdir(exist_ok=False)
        names = self.names(job)
        lyrics_only = job.input_summary.get('operation') == 'lyrics_only'
        if lyrics_only and getattr(prepared, 'mode', None) != 'general':
            raise ValueError('가사 전용 작업에 이전 타이밍 수정 결과를 저장할 수 없습니다.')
        if getattr(prepared, 'mode', None) == 'general':
            if names != prepared.names:
                raise ValueError('작업과 계산 결과의 파일 이름이 다릅니다.')
            if lyrics_only:
                verify_lyrics_only(prepared.document, prepared.updated)
            prepared.document.write(folder / names[0], prepared.updated)
            if lyrics_only:
                verify_lyrics_only(prepared.document, read_svp(folder / names[0])[0])
            rows, lyrics, report = prepared.comparison_rows, prepared.lyric_rows, prepared.report
            write_csv(folder / names[1], rows)
            write_csv(folder / names[2], lyrics)
            with (folder / names[3]).open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(report)
            context = getattr(prepared, 'review_context', None)
            if context is not None:
                encoded = json.dumps(context, ensure_ascii=False, allow_nan=False, indent=2)
                if len(encoded.encode('utf-8')) > 16 * 1024 * 1024:
                    raise ValueError('교정 근거 자료가 너무 큽니다.')
                with (folder / 'review-context.json').open('x', encoding='utf-8', newline='\n') as stream:
                    stream.write(encoded)
        else:
            rows, lyrics, _ = write_bundle(prepared, folder)
            report = gui_markdown(rows, lyrics, prepared.inputs[-1], prepared.audio,
                                  input_summary=job.input_summary)
            (folder / REPORT).write_text(report, encoding='utf-8', newline='\n')
        hashes = {name: digest_file(folder / name) for name in names}
        return rows, lyrics, report, hashes

    def validate_bundle(self, job, completed=False, prepared=None):
        folder = (self.result_folder(job.job_id) if completed else
                  self.draft_folder(job))
        names = self.names(job)
        if set(job.artifact_hashes) != set(names):
            raise ValueError('완전한 결과 묶음 기록이 없습니다.')
        for name in names:
            path = self._within_root(folder / name)
            if not path.is_file():
                raise ValueError(f'결과 파일이 없습니다: {name}')
            if digest_file(path) != job.artifact_hashes[name]:
                raise ValueError(f'결과 파일이 변경됐습니다: {name}')
        if not completed and job.review_context_hash:
            if self.context_hash(job) != job.review_context_hash:
                raise ValueError('교정 근거 파일이 변경됐습니다.')
        project, suffix = read_svp(folder / names[0])
        if job.input_summary.get('operation') == 'lyrics_only':
            paths = job.input_summary.get('paths', [])
            hashes = job.input_summary.get('input_hashes', [])
            if len(paths) != 3 or len(hashes) != 3 or digest_file(paths[0]) != hashes[0]:
                raise ValueError('가사 전용 결과의 원본 SVP 기록 또는 해시가 다릅니다.')
            document = read_project(paths[0], uploaded=True)
            if suffix != document.suffix:
                raise ValueError('가사 전용 결과의 SVP 접미 데이터가 원본과 다릅니다.')
            verify_lyrics_only(document, project)
        if prepared is not None:
            if getattr(prepared, 'mode', None) == 'general':
                project, suffix = read_svp(folder / names[0])
                if (project, suffix) != (prepared.updated, prepared.document.suffix):
                    raise ValueError('저장된 SVP가 이 작업의 계산 결과와 다릅니다.')
                prepared.document.verify(project)
                context = getattr(prepared, 'review_context', None)
                if context is not None:
                    from svp_alignment.verification.general_lyrics import verify_placement
                    verify_placement(context['alignment']['words'], context['alignment'],
                                     prepared.document.target_notes(project=project))
            else:
                if read_svp(folder / TARGET) != (prepared.updated, prepared.suffix):
                    raise ValueError('저장된 SVP가 이 작업의 계산 결과와 다릅니다.')
                _, after = verify_svp(prepared.original, prepared.suffix,
                                      folder / TARGET, prepared.duration)
                verify_lyrics(after, prepared.assignments, prepared.continuations,
                              prepared.syllables, prepared.words, UNPLACED)
        return folder

    def read_review(self, job, completed=False):
        folder = self.validate_bundle(job, completed=completed)
        names = self.names(job)
        with (folder / names[1]).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        with (folder / names[2]).open(encoding='utf-8-sig', newline='') as stream:
            lyrics = list(csv.DictReader(stream))
        return rows, lyrics, (folder / names[3]).read_text(encoding='utf-8')

    def publish(self, job, prepared):
        """Commit an entire validated folder by same-volume rename."""
        draft = self.validate_bundle(job, prepared=prepared)
        names = self.names(job)
        target = self.result_folder(job.job_id)
        if target.exists():
            raise FileExistsError(f'기존 결과 폴더를 덮어쓰지 않습니다: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = self._within_root(target.parent / ('.publish-' + job.job_id))
        staging.mkdir(exist_ok=False)
        try:
            for name in names:
                shutil.copyfile(draft / name, staging / name)
                if digest_file(staging / name) != job.artifact_hashes[name]:
                    raise ValueError(f'결과 복사 검증에 실패했습니다: {name}')
            # os.rename on Windows refuses an existing directory. The ID is
            # unique, and manager holds the job lock across this commit boundary.
            if target.exists():
                raise FileExistsError(target)
            staging.rename(target)
        except BaseException:
            # Only the exact newly-created staging folder belongs to this call.
            if staging.exists():
                for name in names:
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
            raise
        return [str(target / name) for name in names]

