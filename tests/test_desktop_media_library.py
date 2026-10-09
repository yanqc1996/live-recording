import unittest

from desktop_media_library import group_recordings


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


if __name__ == "__main__":
    unittest.main()
