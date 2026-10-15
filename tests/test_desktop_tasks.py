import json
import tempfile
import time
import unittest
from pathlib import Path

from desktop_tasks import RecordingTaskQueue


class RecordingTaskQueueTest(unittest.TestCase):
    def test_interrupted_task_is_recovered_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            path.write_text(json.dumps([{
                "id": "task-1", "kind": "finalize_recording", "payload": {}, "status": "running",
                "attempts": 1, "max_attempts": 3, "created_at": 1, "updated_at": 1,
            }]), encoding="utf-8")
            completed = []
            queue = RecordingTaskQueue(path, lambda task: completed.append(task["id"]), retry_delay=0)
            deadline = time.time() + 2
            while time.time() < deadline and not completed:
                time.sleep(0.01)
            queue.stop()

            self.assertEqual(["task-1"], completed)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("success", saved[0]["status"])

    def test_enqueue_deduplicates_completed_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = RecordingTaskQueue(Path(directory) / "tasks.json", lambda _task: None)
            first = queue.enqueue("finalize_recording", {"path": "/tmp/a.ts"}, dedupe_key="/tmp/a.ts")
            second = queue.enqueue("finalize_recording", {"path": "/tmp/a.ts"}, dedupe_key="/tmp/a.ts")
            queue.stop()

            self.assertEqual(first["id"], second["id"])
