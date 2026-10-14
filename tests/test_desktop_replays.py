import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from desktop_work_pull import WorkPullManager


class ReplayCandidateTest(unittest.TestCase):
    def test_only_explicit_live_replays_are_returned(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = WorkPullManager(Path(directory) / "state.json", Path(directory))
            manager._session = MagicMock(return_value=object())
            manager._resolve_sec_user_id = MagicMock(return_value="sec-id")
            manager._post_page = MagicMock(return_value={"has_more": 0, "aweme_list": [
                {"aweme_id": "normal", "create_time": 1000, "desc": "普通作品", "video": {"bit_rate": [{"bit_rate": 1, "play_addr": {"url_list": ["https://example.com/normal.mp4"]}}]}},
                {"aweme_id": "replay", "create_time": 1100, "desc": "昨晚直播回放", "video": {"bit_rate": [{"bit_rate": 1, "play_addr": {"url_list": ["https://example.com/replay.mp4"]}}]}},
            ]})

            result = manager.find_replay_candidates("profile", 900, 1200)

            self.assertEqual(["replay"], [item["id"] for item in result])


if __name__ == "__main__": unittest.main()
