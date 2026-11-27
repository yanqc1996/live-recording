import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_baidupan import BaiduPanUploadManager


class BaiduPanUploadManagerTest(unittest.TestCase):
    def test_media_presentation_distinguishes_history_from_confirmed_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'video')
            manager = BaiduPanUploadManager(root, root)
            manager._save_queue([])
            uploaded = int(time.time())
            manager.history_path.write_text(json.dumps({str(video):{'uploaded_at':uploaded,'remote_dir':'/archive'}}))
            groups = [{'latest_modified':time.time()-600,'files':[{'path':str(video)}]}]
            historic = manager.reconcile_files(groups)['files'][0]
            self.assertEqual(historic['upload_evidence'], 'history')
            self.assertEqual(historic['remote_checked_at'], 0)
            self.assertEqual(historic['cleanup_due_at'], 0)
            manager._ensure_worker = lambda: None
            manager.save_config({'keep_local_days':1})
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'],'success','',True,[str(video)])
            manager.clear_finished()
            retained = manager.reconcile_files(groups)['files'][0]
            self.assertTrue(retained['cleanup_enabled'])
            self.assertGreaterEqual(retained['cleanup_due_at'],uploaded+86400)
            manager.save_config({'delete_after_upload':False})
            self.assertFalse(manager.reconcile_files(groups)['files'][0]['cleanup_enabled'])

    def test_cleanup_error_survives_clearing_task_records_and_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'video')
            manager = BaiduPanUploadManager(root, root)
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            with patch.object(Path, 'unlink', side_effect=PermissionError('busy')):
                status = manager.clear_finished()
            self.assertEqual(status['cleanup_pending'], 1)
            self.assertEqual(status['cleanup_errors'][0]['error'], 'busy')
            manager.status()
            self.assertFalse(video.exists())

    def test_corrupt_cleanup_ledger_does_not_clear_success_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'video')
            manager = BaiduPanUploadManager(root, root)
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            manager.cleanup_path.write_text('broken json')
            with self.assertRaises(ValueError):
                manager.clear_finished()
            self.assertEqual(len(manager._load_queue()), 1)
            self.assertTrue(video.exists())

    def test_new_upload_of_same_path_prevents_old_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'video')
            manager = BaiduPanUploadManager(root, root)
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            manager._save_queue([{'id':'new', 'status':'pending', 'save_file_path':str(video)}])
            manager._cleanup_uploaded_files()
            self.assertTrue(video.exists())
            self.assertEqual(len(manager._load_cleanup()), 1)

    def test_clear_finished_keeps_cleanup_across_restart_until_retention_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'record.mp4'
            segment = root / 'record_000.mp4'
            video.write_bytes(b'whole')
            segment.write_bytes(b'part')
            manager = BaiduPanUploadManager(root, root)
            manager._start_cleanup_verification = lambda: None
            manager._ensure_worker = lambda: None
            manager.save_config({'keep_local_days': 1})
            item = manager.enqueue_recording(str(video), cleanup_paths=[str(segment)])
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            manager.clear_finished()
            self.assertEqual(manager._load_queue(), [])
            self.assertTrue(video.exists())
            self.assertTrue(segment.exists())
            restarted = BaiduPanUploadManager(root, root)
            with patch('desktop_baidupan.time.time', return_value=time.time()+86401):
                restarted.status()
            self.assertFalse(video.exists())
            self.assertFalse(segment.exists())
            self.assertEqual(restarted._load_cleanup(), {})

    def test_changed_file_is_not_deleted_after_task_list_is_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'original')
            manager = BaiduPanUploadManager(root, root)
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            video.write_bytes(b'changed locally')
            manager.clear_finished()
            self.assertTrue(video.exists())
            self.assertIn('发生变化', manager._load_cleanup()[item['id']]['cleanup_error'])

    def test_disabling_cleanup_preserves_cleared_task_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'original')
            manager = BaiduPanUploadManager(root, root)
            manager._ensure_worker = lambda: None
            item = manager.enqueue_recording(str(video))
            manager._finish_item(item['id'], 'success', '', True, [str(video)])
            manager.save_config({'delete_after_upload': False})
            manager.clear_finished()
            self.assertTrue(video.exists())

    def test_history_requires_remote_size_confirmation_before_cleanup(self):
        for remote_output, returncode, removed in [('CLEANUP|F|5\n',0,True), ('CLEANUP|F|99\n',0,False), ('',1,False), ('',0,False)]:
            with self.subTest(output=remote_output), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                video = root/'record.mp4'
                segment = root/'record_000.mp4'
                for path in [video, segment]:
                    path.write_bytes(b'video')
                    os.utime(path,(time.time()-3*86400,time.time()-3*86400))
                manager = BaiduPanUploadManager(root, root)
                manager._ensure_worker = lambda: None
                manager.save_config({'enabled':True,'keep_local_days':1})
                manager.history_path.write_text(json.dumps({str(video): {'remote_dir':'/archive','uploaded_at':int(time.time()-2*86400)}}))
                manager._recover_history_cleanup([{'latest_modified':time.time()-3*86400,'merged_file':{'path':str(video)},'segments':[{'path':str(segment)}]}])
                candidates = list(manager._load_cleanup().values())
                self.assertEqual(len(candidates),1)
                manager._cleanup_uploaded_files()
                self.assertTrue(video.exists())
                with patch('desktop_baidupan.subprocess.run') as run:
                    run.return_value.returncode = returncode
                    run.return_value.stdout = remote_output
                    manager._verify_history_cleanup(candidates)
                self.assertEqual(not video.exists(), removed)
                self.assertEqual(not segment.exists(), removed)
                if not removed:
                    self.assertTrue(next(iter(manager._load_cleanup().values()))['cleanup_error'])

    def test_history_does_not_recover_active_or_changed_recordings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root/'record.mp4'
            video.write_bytes(b'new data')
            manager = BaiduPanUploadManager(root, root)
            manager._ensure_worker = lambda: None
            manager.save_config({'enabled':True})
            manager.history_path.write_text(json.dumps({str(video): {'remote_dir':'/archive','uploaded_at':int(time.time()-86400)}}))
            for modified in [time.time(),time.time()-600]:
                manager._recover_history_cleanup([{'latest_modified':modified,'files':[{'path':str(video)}]}])
            self.assertEqual(manager._load_cleanup(), {})

    def test_transcription_failure_allows_upload_and_verified_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'record.ts'
            video.write_bytes(b'video')
            def fail(item, cancelled):
                raise RuntimeError('转写失败')
            manager = BaiduPanUploadManager(root, root, before_upload=fail)
            item = manager.enqueue_recording(str(video), record_name='主播')
            claimed = manager._claim_pending_items(1)[0]
            with patch('desktop_baidupan.subprocess.Popen') as process:
                process.return_value.stdout = iter([])
                process.return_value.wait.return_value = 0
                manager._run_item(claimed)
                process.assert_called_once()
            saved = manager._load_queue()[0]
            self.assertEqual(saved['status'], 'success')
            self.assertIn('转写失败', saved['transcription_error'])
            self.assertFalse(saved['transcription_archived'])
            self.assertFalse(video.exists())

    def test_upload_pause_during_transcription_still_prevents_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'record.ts'
            video.write_bytes(b'video')
            manager = BaiduPanUploadManager(root, root)
            def pause(item, cancelled):
                manager.pause_item(item['id'])
                raise InterruptedError('暂停')
            manager.before_upload = pause
            manager.enqueue_recording(str(video))
            claimed = manager._claim_pending_items(1)[0]
            with patch('desktop_baidupan.subprocess.Popen') as process:
                manager._run_item(claimed)
                process.assert_not_called()
            self.assertEqual(manager._load_queue()[0]['status'], 'paused')
            self.assertTrue(video.exists())

    def test_interrupted_upload_returns_to_pending_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            queue_path = root / "config" / "baidupan_queue.json"
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(json.dumps([{
                "id": "upload-1", "status": "uploading", "save_file_path": "/tmp/a.ts", "created_at": 1,
            }]), encoding="utf-8")

            manager = BaiduPanUploadManager(root, root)

            recovered = manager._load_queue()[0]
            self.assertEqual("pending", recovered["status"])
            self.assertIn("自动恢复", recovered["error"])

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
