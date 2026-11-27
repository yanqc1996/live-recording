"""Persistent background queue for recording post-processing tasks."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable


def _atomic_write(path: Path, value: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class RecordingTaskQueue:
    def __init__(self, path: Path, handler: Callable[[dict], None], retry_delay: float = 15):
        self.path = path
        self.handler = handler
        self.retry_delay = retry_delay
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._recover_interrupted()
        self._worker = threading.Thread(target=self._run, daemon=True, name="recording-task-queue")
        self._worker.start()

    def _load(self) -> list[dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, tasks: list[dict]) -> None:
        _atomic_write(self.path, tasks)

    def _recover_interrupted(self) -> None:
        with self._lock:
            tasks = self._load()
            changed = False
            for task in tasks:
                if task.get("status") == "running":
                    task.update({"status": "pending", "error": "应用上次退出时任务尚未完成，已自动恢复", "next_attempt_at": 0})
                    changed = True
            if changed:
                self._save(tasks)

    def enqueue(self, kind: str, payload: dict, dedupe_key: str = "") -> dict:
        with self._lock:
            tasks = self._load()
            if dedupe_key:
                existing = next((item for item in tasks if item.get("dedupe_key") == dedupe_key and item.get("status") in {"pending", "running", "success"}), None)
                if existing:
                    return existing
            now = time.time()
            task = {
                "id": uuid.uuid4().hex, "kind": kind, "payload": payload, "dedupe_key": dedupe_key,
                "status": "pending", "attempts": 0, "max_attempts": 3, "error": "",
                "created_at": now, "updated_at": now, "next_attempt_at": 0,
            }
            tasks.append(task)
            self._save(tasks[-300:])
        self._wake.set()
        return task

    def _next(self) -> dict | None:
        with self._lock:
            tasks = self._load()
            now = time.time()
            task = next((item for item in tasks if item.get("status") == "pending" and float(item.get("next_attempt_at") or 0) <= now), None)
            if not task:
                return None
            task.update({"status": "running", "attempts": int(task.get("attempts") or 0) + 1, "updated_at": now, "error": ""})
            self._save(tasks)
            return dict(task)

    def _finish(self, task_id: str, error: Exception | None = None) -> None:
        with self._lock:
            tasks = self._load()
            task = next((item for item in tasks if item.get("id") == task_id), None)
            if not task:
                return
            if error is None:
                task.update({"status": "success", "completed_at": time.time(), "updated_at": time.time(), "error": ""})
            elif int(task.get("attempts") or 0) < int(task.get("max_attempts") or 3):
                task.update({"status": "pending", "updated_at": time.time(), "error": str(error), "next_attempt_at": time.time() + self.retry_delay})
            else:
                task.update({"status": "failed", "updated_at": time.time(), "error": str(error)})
            self._save(tasks)

    def _run(self) -> None:
        while not self._stop.is_set():
            task = self._next()
            if not task:
                self._wake.wait(2)
                self._wake.clear()
                continue
            try:
                self.handler(task)
                self._finish(str(task["id"]))
            except Exception as exc:
                self._finish(str(task["id"]), exc)

    def retry(self, task_id: str) -> dict:
        with self._lock:
            tasks = self._load()
            task = next((item for item in tasks if item['id'] == task_id), None)
            if not task:
                raise ValueError('整理任务不存在')
            if task.get('status') != 'failed':
                raise ValueError('只能重试失败的整理任务')
            task.update(status='pending', attempts=0, error='', next_attempt_at=0, updated_at=time.time())
            self._save(tasks)
            result = dict(task)
        self._wake.set()
        return result

    def status(self) -> dict:
        with self._lock:
            tasks = sorted(self._load(), key=lambda item: item.get("created_at", 0), reverse=True)
        return {
            "tasks": tasks[:80],
            "pending": sum(item.get("status") == "pending" for item in tasks),
            "running": sum(item.get("status") == "running" for item in tasks),
            "failed": sum(item.get("status") == "failed" for item in tasks),
        }

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker.is_alive() and threading.current_thread() is not self._worker:
            self._worker.join(timeout=2)
