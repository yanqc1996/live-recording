import unittest
import tempfile
from pathlib import Path

from unittest.mock import patch

from desktop_media_library import RecentRecordingCache, group_recordings, merge_recording_group, scan_recordings


class RecordingGroupsTest(unittest.TestCase):
    def test_segments_from_one_session_are_grouped(self):
        files = [
            {"name": "主播甲_2026-10-09_10-00-00_001.mp4", "path": "/tmp/主播甲/主播甲_2026-10-09_10-00-00_001.mp4", "size": 200, "modified": 1791514800},
            {"name": "主播甲_2026-10-09_10-00-00_000.mp4", "path": "/tmp/主播甲/主播甲_2026-10-09_10-00-00_000.mp4", "size": 100, "modified": 1791513000},
        ]

        groups = group_recordings(files)

        self.assertEqual(1, len(groups))
        self.assertEqual("主播甲", groups[0]["anchor"])
        self.assertEqual(2, groups[0]["segment_count"])
        self.assertEqual(300, groups[0]["total_size"])
        self.assertEqual("MP4", groups[0]["format"])
        self.assertTrue(groups[0]["mergeable"])

    def test_completed_merge_is_part_of_original_session(self):
        files = [
            {"name": "主播甲_2026-10-09_10-00-00_000.ts", "path": "/tmp/主播甲/主播甲_2026-10-09_10-00-00_000.ts", "size": 100, "modified": 100},
            {"name": "主播甲_2026-10-09_10-00-00_001.ts", "path": "/tmp/主播甲/主播甲_2026-10-09_10-00-00_001.ts", "size": 200, "modified": 200},
            {"name": "主播甲_2026-10-09_10-00-00_完整.ts", "path": "/tmp/主播甲/主播甲_2026-10-09_10-00-00_完整.ts", "size": 300, "modified": 300},
        ]

        group = group_recordings(files)[0]

        self.assertEqual(2, group["segment_count"])
        self.assertEqual(300, group["total_size"])
        self.assertEqual("主播甲_2026-10-09_10-00-00_完整.ts", group["merged_file"]["name"])
        self.assertFalse(group["mergeable"])

    def test_merge_uses_concat_copy_and_keeps_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "主播甲_2026-10-09_10-00-00_000.ts"
            second = root / "主播甲_2026-10-09_10-00-00_001.ts"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            group = group_recordings(scan_recordings(root, limit=None))[0]

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"merged")
                return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

            with patch("desktop_media_library.subprocess.run", side_effect=fake_run) as run:
                merged = merge_recording_group(group, ffmpeg="/fake/ffmpeg", minimum_age_seconds=0)

            self.assertEqual("主播甲_2026-10-09_10-00-00_完整.ts", merged["name"])
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertIn("concat", run.call_args.args[0])
            self.assertIn("copy", run.call_args.args[0])

    def test_recent_recordings_are_cached_until_invalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.mp4"
            first.write_bytes(b"first")
            cache = RecentRecordingCache(ttl_seconds=60)

            self.assertEqual(["first.mp4"], [item["name"] for item in cache.get(root)])
            (root / "second.mp4").write_bytes(b"second")
            self.assertEqual(["first.mp4"], [item["name"] for item in cache.get(root)])

            cache.invalidate()
            self.assertEqual({"first.mp4", "second.mp4"}, {item["name"] for item in cache.get(root)})

    def test_full_recording_scan_is_not_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(105):
                (root / f"segment-{index:03d}.mp4").write_bytes(b"video")

            self.assertEqual(105, len(scan_recordings(root, limit=None)))


if __name__ == "__main__":
    unittest.main()
