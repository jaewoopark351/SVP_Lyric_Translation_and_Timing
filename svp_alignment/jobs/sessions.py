"""Server session revisions prevent stale callbacks rebinding old inputs."""

from threading import RLock


class SessionRegistry:
    def __init__(self):
        self._states = {}
        self._lock = RLock()

    def revision(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('브라우저 세션 정보가 필요합니다.')
        with self._lock:
            return self._states.setdefault(session_id, {'revision': 0, 'job_id': None})['revision']

    def invalidate(self, session_id):
        self.revision(session_id)
        with self._lock:
            state = self._states[session_id]
            state['revision'] += 1
            state['job_id'] = None

    def bind(self, session_id, job_id, expected_revision=None):
        self.revision(session_id)
        with self._lock:
            state = self._states[session_id]
            if expected_revision is not None and state['revision'] != expected_revision:
                return False
            state['job_id'] = job_id
            return True

    def current_job(self, session_id):
        self.revision(session_id)
        with self._lock:
            return self._states[session_id]['job_id']
