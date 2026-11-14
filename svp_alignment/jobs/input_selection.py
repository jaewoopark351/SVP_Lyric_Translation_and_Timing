"""Server-owned upload selections; file storage remains the upload store's responsibility."""

from threading import RLock
from uuid import uuid4


INPUT_KINDS = ('svp', 'txt', 'wav')
_LABELS = {'svp': 'SVP', 'txt': 'TXT', 'wav': 'WAV'}


class InputSelectionRegistry:
    """Bind each current browser file selection to one immutable stored path.

    Tokens belong to one session and one input kind. Replacing or clearing a
    selection makes an in-flight save unable to restore the previous selection.
    Different kinds do not invalidate one another's uploads.
    """

    def __init__(self):
        self._sessions = {}
        self._lock = RLock()

    @staticmethod
    def _session(session_id):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError('브라우저 세션 정보가 필요합니다.')
        return session_id

    @staticmethod
    def _kind(kind):
        if kind not in INPUT_KINDS:
            raise ValueError('입력 종류는 svp, txt, wav 중 하나여야 합니다.')
        return kind

    @staticmethod
    def _source(value):
        return str(value or '').strip() or None

    def begin(self, session_id, kind, source):
        """Record a pending selection and return a unique token for its save."""
        session_id, kind = self._session(session_id), self._kind(kind)
        source = self._source(source)
        token = uuid4().hex
        with self._lock:
            self._sessions.setdefault(session_id, {})[kind] = {
                'token': token, 'source': source, 'stored_path': None,
            }
        return token

    def bind(self, session_id, kind, token, stored_path):
        """Finish the current selection only; stale saves have no side effects."""
        session_id, kind = self._session(session_id), self._kind(kind)
        with self._lock:
            selection = self._sessions.get(session_id, {}).get(kind)
            if selection is None or selection['token'] != token or selection['source'] is None:
                return False
            stored_path = self._source(stored_path)
            if stored_path is None:
                raise ValueError('업로드한 파일의 저장 경로가 필요합니다.')
            if selection['stored_path'] is not None:
                return selection['stored_path'] == stored_path
            selection['stored_path'] = stored_path
            return True

    def resolve(self, session_id, sources):
        """Return SVP, TXT, WAV stored paths only for three current ready files."""
        session_id = self._session(session_id)
        if isinstance(sources, (str, bytes)):
            raise ValueError('SVP, TXT, WAV 파일을 순서대로 세 개 지정해야 합니다.')
        try:
            sources = tuple(self._source(value) for value in sources)
        except TypeError as error:
            raise ValueError('SVP, TXT, WAV 파일을 순서대로 세 개 지정해야 합니다.') from error
        if len(sources) != len(INPUT_KINDS):
            raise ValueError('SVP, TXT, WAV 파일을 순서대로 세 개 지정해야 합니다.')
        with self._lock:
            selections = self._sessions.get(session_id, {})
            paths = []
            for kind, source in zip(INPUT_KINDS, sources):
                selection = selections.get(kind)
                label = _LABELS[kind]
                if source is None or selection is None or selection['source'] is None:
                    raise ValueError(f'{label} 파일을 업로드하세요.')
                if selection['source'] != source:
                    raise ValueError(f'{label} 파일 선택이 변경됐습니다. 업로드 완료 후 입력 검사를 다시 실행하세요.')
                if selection['stored_path'] is None:
                    raise ValueError(f'{label} 파일을 저장하고 있습니다. 업로드 완료 후 입력 검사를 실행하세요.')
                paths.append(selection['stored_path'])
            return tuple(paths)

    def clear(self, session_id, kind):
        """Invalidate only one input and all unfinished saves for that input."""
        session_id, kind = self._session(session_id), self._kind(kind)
        with self._lock:
            selections = self._sessions.get(session_id)
            if selections is not None:
                selections.pop(kind, None)
                if not selections:
                    self._sessions.pop(session_id, None)

    def reset(self, session_id):
        """Detach all previous selections before loading another job."""
        session_id = self._session(session_id)
        with self._lock:
            self._sessions.pop(session_id, None)
