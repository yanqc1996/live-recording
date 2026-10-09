import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_work_pull import WorkPullManager


class WorkPullAnonymousAccessTest(unittest.TestCase):
    @patch("desktop_work_pull.threading.Thread")
    def test_pull_can_start_without_douyin_login(self, thread):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = WorkPullManager(root / "state.json", root / "downloads")

            status = manager.start("https://www.douyin.com/user/example")

            self.assertTrue(status["running"])
            self.assertEqual("anonymous", status["access_mode"])
            self.assertIn("匿名", status["message"])
            thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
