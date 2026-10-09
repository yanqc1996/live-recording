import tempfile
import unittest
from pathlib import Path

from desktop_core import RecorderProcess, RoomStore, SettingsStore
from desktop_anchors import AnchorStore


class AnchorStoreTest(unittest.TestCase):
    def test_optional_live_url_is_normalized_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            anchor = store.add(
                "主播",
                "https://www.douyin.com/user/example",
                "https://live.douyin.com/example?enter_from=web",
            )
            self.assertEqual("https://live.douyin.com/example", anchor["live_url"])


class RoomStoreTest(unittest.TestCase):
    def test_add_toggle_and_delete_preserves_other_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "URL_config.ini"
            path.write_text("# note\nhttps://example.com/live\n#https://other.test/room\n", encoding="utf-8-sig")
            store = RoomStore(path)
            self.assertEqual([True, False], [room["active"] for room in store.list()])
            store.set_active(0, False)
            store.add("https://new.test/live")
            self.assertEqual([False, False, True], [room["active"] for room in store.list()])
            store.delete(1)
            self.assertIn("# note", path.read_text(encoding="utf-8-sig"))
            self.assertNotIn("other.test", path.read_text(encoding="utf-8-sig"))


class SettingsStoreTest(unittest.TestCase):
    def test_save_keeps_cookie_and_disables_custom_script(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text(
                "[录制设置]\n原画|超清|高清|标清|流畅 = 原画\n是否录制完成后执行自定义脚本 = 是\n"
                "[Cookie]\n抖音cookie = secret-value\n",
                encoding="utf-8-sig",
            )
            store = SettingsStore(path)
            saved = store.save({"quality": "高清", "format": "MP4", "split_seconds": 60})
            content = path.read_text(encoding="utf-8-sig")
            self.assertEqual("高清", saved["quality"])
            self.assertIn("抖音cookie = secret-value", content)
            self.assertIn("是否录制完成后执行自定义脚本 = 否", content)


class RecorderProcessTest(unittest.TestCase):
    def test_douyin_session_is_kept_in_memory(self):
        recorder = RecorderProcess(Path.cwd())
        self.assertFalse(recorder.has_douyin_session)
        recorder.set_douyin_cookie("ttwid=value; LOGIN_STATUS=1")
        self.assertTrue(recorder.has_douyin_session)

    def test_log_cursor_continues_after_buffer_rolls_over(self):
        recorder = RecorderProcess(Path.cwd())
        for index in range(1205):
            recorder._append_log(f"line {index}")
        snapshot = recorder.log_snapshot(1200)
        self.assertEqual([f"line {index}" for index in range(1200, 1205)], snapshot["lines"])
        self.assertEqual(1205, snapshot["cursor"])

    def test_room_recording_state_is_derived_from_recorder_output(self):
        recorder = RecorderProcess(Path.cwd())
        recorder._append_log("主播甲 准备开始录制视频: /tmp/主播甲_001.ts")
        active = recorder.status()["room_states"]["主播甲"]
        self.assertEqual("recording", active["state"])
        self.assertEqual("/tmp/主播甲_001.ts", active["path"])

        recorder._append_log("主播甲 2026-10-09 14:00:00 直播录制完成")
        completed = recorder.status()["room_states"]["主播甲"]
        self.assertEqual("waiting", completed["state"])
        self.assertIn("completed_at", completed)


if __name__ == "__main__":
    unittest.main()
