"""Actual multipart upload and Gradio FileData processing without a browser/server."""

import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

os.environ['GRADIO_TEMP_DIR'] = str(Path(__file__).resolve().parents[1] / 'work' / 'gradio_cache')
os.environ['GRADIO_ANALYTICS_ENABLED'] = 'False'

from fastapi import FastAPI
import gradio as gr
from gradio.state_holder import SessionState
from starlette.testclient import TestClient

from svp_alignment.jobs.manager import JobManager
from svp_alignment.jobs.uploads import UploadStore
from svp_alignment.profiles.counting_stars import ROOT, SOURCE_HASHES, default_input_paths
from svp_alignment.ui.gradio_app import build_app
from tests.test_general_jobs import deterministic_alignment, synthetic_project


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


class GuiUploadTransportTests(unittest.TestCase):
    def test_general_song_correction_uses_real_gradio_state_and_manager_revision(self):
        base = (ROOT / 'work' / 'gui-validation').resolve()
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='review-transport-', dir=base)
        workspace = Path(temporary.name).resolve()
        self.assertTrue(workspace.is_relative_to(base))
        sources = tuple(workspace / name for name in ('별빛.svp', '별빛.txt', '별빛.wav'))
        sources[0].write_bytes(json.dumps(synthetic_project(), ensure_ascii=False).encode('utf-8') + b'\0')
        sources[1].write_text('cat dog\n', encoding='utf-8')
        with wave.open(str(sources[2]), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\0\0' * 16000 * 4)
        before = tuple(file_hash(source) for source in sources)
        manager = JobManager(root=workspace)

        async def construct():
            screen = build_app(manager=manager)
            asgi_app = gr.mount_gradio_app(
                FastAPI(), screen, path='/', ssr_mode=False, mcp_server=False,
                allowed_paths=[], footer_links=[])
            return screen, asgi_app

        screen = None
        try:
            screen, asgi_app = asyncio.run(construct())
            with TestClient(asgi_app) as client:
                with ExitStack() as streams:
                    files = [('files', (source.name, streams.enter_context(source.open('rb')),
                                        'application/octet-stream')) for source in sources]
                    response = client.post('/gradio_api/upload', files=files)
                self.assertEqual(200, response.status_code, response.text)
                payloads = [{'path': filename, 'orig_name': source.name,
                             'meta': {'_type': 'gradio.FileData'}}
                            for filename, source in zip(response.json(), sources)]
                state = SessionState(screen)
                session_id = 'general-correction-transport'
                request = gr.Request(session_hash=session_id)
                events = {event.fn.__name__: index for index, event in screen.fns.items()}

                async def event(name, values, selection=None):
                    return await screen.process_api(
                        events[name], values, state=state, request=request, session_hash=session_id,
                        event_data=gr.SelectData(None, selection) if selection is not None else None)

                for kind, payload in zip(('svp', 'txt', 'wav'), payloads):
                    client.portal.call(event, 'upload_' + kind, [payload])
                inspected = client.portal.call(event, 'inspect_inputs',
                                               [*payloads, False, False, 100, 'eng', 'auto', 'all'])
                job_id = state[screen.fns[events['inspect_inputs']].outputs[0]._id]
                self.assertTrue(job_id, inspected['data'][3])
                bound = [None, None, *payloads, False, False, 100, 'eng', 'auto', 'all']
                with patch('svp_alignment.audio.alignment.align_words', side_effect=deterministic_alignment):
                    executed = client.portal.call(event, 'run', bound)
                review = manager.snapshot(job_id)
                self.assertEqual('REVIEW_READY', review['status'], executed['data'][3])
                self.assertTrue(review['summary']['quality_known'])
                note_index, row = next((index, row) for index, row in enumerate(review['comparison_rows'])
                                       if row['placement_action'] == 'WORD_START' and not row['symbol_risk'])
                revision = review['summary']['draft_revision']
                edit_selection = client.portal.call(
                    event, 'select_correction', bound,
                    {'index': [note_index, 0], 'value': row['note']})
                selection_event = screen.fns[events['select_correction']]
                token = state[selection_event.outputs[0]._id]
                self.assertEqual(int(row['note']), token['note_number'], edit_selection['data'][-1])
                self.assertEqual(revision, token['draft_revision'])
                corrected = client.portal.call(
                    event, 'apply_correction',
                    [None, None, *payloads, False, False, 100, None, 'CONFIRM',
                     int(row['word_index']), 1, int(row['note']), True, 'eng', 'auto', 'all'])
                after = manager.snapshot(job_id)
                self.assertEqual('REVIEW_READY', after['status'], corrected['data'][-1])
                self.assertEqual(revision + 1, after['summary']['draft_revision'])
                self.assertEqual('USER_CONFIRMED', after['comparison_rows'][note_index]['review_status'])
                self.assertEqual('PASS', after['summary']['preservation'])
                self.assertTrue(all(item['old_start_s'] == item['new_start_s']
                                    and item['old_end_s'] == item['new_end_s']
                                    for item in after['comparison_rows']))
        finally:
            if screen is not None:
                screen.close(verbose=False)
            self.assertEqual(before, tuple(file_hash(source) for source in sources))
            self.assertTrue(workspace.resolve().is_relative_to(base))
            self.assertNotEqual(workspace.resolve(), base)
            temporary.cleanup()

    def test_multipart_files_pass_real_gradio_processing_and_recover_without_file_outputs(self):
        sources = tuple(default_input_paths())
        if not all(source.is_file() for source in sources):
            self.skipTest('Local verified Counting Stars inputs are unavailable')
        before = tuple(file_hash(source) for source in sources)
        self.assertEqual(SOURCE_HASHES, before)
        base = (ROOT / 'work' / 'gui-validation').resolve()
        base.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='transport-', dir=base)
        workspace = Path(temporary.name).resolve()
        self.assertTrue(workspace.is_relative_to(base))
        self.assertNotEqual(workspace, base)
        manager = JobManager(root=workspace)
        store = UploadStore(workspace)

        async def construct():
            screen = build_app(manager=manager, upload_store=store)
            # Gradio lock initialization must occur on a running loop.
            asgi_app = gr.mount_gradio_app(
                FastAPI(), screen, path='/', ssr_mode=False, mcp_server=False,
                allowed_paths=[], footer_links=[])
            return screen, asgi_app

        screen = None
        try:
            # Mounting supplies normal request configuration and ASGI lifespan.
            # TestClient dispatches in-process: no port is opened.
            screen, asgi_app = asyncio.run(construct())
            with TestClient(asgi_app) as client:
                with ExitStack() as streams:
                    files = [('files', (source.name, streams.enter_context(source.open('rb')),
                                        'application/octet-stream')) for source in sources]
                    response = client.post('/gradio_api/upload', files=files)
                self.assertEqual(200, response.status_code, response.text)
                uploaded = response.json()
                self.assertEqual(3, len(uploaded))
                cache_root = (ROOT / 'work' / 'gradio_cache').resolve()
                payloads = []
                for source, cache_path, expected in zip(sources, uploaded, SOURCE_HASHES):
                    self.assertTrue(Path(cache_path).resolve().is_relative_to(cache_root))
                    self.assertEqual(source.name, Path(cache_path).name)
                    self.assertEqual(expected, file_hash(cache_path))
                    payloads.append({'path': cache_path, 'orig_name': source.name,
                                     'meta': {'_type': 'gradio.FileData'}})
                state = SessionState(screen)
                session_id = 'multipart-transport-session'
                request = gr.Request(session_hash=session_id)
                events = {event.fn.__name__: index for index, event in screen.fns.items()}

                async def event(name, values, selection=None):
                    return await screen.process_api(
                        events[name], values, state=state, request=request,
                        session_hash=session_id,
                        event_data=gr.SelectData(None, selection) if selection is not None else None)

                for kind, payload in zip(('svp', 'txt', 'wav'), payloads):
                    result = client.portal.call(event, 'upload_' + kind, [payload])
                    self.assertIn('파일 보관 완료', result['data'][3])
                    # A successful upload does not send originals back as File
                    # outputs or replace another component's current selection.
                    self.assertEqual([gr.skip()] * 3, result['data'][14:17])
                self.assertEqual(3, len(list((workspace / 'work' / 'uploads').glob('*/manifest.json'))))
                inspected = client.portal.call(event, 'inspect_inputs',
                                               [*payloads, False, False, 100, 'auto', 'cached_counting_stars', 'all'])
                inspect_event = screen.fns[events['inspect_inputs']]
                job_id = state[inspect_event.outputs[0]._id]
                self.assertTrue(job_id, inspected['data'][3])
                snapshot = manager.snapshot(job_id)
                self.assertEqual('READY', snapshot['status'])
                self.assertEqual('lyrics_only', snapshot['input_summary']['operation'])
                self.assertEqual('cached_counting_stars', snapshot['input_summary']['model_choice'])
                self.assertEqual(715, snapshot['input_summary']['note_count'])
                self.assertEqual(job_id, manager.current_session_job(session_id))
                self.assertEqual([gr.skip()] * 3, inspected['data'][14:17])
                saved = snapshot['input_summary']['paths']
                for kind, filename, source, expected in zip(('svp', 'txt', 'wav'), saved, sources, SOURCE_HASHES):
                    self.assertTrue(store.managed(filename, kind))
                    self.assertTrue(Path(filename).resolve().is_relative_to(workspace / 'work' / 'uploads'))
                    self.assertNotEqual(Path(filename).resolve(), source.resolve())
                    self.assertEqual(source.name, Path(filename).name)
                    self.assertEqual(expected, file_hash(filename))
                recovered = client.portal.call(event, 'recover', [job_id, False, False, 100, 'all'])
                self.assertEqual([None, None, None], recovered['data'][14:17])
                self.assertEqual('READY', manager.snapshot(job_id)['status'])
                self.assertEqual(job_id, manager.current_session_job(session_id))
                self.assertIsNone(recovered['data'][9])
                self.assertEqual('cached_counting_stars', recovered['data'][18])
                changed = client.portal.call(
                    event, 'run', [None, None, None, None, None, False, False, 100, 'auto',
                                   'WAV2VEC2_ASR_LARGE_LV60K_960H', 'all'])
                self.assertIn('입력 검사', changed['data'][3])
                self.assertEqual('READY', manager.snapshot(job_id)['status'])
                recovered = client.portal.call(event, 'recover', [job_id, False, False, 100, 'all'])
                executed = client.portal.call(
                    event, 'run', [None, None, None, None, None, False, False, 100, 'auto', 'cached_counting_stars', 'all'])
                self.assertEqual('REVIEW_READY', manager.snapshot(job_id)['status'], executed['data'][3])
                review = manager.snapshot(job_id)
                self.assertEqual('lyrics_only', review['input_summary']['operation'])
                self.assertTrue(all(row['old_start_s'] == row['new_start_s']
                                    and row['old_end_s'] == row['new_end_s']
                                    for row in review['comparison_rows']))
                self.assertIn('원본 음표 시간 고정', executed['data'][5])
                selected = client.portal.call(
                    event, 'select_note',
                    [None, None, None, None, None, False, False, 100, 'auto', 'cached_counting_stars', 'all'],
                    {'index': [0, 0], 'value': 1})
                start, end = selected['data']
                self.assertIsInstance(start, (int, float))
                self.assertGreater(end, start)
        finally:
            if screen is not None:
                screen.close(verbose=False)
            self.assertEqual(before, tuple(file_hash(source) for source in sources))
            # Only this verified, newly created temporary tree is removed.
            self.assertTrue(workspace.resolve().is_relative_to(base))
            self.assertNotEqual(workspace.resolve(), base)
            temporary.cleanup()


if __name__ == '__main__':
    unittest.main()
