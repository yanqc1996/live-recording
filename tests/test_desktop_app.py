import unittest
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from desktop_app import AppState, make_handler
from unittest.mock import Mock
from unittest.mock import patch
from contextlib import ExitStack
from pathlib import Path


class AnchorPresenceTests(unittest.TestCase):
    def test_uploads_do_not_enable_automatic_transcription(self):
        with ExitStack() as stack:
            dependencies = ['RoomStore', 'AnchorStore', 'SettingsStore', 'UpdateManager',
                            'RecentRecordingCache', 'MediaIntegrityStore', 'RecorderProcess',
                            'GiftLedger', 'LazyDouyinInteraction', 'WorkPullManager',
                            'TranscriptionManager', 'BaiduPanUploadManager', 'RecordingTaskQueue']
            mocks = {name: stack.enter_context(patch('desktop_app.' + name)) for name in dependencies}
            stack.enter_context(patch.object(AppState, 'output_path', return_value=Path('/tmp/manual-transcription-test')))
            AppState()
            self.assertNotIn('before_upload', mocks['BaiduPanUploadManager'].call_args.kwargs)
            mocks['TranscriptionManager'].return_value.archive_before_upload.assert_not_called()

    def test_presence_checks_disabled_anchors_without_starting_recording(self):
        for running in (False, True):
            with self.subTest(running=running):
                state = AppState.__new__(AppState)
                anchor = {"id": "disabled", "enabled_recording": False}
                state.anchors = _Anchors(anchor)
                state.rooms = Mock()
                state.recorder = Mock(is_running=running)
                state.resolve_anchor = Mock(return_value=(anchor, {"is_live": True}))
                state.sync_recording_rooms = Mock()
                result = state.check_anchors_live_status()
                state.resolve_anchor.assert_called_once_with("disabled")
                self.assertTrue(result["results"][0]["ok"])
                state.recorder.observe_anchor.assert_not_called()

    def test_presence_continues_to_feed_enabled_running_recorder(self):
        state = AppState.__new__(AppState)
        anchor = {"id": "enabled", "enabled_recording": True}
        state.anchors = _Anchors(anchor)
        state.rooms = Mock()
        state.recorder = Mock(is_running=True)
        state.resolve_anchor = Mock(return_value=(anchor, {"is_live": True}))
        state.sync_recording_rooms = Mock()
        state.check_anchors_live_status()
        state.recorder.observe_anchor.assert_called_once_with(anchor)


class _Uploads:
    def __init__(self):
        self.items = []

    def load_config(self):
        return {"enabled": True, "auto_upload": True}

    def enqueue_recording(self, path, **kwargs):
        self.items.append((path, kwargs["record_name"]))


class _Settings:
    def load(self):
        return {"format": "TS", "split_enabled": False, "convert_to_mp4": False}


class _Recorder:
    def _append_log(self, _line):
        pass


class _Integrity:
    def inspect(self, _path):
        return {"status": "healthy"}


class _Anchors:
    def __init__(self, anchor):
        self.anchor = dict(anchor)

    def get(self, anchor_id):
        if self.anchor["id"] != anchor_id:
            raise IndexError("主播不存在")
        return dict(self.anchor)

    def list(self):
        return [dict(self.anchor)]

    def update(self, anchor_id, updates):
        if self.anchor["id"] != anchor_id:
            raise IndexError("主播不存在")
        self.anchor.update(updates)
        return dict(self.anchor)


class _Interaction:
    def __init__(self, result):
        self.result = result
        self.values = []

    def resolve_live_room(self, value):
        self.values.append(value)
        return dict(self.result)


class _SequencedInteraction:
    def __init__(self, *results):
        self.results = list(results)
        self.values = []

    def resolve_live_room(self, value):
        self.values.append(value)
        return dict(self.results.pop(0))


class _Tasks:
    def __init__(self, state):
        self.state = state

    def enqueue(self, kind, payload, dedupe_key=""):
        self.state._process_recording_task({"kind": kind, "payload": payload})
        return {"status": "success", "dedupe_key": dedupe_key}


