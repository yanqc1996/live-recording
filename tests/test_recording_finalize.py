import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop_app import AppState
from desktop_tasks import RecordingTaskQueue


class FinalizationTest(unittest.TestCase):
    def test_manual_retry_only_requeues_failed_task(self):
        with tempfile.TemporaryDirectory() as folder:
            queue = RecordingTaskQueue(Path(folder) / 'tasks.json', lambda task: None)
            queue.stop()
            task = queue.enqueue('finalize_recording', {}, 'recording-a')
            with self.assertRaises(ValueError):
                queue.retry(task['id'])
            tasks = queue._load()
            tasks[0].update(status='failed', attempts=3, error='disk full')
            queue._save(tasks)
            retried = queue.retry(task['id'])
            self.assertEqual(retried['status'], 'pending')
            self.assertEqual(retried['attempts'], 0)
            self.assertEqual(len(queue._load()), 1)

    def state(self):
        state = AppState.__new__(AppState)
        state._recording_candidates = {}
        for name in ('uploads', 'settings', 'recorder', 'integrity', 'recording_tasks', '_recordings'):
            setattr(state, name, MagicMock())
        state.settings.load.return_value = {'split_enabled': True, 'format': 'TS'}
        state.uploads.load_config.return_value = {'enabled': False, 'auto_upload': False}
        state.integrity.inspect.return_value = {'status': 'healthy'}
        state._start_gift_monitor = MagicMock()
        state._stop_gift_monitor = MagicMock()
        return state

    def test_local_finalization_is_queued_without_cloud_upload(self):
        state = self.state()
        state._on_recorder_log('主播 准备开始录制视频: /tmp/a_%03d.ts')
        state._on_recorder_log('主播 2026-10-23 12:00:00 直播录制完成')
        state.recording_tasks.enqueue.assert_called_once()
        self.assertEqual(state._recording_candidates, {})

    def test_unknown_completion_never_steals_another_recording(self):
        state = self.state()
        state._on_recorder_log('甲 准备开始录制视频: /tmp/a.ts')
        state._on_recorder_log('乙 2026-10-23 12:00:00 直播录制完成')
        state.recording_tasks.enqueue.assert_not_called()
        self.assertIn('甲', state._recording_candidates)

    def test_error_and_engine_exit_finalize_remaining_batches_once(self):
        state = self.state()
        state._on_recorder_log('甲 准备开始录制视频: /tmp/a.ts')
        state._on_recorder_log('乙 准备开始录制视频: /tmp/b.ts')
        state._on_recorder_log('甲 2026-10-23 12:00:00 直播录制出错,返回码: 1')
        state._on_recorder_log('桌面控制台：录制服务已退出（代码 0）')
        state._on_recorder_log('桌面控制台：录制服务已退出（代码 0）')
        self.assertEqual(state.recording_tasks.enqueue.call_count, 2)

    @patch('desktop_app.merge_recording_group')
    def test_merge_local_batch_without_upload_and_keep_original_segments(self, merge):
        state = self.state()
        group = {'id': '/tmp/a', 'segment_count': 2, 'segments': [
            {'path': '/tmp/a_000.ts'}, {'path': '/tmp/a_001.ts'}]}
        state.recording_archive_groups = lambda: [group]
        merge.return_value = {'path': '/tmp/a_完整.ts'}
        state._merge_and_enqueue_completed_recording({'save_file_path': '/tmp/a_%03d.ts'}, {})
        merge.assert_called_once_with(group, minimum_age_seconds=0)
        state.uploads.replace_segments_with_merged.assert_not_called()
        state.uploads.enqueue_recording.assert_not_called()

    def test_same_named_batch_in_another_directory_is_not_merged(self):
        state = self.state()
        state.recording_archive_groups = lambda: [{'id': '/other/a', 'segment_count': 2, 'segments': []}]
        with self.assertRaisesRegex(RuntimeError, '未找到'):
            state._merge_and_enqueue_completed_recording({'save_file_path': '/tmp/a_%03d.ts'}, {})

    @patch('desktop_app.merge_recording_group', side_effect=RuntimeError('merge failed'))
    def test_merge_failure_is_reported_to_retry_queue(self, merge):
        state = self.state()
        state.recording_archive_groups = lambda: [{'id': '/tmp/a', 'segment_count': 2, 'segments': []}]
        with self.assertRaisesRegex(RuntimeError, 'merge failed'):
            state._merge_and_enqueue_completed_recording({'save_file_path': '/tmp/a_%03d.ts'}, {})
        state.uploads.enqueue_recording.assert_not_called()
