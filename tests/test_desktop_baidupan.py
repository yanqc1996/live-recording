import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from desktop_baidupan import BaiduPanUploadManager


class BaiduPanUploadManagerTest(unittest.TestCase):
    def test_reconcile_enqueues_stable_untracked_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "anchor_000.ts"
            video.write_bytes(b"video")
            old = time.time() - 600
            manager = BaiduPanUploadManager(root, root)
            result = manager.reconcile_files([{
                "anchor": "主播",
                "latest_modified": old,
                "files": [{"path": str(video), "modified": old}],
            }], enqueue=True)

            self.assertEqual(result["added"], 1)
            self.assertEqual(manager._load_queue()[0]["save_file_path"], str(video))

    def test_reconcile_does_not_enqueue_active_recording_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "anchor_000.ts"
            video.write_bytes(b"video")
            manager = BaiduPanUploadManager(root, root)
            result = manager.reconcile_files([{
                "anchor": "主播",
                "latest_modified": time.time(),
                "files": [{"path": str(video), "modified": time.time()}],
            }], enqueue=True)

            self.assertEqual(result["added"], 0)
            self.assertEqual(manager._load_queue(), [])

    def test_verified_upload_cleanup_is_enabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = BaiduPanUploadManager(root, root).load_config()

            self.assertTrue(config["delete_after_upload"])
            self.assertEqual(config["keep_local_days"], 0)
            self.assertEqual(config["cleanup_below_free_gb"], 0)

    def test_concurrency_defaults_to_three_and_is_capped_at_five(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = BaiduPanUploadManager(root, root)

            self.assertEqual(manager.load_config()["max_concurrent_uploads"], 3)
            saved = manager.save_config({"max_concurrent_uploads": 20})
            self.assertEqual(saved["max_concurrent_uploads"], 5)

    def test_claims_only_configured_number_of_pending_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([
                {"id": str(index), "status": "pending", "attempts": 0, "created_at": index}
                for index in range(3)
            ])

            claimed = manager._claim_pending_items(2)

            self.assertEqual([item["id"] for item in claimed], ["0", "1"])
            queue = manager._load_queue()
            self.assertEqual([item["status"] for item in queue], ["uploading", "uploading", "pending"])
            self.assertEqual([item["attempts"] for item in queue], [1, 1, 0])

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

    def test_local_retention_starts_when_upload_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "recording.mp4"
            video.write_bytes(b"video")
            old = time.time() - 30 * 86400
            os.utime(video, (old, old))
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([{
                "id": "retained",
                "status": "success",
                "remote_verified": True,
                "delete_after_upload": True,
                "keep_local_days": 7,
                "cleanup_below_free_gb": 0,
                "save_file_path": str(video),
                "created_at": int(old),
                "updated_at": int(time.time()),
            }])

            manager.status()

            self.assertTrue(video.exists())

    def test_verified_segment_upload_cleans_each_actual_uploaded_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "recording_000.mp4"
            second = root / "recording_001.mp4"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([{
                "id": "segments",
                "status": "success",
                "remote_verified": True,
                "delete_after_upload": True,
                "keep_local_days": 0,
                "cleanup_below_free_gb": 0,
                "save_file_path": str(root / "recording.ts"),
                "uploaded_files": [str(first), str(second)],
                "created_at": 1,
            }])

            status = manager.status()

            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(status["queue"][0]["local_deleted"])

    def test_merged_upload_archives_segments_and_cleans_them_after_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "recording_000.ts"
            second = root / "recording_001.ts"
            merged = root / "recording_完整.ts"
            for path in (first, second, merged):
                path.write_bytes(b"video")
            manager = BaiduPanUploadManager(root, root)
            manager._ensure_worker = lambda: None
            manager.save_config({"enabled": True, "auto_upload": True})

            result = manager.replace_segments_with_merged(str(merged), [str(first), str(second)], "主播")
            item = result["item"]
            self.assertEqual(str(merged), item["save_file_path"])
            self.assertEqual({str(first), str(second)}, set(item["cleanup_paths"]))

            manager._finish_item(item["id"], "success", "", remote_verified=True, uploaded_files=[str(merged)])
            manager.status()

            self.assertFalse(merged.exists())
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())

    def test_reconcile_only_uploads_merged_file_and_marks_segments_archived(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "recording_000.ts"
            merged = root / "recording_完整.ts"
            first.write_bytes(b"part")
            merged.write_bytes(b"whole")
            old = time.time() - 600
            manager = BaiduPanUploadManager(root, root)
            result = manager.reconcile_files([{
                "anchor": "主播", "latest_modified": old,
                "segments": [{"path": str(first)}], "merged_file": {"path": str(merged)},
                "files": [{"path": str(first)}, {"path": str(merged)}],
            }], enqueue=True)

            statuses = {item["path"]: item["status"] for item in result["files"]}
            self.assertEqual("archived", statuses[str(first)])
            self.assertEqual(str(merged), manager._load_queue()[0]["save_file_path"])

    def test_pending_item_can_be_paused_resumed_and_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([{
                "id": "item",
                "status": "pending",
                "save_file_path": str(root / "recording.mp4"),
                "created_at": 1,
            }])

            manager.pause_item("item")
            self.assertEqual(manager._load_queue()[0]["status"], "paused")
            manager.retry("item")
            self.assertEqual(manager._load_queue()[0]["status"], "pending")
            manager.cancel_item("item")
            self.assertEqual(manager._load_queue()[0]["status"], "cancelled")

    def test_paused_item_is_not_claimed_by_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([
                {"id": "paused", "status": "paused", "attempts": 0, "created_at": 1},
                {"id": "ready", "status": "pending", "attempts": 0, "created_at": 2},
            ])

            claimed = manager._claim_pending_items(2)

            self.assertEqual([item["id"] for item in claimed], ["ready"])


if __name__ == "__main__":
    unittest.main()
