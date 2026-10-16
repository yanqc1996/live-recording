import unittest

from desktop_app import AppState


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


if __name__ == "__main__":
    unittest.main()
