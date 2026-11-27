import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop_core import RecorderProcess, RoomStore
from desktop_app import AppState
from src.recording_control import EngineControl, FileProgress, recording_cookie, stop_capture


class EngineControlTest(unittest.TestCase):
    def test_anonymous_room_ignores_logged_in_and_fallback_cookies(self):
        url = 'https://live.douyin.com/a?lr_anonymous_recording=1'
        self.assertEqual('', recording_cookie(url, 'logged-in', 'configured'))

    def test_normal_room_keeps_logged_in_cookie(self):
        self.assertEqual('logged-in', recording_cookie('https://live.douyin.com/a', 'logged-in', 'configured'))

    def test_retry_identity_matches_config_without_room_id(self):
        from src.recording_control import room_key
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'urls.ini'
            RoomStore(path).sync_from_anchors([{'id': 'a', 'name': 'creator',
                'live_url': 'https://live.douyin.com/a', 'sec_user_id': 'sec'}])
            url = path.read_text(encoding='utf-8-sig').strip().split(',')[0]
            self.assertEqual(room_key(url), room_key('https://live.douyin.com/a?lr_sec_user_id=sec'))

    def test_growth_must_be_sustained_before_resetting_failures(self):
        with tempfile.TemporaryDirectory() as folder, patch('src.recording_control.time.monotonic') as clock:
            path = Path(folder) / 'capture.ts'
            clock.return_value = 0
            progress = FileProgress(str(path))
            path.write_bytes(b'x')
            progress.stalled()
            clock.return_value = 60
            progress.stalled()
            self.assertFalse(progress.healthy)
            for now in range(61, 123):
                clock.return_value = now
                path.write_bytes(b'x' * now)
                progress.stalled()
            self.assertTrue(progress.healthy)

    def test_rotated_room_cannot_start_second_worker_for_same_creator(self):
        control = EngineControl()
        old = 'https://live.douyin.com/old?lr_sec_user_id=creator'
        new = 'https://live.douyin.com/new?lr_sec_user_id=creator'
        self.assertTrue(control.claim(old))
        self.assertFalse(control.claim(new))
        control.consume({'action': 'retry', 'url': new})
        self.assertTrue(control.event(old).is_set())
        self.assertEqual(control.current_url(old), new)
        control.release(old)
        self.assertTrue(control.claim(new))

    def test_retry_replaces_stale_radio_session_identity(self):
        control = EngineControl()
        old = ('https://live.douyin.com/radio?lr_room_id=old-session'
               '&lr_sec_user_id=stable-creator')
        new = ('https://live.douyin.com/radio?lr_room_id=current-session'
               '&lr_sec_user_id=stable-creator')
        control.consume({'action': 'retry', 'url': new})
        self.assertEqual(control.current_url(old), new)

    def test_auth_hot_update_and_logout_wake_waiters(self):
        control = EngineControl()
        event = control.event('https://live.douyin.com/a')
        control.listen(io.StringIO('invalid\n' + json.dumps({'action': 'auth', 'cookie': 'new-session'}) + '\n'))
        self.assertEqual(control.cookie, 'new-session')
        self.assertTrue(event.is_set())
        control.consume({'action': 'auth', 'cookie': ''})
        self.assertEqual(control.cookie, '')

    def test_failures_rotate_sources_and_back_off_without_touching_other_room(self):
        control = EngineControl()
        info = {'source_candidates': ['flv', 'hls', 'flv']}
        self.assertEqual(control.source('a', info), 'flv')
        control.failed('a')
        self.assertEqual(control.source('a', info), 'hls')
        self.assertEqual(control.source('b', info), 'flv')
        for _ in range(10):
            control.failed('a')
        self.assertEqual(control.retry_delay('a'), 60)
        control.healthy('a')
        self.assertEqual(control.retry_delay('a'), 2)

    def test_missing_file_and_stopped_segments_are_detected(self):
        with tempfile.TemporaryDirectory() as folder, patch('src.recording_control.time.monotonic') as clock:
            clock.return_value = 10
            progress = FileProgress(str(Path(folder) / 'capture_%03d.ts'))
            clock.return_value = 101
            self.assertTrue(progress.stalled())
            (Path(folder) / 'capture_001.ts').write_bytes(b'video')
            self.assertFalse(progress.stalled())
            clock.return_value = 192
            self.assertTrue(progress.stalled())
            (Path(folder) / 'capture_002.ts').write_bytes(b'video')
            self.assertFalse(progress.stalled())

    def test_capture_stop_finalizes_before_escalating(self):
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired('ffmpeg', 12), None]
        stop_capture(process)
        process.stdin.write.assert_called_once_with(b'q\n')
        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    def test_stuck_capture_escalates_to_kill_with_bounded_waits(self):
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired('ffmpeg', 12),
                                   subprocess.TimeoutExpired('ffmpeg', 5), None]
        stop_capture(process)
        process.kill.assert_called_once()
        self.assertEqual([call.kwargs['timeout'] for call in process.wait.call_args_list], [12, 5, 5])

    def test_h265_flv_is_not_selected_when_hls_available(self):
        control = EngineControl()
        self.assertEqual(control.source('room', {
            'flv_url': 'https://example.com/a.flv?codec=h265',
            'm3u8_url': 'https://example.com/a.m3u8'}), 'https://example.com/a.m3u8')

    def test_repeated_stream_failure_also_tries_page_provider(self):
        control = EngineControl()
        control.failed('a')
        control.failed('a')
        self.assertTrue(control.prefer_page('a'))
        self.assertFalse(control.prefer_page('b'))


