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


class AppStateRecordingUploadTest(unittest.TestCase):
    def test_concurrent_recordings_keep_separate_upload_candidates(self):
        state = AppState.__new__(AppState)
        state._recording_candidates = {}
        state.uploads = _Uploads()
        state.settings = _Settings()
        state.recorder = _Recorder()

        state._on_recorder_log("主播甲 准备开始录制视频: /tmp/a.ts")
        state._on_recorder_log("主播乙 准备开始录制视频: /tmp/b.ts")
        state._on_recorder_log("主播甲 2026-10-09 15:00:00 直播录制完成")
        state._on_recorder_log("主播乙 2026-10-09 15:01:00 直播录制完成")

        self.assertEqual([("/tmp/a.ts", "主播甲"), ("/tmp/b.ts", "主播乙")], state.uploads.items)


if __name__ == "__main__":
    unittest.main()
