"""Upload selection races without filesystem, Gradio, or model dependencies."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
import unittest

from svp_alignment.jobs.input_selection import INPUT_KINDS, InputSelectionRegistry


class InputSelectionTests(unittest.TestCase):
    def setUp(self):
        self.registry = InputSelectionRegistry()
        self.session = 'browser-session'
        self.sources = ('cache/original.svp', 'cache/lyrics.txt', 'cache/vocals.wav')
        self.stored = ('work/uploads/svp/original.svp', 'work/uploads/txt/lyrics.txt',
                       'work/uploads/wav/vocals.wav')

    def ready(self):
        tokens = []
        for kind, source, stored in zip(INPUT_KINDS, self.sources, self.stored):
            token = self.registry.begin(self.session, kind, source)
            self.assertTrue(self.registry.bind(self.session, kind, token, stored))
            tokens.append(token)
        return tokens

    def test_three_independent_uploads_complete_in_parallel(self):
        barrier = Barrier(3)
        def upload(kind, source, stored):
            token = self.registry.begin(self.session, kind, source)
            barrier.wait(timeout=5)
            return self.registry.bind(self.session, kind, token, stored)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(upload, *values)
                       for values in zip(INPUT_KINDS, self.sources, self.stored)]
            self.assertEqual([True, True, True], [future.result(timeout=5) for future in futures])
        self.assertEqual(self.stored, self.registry.resolve(self.session, self.sources))

    def test_late_save_cannot_replace_a_newer_selection(self):
        old_started, finish_old = Event(), Event()
        def old_upload():
            token = self.registry.begin(self.session, 'svp', self.sources[0])
            old_started.set()
            if not finish_old.wait(timeout=5):
                raise TimeoutError('replacement was not released')
            return self.registry.bind(self.session, 'svp', token, self.stored[0])
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(old_upload)
            self.assertTrue(old_started.wait(timeout=5))
            token = self.registry.begin(self.session, 'svp', 'cache/replacement.svp')
            self.assertTrue(self.registry.bind(self.session, 'svp', token, 'work/uploads/new.svp'))
            finish_old.set()
            self.assertFalse(future.result(timeout=5))
        for kind, source, stored in zip(INPUT_KINDS[1:], self.sources[1:], self.stored[1:]):
            token = self.registry.begin(self.session, kind, source)
            self.registry.bind(self.session, kind, token, stored)
        self.assertEqual(('work/uploads/new.svp', *self.stored[1:]),
                         self.registry.resolve(self.session, ('cache/replacement.svp', *self.sources[1:])))
        with self.assertRaisesRegex(ValueError, '선택이 변경'):
            self.registry.resolve(self.session, self.sources)

    def test_clear_blocks_late_bind_and_preserves_other_inputs(self):
        tokens = self.ready()
        self.registry.clear(self.session, 'txt')
        self.assertFalse(self.registry.bind(self.session, 'txt', tokens[1], 'late.txt'))
        with self.assertRaisesRegex(ValueError, 'TXT 파일을 업로드'):
            self.registry.resolve(self.session, self.sources)
        new_token = self.registry.begin(self.session, 'txt', self.sources[1])
        self.assertNotEqual(tokens[1], new_token)
        self.assertFalse(self.registry.bind(self.session, 'txt', tokens[1], self.stored[1]))
        self.assertTrue(self.registry.bind(self.session, 'txt', new_token, self.stored[1]))
        self.assertEqual(self.stored, self.registry.resolve(self.session, self.sources))

    def test_reset_invalidates_every_token_even_when_sources_are_reselected(self):
        tokens = self.ready()
        self.registry.reset(self.session)
        for kind, source, old_token, stored in zip(INPUT_KINDS, self.sources, tokens, self.stored):
            new_token = self.registry.begin(self.session, kind, source)
            self.assertNotEqual(old_token, new_token)
            self.assertFalse(self.registry.bind(self.session, kind, old_token, stored))
            self.assertTrue(self.registry.bind(self.session, kind, new_token, stored))
        self.assertEqual(self.stored, self.registry.resolve(self.session, self.sources))

    def test_pending_missing_and_unregistered_values_are_not_inspectable(self):
        with self.assertRaisesRegex(ValueError, 'SVP 파일을 업로드'):
            self.registry.resolve(self.session, self.sources)
        token = self.registry.begin(self.session, 'svp', self.sources[0])
        with self.assertRaisesRegex(ValueError, '저장하고 있습니다'):
            self.registry.resolve(self.session, self.sources)
        self.registry.bind(self.session, 'svp', token, self.stored[0])
        with self.assertRaisesRegex(ValueError, 'TXT 파일을 업로드'):
            self.registry.resolve(self.session, self.sources)
        self.ready()
        with self.assertRaisesRegex(ValueError, 'WAV 파일을 업로드'):
            self.registry.resolve(self.session, (*self.sources[:2], None))

    def test_empty_begin_detaches_a_previous_file(self):
        self.ready()
        token = self.registry.begin(self.session, 'wav', '   ')
        self.assertFalse(self.registry.bind(self.session, 'wav', token, self.stored[2]))
        with self.assertRaisesRegex(ValueError, 'WAV 파일을 업로드'):
            self.registry.resolve(self.session, self.sources)

    def test_tokens_cannot_cross_sessions_or_kinds(self):
        tokens = self.ready()
        self.assertFalse(self.registry.bind('other-browser', 'svp', tokens[0], self.stored[0]))
        self.assertFalse(self.registry.bind(self.session, 'txt', tokens[0], self.stored[1]))
        self.registry.clear('other-browser', 'svp')
        self.registry.reset('other-browser')
        self.assertEqual(self.stored, self.registry.resolve(self.session, self.sources))

    def test_binding_is_immutable_and_normalizes_path_values(self):
        token = self.registry.begin(self.session, 'svp', '  cache/original.svp  ')
        self.assertTrue(self.registry.bind(self.session, 'svp', token, '  work/uploads/original.svp  '))
        self.assertTrue(self.registry.bind(self.session, 'svp', token, 'work/uploads/original.svp'))
        self.assertFalse(self.registry.bind(self.session, 'svp', token, 'work/uploads/changed.svp'))
        for kind, source, stored in zip(INPUT_KINDS[1:], self.sources[1:], self.stored[1:]):
            token = self.registry.begin(self.session, kind, Path(source))
            self.registry.bind(self.session, kind, token, Path(stored))
        actual = self.registry.resolve(self.session, (' cache/original.svp ', *map(Path, self.sources[1:])))
        self.assertEqual('work/uploads/original.svp', actual[0])
        self.assertEqual(tuple(str(Path(value)) for value in self.stored[1:]), actual[1:])

    def test_invalid_contract_arguments_fail_descriptively(self):
        for kind in ('audio', '', None, []):
            for operation in (
                lambda: self.registry.begin(self.session, kind, self.sources[0]),
                lambda: self.registry.bind(self.session, kind, 'token', self.stored[0]),
                lambda: self.registry.clear(self.session, kind),
            ):
                with self.assertRaisesRegex(ValueError, '입력 종류'):
                    operation()
        for sources in (None, self.sources[:2], (*self.sources, 'extra'), 'abc'):
            with self.assertRaisesRegex(ValueError, '세 개 지정'):
                self.registry.resolve(self.session, sources)
        for session in (None, '', '   ', 123):
            for operation in (
                lambda: self.registry.begin(session, 'svp', self.sources[0]),
                lambda: self.registry.bind(session, 'svp', 'token', self.stored[0]),
                lambda: self.registry.resolve(session, self.sources),
                lambda: self.registry.clear(session, 'svp'),
                lambda: self.registry.reset(session),
            ):
                with self.assertRaisesRegex(ValueError, '브라우저 세션'):
                    operation()
        token = self.registry.begin(self.session, 'svp', self.sources[0])
        with self.assertRaisesRegex(ValueError, '저장 경로'):
            self.registry.bind(self.session, 'svp', token, None)


if __name__ == '__main__':
    unittest.main()