class RecoveryTest(unittest.TestCase):
    def test_waiting_log_does_not_override_recent_live_evidence(self):
        recorder = self.recorder()
        recorder.resolve_anchor_id = lambda name: 'a'
        with patch('desktop_core.time.time', return_value=1000):
            recorder.observe_anchor({'id': 'a', 'name': 'creator', 'last_live_status': 'live'})
            recorder._track_room_state('creator 等待直播')
            self.assertEqual(recorder._room_states['a']['state'], 'reconnecting')
        with patch('desktop_core.time.time', return_value=1121):
            recorder._track_room_state('creator 等待直播')
            self.assertEqual(recorder._room_states['a']['state'], 'waiting')

    def test_slow_anchor_does_not_delay_completed_anchor_recovery(self):
        import threading
        state = AppState.__new__(AppState)
        release = threading.Event()
        state.anchors = MagicMock()
        state.anchors.list.return_value = [{'id': 'slow'}, {'id': 'fast'}]
        def resolve(key):
            if key == 'slow':
                if not release.wait(2):
                    raise RuntimeError('fast anchor was blocked')
            return {'id': key}, {}
        state.resolve_anchor = resolve
        state.sync_recording_rooms = MagicMock()
        state.rooms = MagicMock()
        state.recorder = MagicMock()
        state.recorder.observe_anchor.side_effect = lambda anchor: release.set() if anchor['id'] == 'fast' else None
        result = state.check_anchors_live_status(enabled_only=True)
        self.assertTrue(all(item['ok'] for item in result['results']))
        self.assertEqual(state.recorder.observe_anchor.call_args_list[0].args[0]['id'], 'fast')

    def recorder(self):
        recorder = RecorderProcess(Path('/tmp'))
        recorder.process = MagicMock()
        recorder.process.poll.return_value = None
        return recorder

    def test_hot_cookie_is_sent_to_running_engine_without_restart(self):
        recorder = self.recorder()
        recorder.set_douyin_cookie('new-session')
        command = json.loads(recorder.process.stdin.write.call_args.args[0])
        self.assertEqual(command, {'action': 'auth', 'cookie': 'new-session'})
        self.assertNotIn('new-session', '\n'.join(recorder.logs))
        recorder.process.terminate.assert_not_called()

    def test_independent_live_evidence_recovers_silent_engine_and_cooldown(self):
        recorder = self.recorder()
        anchor = {'id': 'a', 'name': 'creator', 'live_url': 'https://live.douyin.com/a',
                  'enabled_recording': True, 'last_live_status': 'live'}
        with patch('desktop_core.time.time', return_value=1000):
            recorder.observe_anchor(anchor)
        with patch('desktop_core.time.time', return_value=1121):
            recorder.observe_anchor(anchor)
            self.assertEqual(recorder._room_states['a']['state'], 'reconnecting')
            recorder.retry_anchor(anchor)
        recorder.process.stdin.write.assert_called_once()
        self.assertEqual(len(recorder._missed_incidents), 1)

    def test_retry_sends_fresh_radio_room_identity_to_running_worker(self):
        recorder = self.recorder()
        anchor = {
            'id': 'a', 'name': 'radio',
            'live_url': 'https://live.douyin.com/radio?from=profile',
            'room_id': 'current-session', 'sec_user_id': 'stable-creator',
        }
        with patch('desktop_core.time.time', return_value=1000):
            self.assertTrue(recorder.retry_anchor(anchor))
        command = json.loads(recorder.process.stdin.write.call_args.args[0])
        self.assertIn('lr_room_id=current-session', command['url'])
        self.assertIn('lr_sec_user_id=stable-creator', command['url'])
        self.assertIn('from=profile', command['url'])

    def test_force_retry_does_not_interrupt_healthy_capture(self):
        recorder = self.recorder()
        with patch('desktop_core.time.time', return_value=1000):
            recorder._transition_room('a', 'creator', 'recording', last_file_growth_at=999)
            self.assertFalse(recorder.retry_anchor({'id': 'a', 'name': 'creator'}))
        recorder.process.stdin.write.assert_not_called()

    def test_disabled_and_stopped_anchors_are_not_restarted(self):
        recorder = self.recorder()
        anchor = {'id': 'a', 'name': 'creator', 'last_live_status': 'live', 'enabled_recording': False}
        recorder.observe_anchor(anchor)
        recorder.process.poll.return_value = 0
        anchor['enabled_recording'] = True
        recorder.observe_anchor(anchor)
        self.assertEqual(recorder._room_states, {})
        recorder.process.stdin.write.assert_not_called()

    def test_force_record_falls_back_to_saved_identity_without_global_restart(self):
        state = AppState.__new__(AppState)
        anchor = {'id': 'a', 'name': 'creator', 'live_url': 'https://live.douyin.com/a'}
        state.recorder = MagicMock()
        state.storage_status = MagicMock(return_value={'level': 'healthy'})
        state.anchors = MagicMock()
        state.anchors.get.return_value = anchor
        state.anchors.update.return_value = anchor
        state.resolve_anchor = MagicMock(side_effect=RuntimeError('temporary failure'))
        state.sync_recording_rooms = MagicMock()
        result = state.force_record_anchor('a')
        self.assertTrue(result['requested'])
        state.recorder.retry_anchor.assert_called_once_with(anchor, '手动强制检查录制')
        state.recorder.stop.assert_not_called()
        state.recorder.start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