class AppStateRecordingUploadTest(unittest.TestCase):
    def test_resolve_anchor_replaces_short_link_with_stable_profile_and_all_ids(self):
        state = AppState.__new__(AppState)
        state.anchors = _Anchors({
            "id": "a1", "name": "未命名主播", "profile_url": "https://v.douyin.com/abc/",
            "live_url": "", "web_rid": "", "room_id": "", "sec_user_id": "", "platform_user_id": "",
        })
        state.interaction = _Interaction({
            "is_live": True, "nickname": "主播", "profile_url": "https://www.douyin.com/user/sec-1",
            "room_url": "https://live.douyin.com/123", "web_rid": "123", "room_id": "456",
            "anchor_id": "789", "sec_anchor_id": "sec-1",
        })

        anchor, _ = state.resolve_anchor("a1")

        self.assertEqual("主播", anchor["name"])
        self.assertEqual("https://www.douyin.com/user/sec-1", anchor["profile_url"])
        self.assertEqual("https://live.douyin.com/123", anchor["live_url"])
        self.assertEqual("sec-1", anchor["sec_user_id"])
        self.assertEqual("live", anchor["last_live_status"])

    def test_live_result_without_room_identity_is_marked_incomplete(self):
        state = AppState.__new__(AppState)
        state.anchors = _Anchors({
            "id": "a1", "name": "主播", "profile_url": "https://v.douyin.com/abc/",
            "live_url": "", "web_rid": "", "room_id": "", "sec_user_id": "", "platform_user_id": "",
        })
        state.interaction = _Interaction({"is_live": True, "nickname": "主播", "room_url": "", "web_rid": ""})

        anchor, _ = state.resolve_anchor("a1")

        self.assertEqual("incomplete", anchor["last_live_status"])
        self.assertIn("未获得直播间地址", anchor["last_check_error"])

    def test_offline_refresh_does_not_replace_last_confirmed_live_room(self):
        state = AppState.__new__(AppState)
        state.anchors = _Anchors({
            "id": "a1", "name": "主播", "profile_url": "https://www.douyin.com/user/sec-1",
            "live_url": "https://live.douyin.com/930", "web_rid": "930", "room_id": "7698",
            "sec_user_id": "sec-1", "platform_user_id": "789",
        })
        state.interaction = _Interaction({
            "is_live": False, "room_url": "https://live.douyin.com/708",
            "web_rid": "708", "room_id": "offline-room", "sec_anchor_id": "sec-1",
        })

        anchor, _ = state.resolve_anchor("a1")

        self.assertEqual("offline", anchor["last_live_status"])
        self.assertEqual("https://live.douyin.com/930", anchor["live_url"])
        self.assertEqual("930", anchor["web_rid"])
        self.assertEqual("7698", anchor["room_id"])

    def test_offline_refresh_accepts_rotated_room_after_same_account_verification(self):
        state = AppState.__new__(AppState)
        state.anchors = _Anchors({
            "id": "a1", "name": "在下旺旺雪饼", "profile_url": "https://www.douyin.com/user/sec-1",
            "live_url": "https://live.douyin.com/310", "web_rid": "310", "room_id": "old-room",
            "sec_user_id": "sec-1", "platform_user_id": "789",
        })
        state.interaction = _SequencedInteraction(
            {
                "input_type": "user_profile", "is_live": False, "nickname": "小婷winko",
                "profile_url": "https://www.douyin.com/user/sec-1",
                "room_url": "https://live.douyin.com/440", "web_rid": "440",
                "sec_anchor_id": "sec-1", "anchor_id": "789",
            },
            {
                "input_type": "live_room", "is_live": False,
                "room_url": "https://live.douyin.com/440", "web_rid": "440", "room_id": "new-room",
                "sec_anchor_id": "sec-1", "anchor_id": "789",
            },
        )

        anchor, _ = state.resolve_anchor("a1")

        self.assertEqual("小婷winko", anchor["name"])
        self.assertEqual("https://live.douyin.com/440", anchor["live_url"])
        self.assertEqual("440", anchor["web_rid"])
        self.assertEqual("new-room", anchor["room_id"])
        self.assertEqual([
            "https://www.douyin.com/user/sec-1",
            "https://live.douyin.com/440",
        ], state.interaction.values)

    def test_offline_rotated_room_from_different_account_is_rejected(self):
        state = AppState.__new__(AppState)
        state.anchors = _Anchors({
            "id": "a1", "name": "主播", "profile_url": "https://www.douyin.com/user/sec-1",
            "live_url": "https://live.douyin.com/310", "web_rid": "310", "room_id": "old-room",
            "sec_user_id": "sec-1", "platform_user_id": "789",
        })
        state.interaction = _SequencedInteraction(
            {
                "input_type": "user_profile", "is_live": False,
                "room_url": "https://live.douyin.com/440", "web_rid": "440",
                "sec_anchor_id": "sec-1", "anchor_id": "789",
            },
            {
                "input_type": "live_room", "is_live": False,
                "room_url": "https://live.douyin.com/440", "web_rid": "440", "room_id": "other-room",
                "sec_anchor_id": "sec-other", "anchor_id": "999",
            },
        )

        anchor, _ = state.resolve_anchor("a1")

        self.assertEqual("https://live.douyin.com/310", anchor["live_url"])
        self.assertEqual("310", anchor["web_rid"])
        self.assertEqual("old-room", anchor["room_id"])

    def test_concurrent_recordings_keep_separate_upload_candidates(self):
        state = AppState.__new__(AppState)
        state._recording_candidates = {}
        state.uploads = _Uploads()
        state.settings = _Settings()
        state.recorder = _Recorder()
        state.integrity = _Integrity()
        state.recording_tasks = _Tasks(state)

        state._on_recorder_log("主播甲 准备开始录制视频: /tmp/a.ts")
        state._on_recorder_log("主播乙 准备开始录制视频: /tmp/b.ts")
        state._on_recorder_log("序号1 主播甲 2026-10-09 15:00:00 直播录制完成")
        state._on_recorder_log("序号2 主播乙 2026-10-09 15:01:00 直播录制完成")

        self.assertEqual([("/tmp/a.ts", "主播甲"), ("/tmp/b.ts", "主播乙")], state.uploads.items)


class AnchorStatusRouteTest(unittest.TestCase):
    def test_check_live_is_not_treated_as_anchor_id(self):
        class State:
            def check_anchors_live_status(self):
                return {"checked_at": 123, "results": []}

        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(State(), "test-token"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/anchors/check-live",
                data=b"{}",
                headers={"Content-Type": "application/json", "X-LiveRecorder-Token": "test-token"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.load(response)
            self.assertEqual(123, payload["checked_at"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
