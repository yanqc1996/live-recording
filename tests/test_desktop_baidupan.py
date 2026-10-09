import json
import tempfile
import unittest
from pathlib import Path

from desktop_baidupan import BaiduPanUploadManager


class BaiduPanUploadManagerTest(unittest.TestCase):
    def test_verified_upload_can_cleanup_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "recording.mp4"
            video.write_bytes(b"video")
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([{
                "id": "item",
                "status": "success",
                "remote_verified": True,
                "delete_after_upload": True,
                "keep_local_days": 0,
                "cleanup_below_free_gb": 0,
                "save_file_path": str(video),
                "created_at": 1,
            }])

            status = manager.status()

            self.assertFalse(video.exists())
            self.assertTrue(status["queue"][0]["local_deleted"])

    def test_unverified_upload_never_deletes_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "recording.mp4"
            video.write_bytes(b"video")
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([{
                "id": "item",
                "status": "success",
                "remote_verified": False,
                "delete_after_upload": True,
                "keep_local_days": 0,
                "cleanup_below_free_gb": 0,
                "save_file_path": str(video),
                "created_at": 1,
            }])

            manager.status()

            self.assertTrue(video.exists())


if __name__ == "__main__":
    unittest.main()
