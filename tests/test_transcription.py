import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_transcription import TranscriptionManager, normalize_segments, stamp


class TranscriptionTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.media = self.root / 'media'
        self.media.mkdir()
        self.manager = TranscriptionManager(self.root / 'state', lambda: self.media)
        self.manager.stop()
        self.source = self.media / 'audio.wav'
        self.source.write_bytes(b'audio')
        os.utime(self.source, (time.time()-120, time.time()-120))

    def tearDown(self):
        self.manager.stop()
        self.folder.cleanup()

    def test_refuse_outside_symlinks_and_recording_files(self):
        outside = self.root / 'outside.wav'
        outside.write_bytes(b'audio')
        link = self.media / 'link.wav'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.manager.validate(str(link))
        self.manager.active_paths = lambda: [str(self.media / 'audio.wav')]
        with self.assertRaisesRegex(ValueError, '仍在录制'):
            self.manager.validate(str(self.source))

    def test_refuse_newly_modified_file(self):
        os.utime(self.source, None)
        with self.assertRaisesRegex(ValueError, '60'):
            self.manager.validate(str(self.source))

    def test_duplicate_cancel_retry_and_source_version(self):
        with patch.object(self.manager, 'executable', return_value='/bin/whisper'), patch.object(self.manager, 'status', return_value={'model_ready': True}):
            job = self.manager.start(str(self.source))
            self.assertEqual(job['id'], self.manager.start(str(self.source))['id'])
            self.assertEqual(len(self.manager.jobs), 1)
            self.assertEqual(self.manager.cancel(job['id'])['state'], 'cancelled')
            self.assertEqual(self.manager.start(str(self.source))['state'], 'queued')
            os.utime(self.source, (time.time()-180, time.time()-180))
            self.assertNotEqual(job['id'], self.manager.start(str(self.source))['id'])

    def test_offsets_and_export_timestamps_cross_hour(self):
        data = {'transcription': [{'offsets': {'from': 1250, 'to': 5000}, 'text': ' 你好 '}]}
        segments = normalize_segments(data, 3599, 3)
        self.assertEqual(segments, [{'start': 3600.25, 'end': 3602, 'text': '你好'}])
        self.assertEqual(stamp(segments[0]['start']), '01:00:00,250')

    def test_archive_search_survives_video_deletion_and_restart(self):
        source = self.media / '直播_2026-10-22_20-00-00.wav'
        self.source.rename(source)
        with patch.object(self.manager, 'executable', return_value='/bin/whisper'), patch.object(self.manager, 'status', return_value={'model_ready': True}):
            job = self.manager.start(str(source), creator='好女孩')
        self.manager.jobs[0]['state'] = 'success'
        self.manager._save()
        result = {'text':'今天聊计算机', 'srt':'字幕', 'segments':[{'start':2, 'end':4, 'text':'今天聊计算机'}]}
        (self.manager.root / (job['id'] + '.json')).write_text(json.dumps(result))
        source.unlink()
        restarted = TranscriptionManager(self.manager.root, lambda:self.media)
        try:
            found = restarted.search('好女孩', '2026-10-22', '计算机')['jobs']
            self.assertEqual(len(found), 1)
            self.assertFalse(found[0]['source_exists'])
            self.assertEqual(found[0]['matches'][0]['start'], 2)
            self.assertEqual(restarted.result(job['id']), result)
            self.assertEqual(restarted.search(date='2026-10-21')['jobs'], [])
        finally:
            restarted.stop()

    def test_upload_gate_requires_durable_result(self):
        self.manager.closed.clear()
        self.manager.jobs = [{'id':'b'*24, 'state':'failed', 'error':'识别失败'}]
        with patch.object(self.manager, 'start', return_value={'id':'b'*24}):
            with self.assertRaisesRegex(RuntimeError, '转写未完成'):
                self.manager.archive_before_upload([self.source], '主播', lambda:False)
            self.manager.jobs[0]['state'] = 'success'
            with self.assertRaises(OSError):
                self.manager.archive_before_upload([self.source], '主播', lambda:False)
            (self.manager.root / ('b'*24+'.json')).write_text('{}')
            self.manager.archive_before_upload([self.source], '主播', lambda:False)

    def test_restart_recovers_as_retryable_not_fake_success(self):
        self.manager.path.write_text(json.dumps([{'id':'a'*24, 'state':'running'}]))
        restarted = TranscriptionManager(self.manager.root, lambda: self.media)
        try:
            self.assertEqual(restarted.jobs[0]['state'], 'failed')
            with self.assertRaises(ValueError):
                restarted.result('../secret')
        finally:
            restarted.stop()

    def test_cancel_running_process_reaps_it(self):
        import sys
        self.manager.closed.clear()
        job = {'id':'test'}
        import threading
        timer = threading.Timer(.2, lambda: self.manager.cancelled.add('test'))
        timer.start()
        started = time.monotonic()
        with self.assertRaises(InterruptedError):
            self.manager._command(job, [sys.executable, '-c', 'import time; time.sleep(60)'])
        timer.join()
        self.assertLess(time.monotonic()-started, 5)
