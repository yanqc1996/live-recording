import unittest
import tempfile
from pathlib import Path

from desktop_media_library import RecentRecordingCache, group_recordings, scan_recordings


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
