import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop_core import RecorderProcess, RoomStore, SettingsStore
from desktop_anchors import AnchorStore


class AnchorStoreTest(unittest.TestCase):
    def test_unique_display_name_resolves_to_canonical_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            anchor = store.add("在下旺旺雪饼🫓", "https://www.douyin.com/user/current")

            self.assertEqual(anchor["id"], store.find_id_by_name("在下旺旺雪饼"))

    def test_optional_live_url_is_normalized_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            anchor = store.add(
                "主播",
                "https://www.douyin.com/user/example",
                "https://live.douyin.com/example?enter_from=web",
            )
            self.assertEqual("https://live.douyin.com/example", anchor["live_url"])

    def test_anchor_profile_can_be_edited_visually(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            anchor = store.add("旧名称", "https://www.douyin.com/user/old")

            updated = store.update(anchor["id"], {
                "name": " 新名称 ",
                "profile_url": "https://www.douyin.com/user/new",
                "live_url": "https://live.douyin.com/123?source=edit",
                "default_quality": "高清",
                "sec_user_id": "  SEC-123  ",
                "web_rid": " room-web ",
                "room_id": " 98765 ",
                "output_dir": " /tmp/主播 ",
                "enabled_recording": False,
            })

            self.assertEqual("新名称", updated["name"])
            self.assertEqual("https://live.douyin.com/123", updated["live_url"])
            self.assertEqual("高清", updated["default_quality"])
            self.assertEqual("SEC-123", updated["sec_user_id"])
            self.assertEqual("room-web", updated["web_rid"])
            self.assertEqual("98765", updated["room_id"])
            self.assertEqual("/tmp/主播", updated["output_dir"])
            self.assertFalse(updated["enabled_recording"])
            self.assertEqual(["旧名称", "新名称"], updated["aliases"]["names"])
            self.assertEqual(
                ["https://www.douyin.com/user/old", "https://www.douyin.com/user/new"],
                updated["aliases"]["profile_urls"],
            )

    def test_identity_lookup_and_merge_preserve_primary_uuid_and_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            primary = store.add("新名字", "https://www.douyin.com/user/new")
            primary = store.update(primary["id"], {"platform_user_id": "12345", "sec_user_id": "SEC-ONE", "live_url": "https://live.douyin.com/new"})
            duplicate = store.add("旧名字", "https://www.douyin.com/user/old")
            duplicate = store.update(duplicate["id"], {"sec_user_id": "SEC-ONE", "room_id": "ROOM-OLD"})

            self.assertEqual(primary["id"], store.find_by_identity({"sec_user_id": "SEC-ONE"})["id"])
            self.assertEqual(primary["id"], store.find_by_identity({"platform_user_id": "12345"})["id"])
            self.assertEqual(1, len(store.duplicate_groups()))
            merged = store.merge(primary["id"], [duplicate["id"]])

            self.assertEqual(primary["id"], merged["id"])
            self.assertEqual(1, len(store.list()))
            self.assertEqual("ROOM-OLD", merged["room_id"])
            self.assertEqual(["新名字", "旧名字"], merged["aliases"]["names"])

    def test_edit_rejects_duplicate_profile_url(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            first = store.add("甲", "https://www.douyin.com/user/a")
            store.add("乙", "https://www.douyin.com/user/b")

            with self.assertRaisesRegex(ValueError, "已经存在"):
                store.update(first["id"], {"profile_url": "https://www.douyin.com/user/b"})

    def test_legacy_rooms_are_imported_once(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            rooms = [{"value": "https://live.douyin.com/123,主播: 小王", "active": False}]

            self.assertEqual(1, store.import_rooms(rooms))
            self.assertEqual(0, store.import_rooms(rooms))
            anchor = store.list()[0]
            self.assertEqual("小王", anchor["name"])
            self.assertEqual("https://live.douyin.com/123", anchor["live_url"])
            self.assertFalse(anchor["enabled_recording"])

    def test_legacy_room_enabled_state_updates_matching_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            anchor = store.add("小王", "https://live.douyin.com/123")
            self.assertTrue(anchor["enabled_recording"])

            self.assertEqual(0, store.import_rooms([{"value": "https://live.douyin.com/123,主播: 小王", "active": False}]))
            self.assertFalse(store.list()[0]["enabled_recording"])

    def test_legacy_room_with_decorated_duplicate_name_is_not_imported(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AnchorStore(Path(directory) / "anchors.json")
            store.add(
                "在下旺旺雪饼🫓",
                "https://www.douyin.com/user/current",
                "https://live.douyin.com/current",
            )

            imported = store.import_rooms([{
                "value": "https://live.douyin.com/old,主播: 在下旺旺雪饼",
                "active": True,
            }])

            self.assertEqual(0, imported)
            self.assertEqual(1, len(store.list()))
            self.assertEqual("https://live.douyin.com/current", store.list()[0]["live_url"])


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

    def test_bulk_edit_recording_collection_preserves_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "URL_config.ini"
            path.write_text("## keep this\nhttps://live.douyin.com/1,主播: 甲\n#https://live.douyin.com/2,主播: 乙\n", encoding="utf-8-sig")
            store = RoomStore(path)

            rooms = store.replace_all([
                {"id": 0, "value": "https://live.douyin.com/1,主播: 新甲", "active": False},
                {"id": 1, "value": "https://live.douyin.com/2,主播: 新乙", "active": True},
            ])

            self.assertEqual([False, True], [room["active"] for room in rooms])
            content = path.read_text(encoding="utf-8-sig")
            self.assertIn("## keep this", content)
            self.assertIn("#https://live.douyin.com/1,主播: 新甲", content)
            self.assertIn("https://live.douyin.com/2,主播: 新乙", content)

    def test_sync_from_anchors_rebuilds_derived_recording_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "URL_config.ini"
            path.write_text("## keep this\nhttps://live.douyin.com/old,主播: 旧主播\n", encoding="utf-8-sig")
            store = RoomStore(path)

            rooms = store.sync_from_anchors([
                {"name": "甲", "live_url": "https://live.douyin.com/1", "enabled_recording": True},
                {"name": "乙", "profile_url": "https://live.douyin.com/2?from=x", "enabled_recording": False},
                {"name": "无直播地址", "profile_url": "https://www.douyin.com/user/x", "enabled_recording": True},
            ])

            self.assertEqual([True, False], [room["active"] for room in rooms])
            content = path.read_text(encoding="utf-8-sig")
            self.assertIn("## keep this", content)
            self.assertNotIn("旧主播", content)
            self.assertIn("https://live.douyin.com/1,主播: 甲", content)
            self.assertIn("#https://live.douyin.com/2,主播: 乙", content)

    def test_sync_from_anchors_includes_reflow_identity_for_radio_rooms(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "URL_config.ini"
            store = RoomStore(path)

            store.sync_from_anchors([{
                "name": "电台主播",
                "live_url": "https://live.douyin.com/404-room",
                "room_id": "7697135735631104768",
                "sec_user_id": "sec-radio",
                "enabled_recording": True,
            }])

            content = path.read_text(encoding="utf-8-sig")
            self.assertIn("lr_room_id=7697135735631104768", content)
            self.assertIn("lr_sec_user_id=sec-radio", content)
            self.assertIn(",主播: 电台主播", content)


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
    def test_unexpected_engine_exit_schedules_automatic_recovery(self):
        recorder = RecorderProcess(Path.cwd())
        process = MagicMock()
        process.stdout = ["engine stopped\n"]
        process.wait.return_value = 7
        recorder.process = process
        recorder._desired_running = True

        with patch("desktop_core.threading.Timer") as timer:
            recorder._read_output(process)

        timer.assert_called_once()
        self.assertEqual(1, recorder.status()["auto_recovery"]["restart_attempts"])
        self.assertEqual(7, recorder.status()["auto_recovery"]["last_exit_code"])

    def test_recording_state_uses_canonical_anchor_id(self):
        recorder = RecorderProcess(Path.cwd(), resolve_anchor_id=lambda name: "anchor-123" if name == "主播甲" else None)
        recorder._append_log("主播甲 准备开始录制视频: /tmp/主播甲_001.ts")

        states = recorder.status()["room_states"]
        self.assertNotIn("主播甲", states)
        self.assertEqual("主播甲", states["anchor-123"]["name"])
        self.assertEqual("anchor-123", states["anchor-123"]["anchor_id"])

        recorder._append_log("序号3 主播甲 2026-10-09 14:00:00 直播录制完成")
        self.assertEqual("finalizing", recorder.status()["room_states"]["anchor-123"]["state"])

    def test_sequence_prefix_does_not_leave_stale_recording_state(self):
        recorder = RecorderProcess(Path.cwd())
        recorder._append_log("吐司 准备开始录制视频: /tmp/吐司.ts")
        recorder._append_log("序号3 吐司 2026-10-13 13:02:30 直播录制完成")

        states = recorder.status()["room_states"]
        self.assertEqual(["吐司"], list(states))
        self.assertEqual("finalizing", states["吐司"]["state"])

    def test_live_without_recording_is_marked_as_suspected_miss(self):
        recorder = RecorderProcess(Path.cwd())
        recorder.missed_recording_threshold = 0
        recorder._append_log("主播甲 正在直播中")

        status = recorder.status()

        self.assertEqual("missed", status["room_states"]["主播甲"]["state"])
        self.assertEqual("主播甲", status["missed_recordings"][0]["name"])

    def test_recording_start_clears_suspected_miss(self):
        recorder = RecorderProcess(Path.cwd())
        recorder.missed_recording_threshold = 0
        recorder._append_log("主播甲 正在直播中")
        recorder.status()
        recorder._append_log("主播甲 准备开始录制视频: /tmp/a.ts")

        self.assertEqual("recording", recorder.status()["room_states"]["主播甲"]["state"])
        self.assertFalse(recorder.status()["room_states"]["主播甲"]["suspected_missed"])

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

    def test_key_log_view_filters_repetitive_engine_output(self):
        recorder = RecorderProcess(Path.cwd())
        recorder._append_log("检测直播间中...")
        recorder._append_log("主播甲 准备开始录制视频: /tmp/test.ts")
        recorder._append_log("普通调试输出")

        snapshot = recorder.log_snapshot(0, important_only=True)

        self.assertEqual(["主播甲 准备开始录制视频: /tmp/test.ts"], snapshot["lines"])
        self.assertEqual(3, snapshot["cursor"])

    def test_room_recording_state_is_derived_from_recorder_output(self):
        recorder = RecorderProcess(Path.cwd())
        recorder._append_log("主播甲 准备开始录制视频: /tmp/主播甲_001.ts")
        active = recorder.status()["room_states"]["主播甲"]
        self.assertEqual("recording", active["state"])
        self.assertEqual("/tmp/主播甲_001.ts", active["path"])

        recorder._append_log("主播甲 2026-10-09 14:00:00 直播录制完成")
        completed = recorder.status()["room_states"]["主播甲"]
        self.assertEqual("finalizing", completed["state"])
        self.assertIn("completed_at", completed)

    def test_waiting_log_moves_finished_room_back_to_waiting(self):
        recorder = RecorderProcess(Path.cwd())
        recorder._append_log("主播甲 准备开始录制视频: /tmp/主播甲.ts")
        recorder._append_log("主播甲 2026-10-09 14:00:00 直播录制完成")
        recorder._append_log("序号1 主播甲 等待直播... ")

        state = recorder.status()["room_states"]["主播甲"]
        self.assertEqual("waiting", state["state"])
        self.assertEqual("", state["path"])

    def test_stalled_recording_enters_reconnecting_and_growth_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "主播甲.ts"
            path.write_bytes(b"first")
            recorder = RecorderProcess(Path.cwd())
            recorder.recording_stale_threshold = 0
            recorder._append_log(f"主播甲 准备开始录制视频: {path}")

            self.assertEqual("recording", recorder.status()["room_states"]["主播甲"]["state"])
            self.assertEqual("reconnecting", recorder.status()["room_states"]["主播甲"]["state"])
            path.write_bytes(b"first-more-data")
            self.assertEqual("recording", recorder.status()["room_states"]["主播甲"]["state"])


if __name__ == "__main__":
    unittest.main()
