"""Baidu Netdisk upload settings and queue for the desktop app."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
import shutil
from collections import deque
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv", ".mp3", ".m4a"}

DEFAULT_CONFIG = {
    "enabled": False,
    "auto_upload": False,
    "paused": False,
    "remote_dir": "/apps/LiveRecorder",
    "group_by_anchor": True,
    "delete_after_upload": True,
    "keep_local_days": 0,
    "cleanup_below_free_gb": 0,
    "wait_timeout": 900,
    "retries": 3,
    "max_concurrent_uploads": 3,
    "bypy_bin": "__python_module_bypy__",
}


def _atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _safe_remote_part(value: str) -> str:
    value = re.sub(r"^序号\d+\s+", "", str(value or "")).strip()
    value = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", value).strip(" ._")
    return value[:80] or "未命名主播"


def _normalize_remote_dir(value: str) -> str:
    value = str(value or "").strip() or DEFAULT_CONFIG["remote_dir"]
    value = "/" + value.strip("/")
    return value.rstrip("/") or "/"


def bypy_command(configured: str) -> list[str]:
    configured = str(configured or "").strip()
    if not configured:
        configured = DEFAULT_CONFIG["bypy_bin"]
    if configured == "__python_module_bypy__":
        return [sys.executable, "-m", "bypy"]
    return shlex.split(configured)


class BaiduPanUploadManager:
    def __init__(
        self,
        project_root: Path,
        bundle_root: Path,
        on_log: Callable[[str], None] | None = None,
    ):
        self.project_root = project_root
        self.bundle_root = bundle_root
        self.on_log = on_log
        self.config_path = project_root / "config" / "baidupan_upload.json"
        self.queue_path = project_root / "config" / "baidupan_queue.json"
        self.history_path = project_root / "config" / "baidupan_history.json"
        self.logs: deque[str] = deque(maxlen=800)
        self._log_offset = 0
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._active_workers: dict[str, threading.Thread] = {}
        self._active_processes: dict[str, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._auth_process: subprocess.Popen | None = None
        self._auth_state = {"status": "idle", "authorization_url": "", "message": "尚未授权", "output": ""}
        self._progresses: dict[str, dict] = {}
        self._ensure_worker()

    def _append_log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        if self.logs.maxlen and len(self.logs) == self.logs.maxlen:
            self._log_offset += 1
        self.logs.append(line)
        if self.on_log:
            self.on_log(f"百度网盘：{line}")

    def logs_snapshot(self, after: int = 0) -> dict:
        lines = list(self.logs)
        start = max(0, min(after - self._log_offset, len(lines)))
        return {"lines": lines[start:], "cursor": self._log_offset + len(lines)}

    def load_config(self) -> dict:
        data = {}
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        config = {**DEFAULT_CONFIG, **(data if isinstance(data, dict) else {})}
        config["enabled"] = bool(config.get("enabled"))
        config["auto_upload"] = bool(config.get("auto_upload"))
        config["paused"] = bool(config.get("paused"))
        config["group_by_anchor"] = bool(config.get("group_by_anchor"))
        config["delete_after_upload"] = bool(config.get("delete_after_upload"))
        config["remote_dir"] = _normalize_remote_dir(config.get("remote_dir", ""))
        for key in ("wait_timeout", "retries", "max_concurrent_uploads"):
            try:
                config[key] = int(config.get(key) or DEFAULT_CONFIG[key])
            except (TypeError, ValueError):
                config[key] = DEFAULT_CONFIG[key]
        for key in ("keep_local_days", "cleanup_below_free_gb"):
            try:
                config[key] = int(config.get(key, DEFAULT_CONFIG[key]))
            except (TypeError, ValueError):
                config[key] = DEFAULT_CONFIG[key]
        config["wait_timeout"] = max(10, min(config["wait_timeout"], 24 * 3600))
        config["retries"] = max(1, min(config["retries"], 10))
        config["max_concurrent_uploads"] = max(1, min(config["max_concurrent_uploads"], 5))
        config["keep_local_days"] = max(0, min(config["keep_local_days"], 3650))
        config["cleanup_below_free_gb"] = max(0, min(config["cleanup_below_free_gb"], 10000))
        config["bypy_bin"] = str(config.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"]).strip()
        return config

    def save_config(self, supplied: dict) -> dict:
        current = self.load_config()
        config = {**current, **{key: supplied[key] for key in supplied if key in DEFAULT_CONFIG}}
        config["remote_dir"] = _normalize_remote_dir(config.get("remote_dir", ""))
        config["enabled"] = bool(config.get("enabled"))
        config["auto_upload"] = bool(config.get("auto_upload"))
        config["paused"] = bool(config.get("paused"))
        config["group_by_anchor"] = bool(config.get("group_by_anchor"))
        config["delete_after_upload"] = bool(config.get("delete_after_upload"))
        config["wait_timeout"] = max(10, min(int(config.get("wait_timeout") or 900), 24 * 3600))
        config["retries"] = max(1, min(int(config.get("retries") or 3), 10))
        config["max_concurrent_uploads"] = max(1, min(int(config.get("max_concurrent_uploads") or 3), 5))
        config["keep_local_days"] = max(0, min(int(config.get("keep_local_days") or 0), 3650))
        config["cleanup_below_free_gb"] = max(0, min(int(config.get("cleanup_below_free_gb") or 0), 10000))
        config["bypy_bin"] = str(config.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"]).strip()
        with self._lock:
            _atomic_json(self.config_path, config)
        self._ensure_worker()
        return config

    def _load_queue(self) -> list[dict]:
        if not self.queue_path.exists():
            return []
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def _save_queue(self, queue: list[dict]) -> None:
        _atomic_json(self.queue_path, queue)

    def _load_history(self) -> dict:
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def reconcile_files(self, groups: list[dict], enqueue: bool = False) -> dict:
        queue = self._load_queue()
        history = self._load_history()
        by_path = {}
        for item in queue:
            for value in item.get("uploaded_files") or [item.get("save_file_path")]:
                if value:
                    by_path[str(Path(value))] = item
        files = []
        added = 0
        now = time.time()
        for group in groups:
            anchor = str(group.get("anchor") or "历史录像")
            group_active = now - float(group.get("latest_modified") or 0) < 300
            for file_item in group.get("files") or []:
                path = str(Path(str(file_item.get("path") or "")))
                item = by_path.get(path)
                status = str(item.get("status")) if item else ("success" if path in history else "untracked")
                files.append({"path": path, "status": status, "item_id": item.get("id") if item else ""})
                if enqueue and status == "untracked" and not group_active:
                    self.enqueue_recording(path, record_name=anchor, save_type=Path(path).suffix.lstrip(".").upper(), source="reconcile")
                    added += 1
        return {"files": files, "counts": {key: sum(f["status"] == key for f in files) for key in ("untracked", "pending", "uploading", "success", "failed", "paused")}, "added": added}

    def status(self) -> dict:
        self._cleanup_uploaded_files()
        with self._lock:
            queue = self._load_queue()
        return {
            "config": self.load_config(),
            "queue": sorted(queue, key=lambda item: item.get("created_at", 0), reverse=True)[:80],
            "running": bool(self._worker and self._worker.is_alive()),
            "pending": len([item for item in queue if item.get("status") in {"pending", "uploading"}]),
            "auth": dict(self._auth_state),
            "paused": bool(self.load_config().get("paused")),
            "pending_bytes": sum(int(item.get("file_size") or 0) for item in queue if item.get("status") in {"pending", "uploading"}),
            "progress": dict(next(iter(self._progresses.values()), {"item_id": "", "file": "", "percent": 0})),
            "progresses": [dict(progress) for progress in self._progresses.values()],
        }

    def set_paused(self, paused: bool) -> dict:
        config = self.load_config()
        config["paused"] = bool(paused)
        self.save_config(config)
        if not paused:
            self._ensure_worker()
        return self.status()

    def start_auth(self) -> dict:
        with self._lock:
            if self._auth_process and self._auth_process.poll() is None:
                return dict(self._auth_state)
            config = self.load_config()
            self._auth_state = {"status": "starting", "authorization_url": "", "message": "正在准备百度授权…", "output": ""}
            self._auth_process = subprocess.Popen(
                [*bypy_command(config["bypy_bin"]), "info"],
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            threading.Thread(target=self._read_auth_process, daemon=True).start()
            return dict(self._auth_state)

    def _read_auth_process(self) -> None:
        process = self._auth_process
        if not process or not process.stdout:
            return
        lines: deque[str] = deque(maxlen=80)
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            lines.append(line)
            url_match = re.search(r"https?://\S+", line)
            with self._lock:
                if url_match:
                    self._auth_state.update({
                        "status": "waiting_code",
                        "authorization_url": url_match.group(0).rstrip(".,;"),
                        "message": "请在浏览器授权后粘贴授权码",
                    })
                self._auth_state["output"] = "\n".join(lines)[-6000:]
        return_code = process.wait()
        with self._lock:
            self._auth_state.update({
                "status": "authorized" if return_code == 0 else "failed",
                "message": "百度网盘授权成功" if return_code == 0 else "授权失败，请重新尝试",
                "output": "\n".join(lines)[-6000:],
            })
            self._auth_process = None

    def submit_auth_code(self, code: str) -> dict:
        code = str(code or "").strip()
        if len(code) < 16:
            raise ValueError("请输入百度授权页面返回的完整授权码")
        with self._lock:
            process = self._auth_process
            if not process or process.poll() is not None or not process.stdin:
                raise RuntimeError("当前没有等待授权的任务，请先点击开始授权")
            process.stdin.write(code + "\n")
            process.stdin.flush()
            self._auth_state.update({"status": "authorizing", "message": "正在完成授权…"})
            return dict(self._auth_state)

    def script_path(self) -> Path:
        bundled = self.bundle_root / "scripts" / "upload_to_baidu_netdisk.py"
        if bundled.exists():
            return bundled
        return self.project_root / "scripts" / "upload_to_baidu_netdisk.py"

    def check_auth(self, timeout: int = 25) -> dict:
        config = self.load_config()
        cmd = [*bypy_command(config["bypy_bin"]), "info"]
        try:
            result = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
            return {"ok": False, "error": "授权检测超时，请按输出中的链接完成 bypy 授权后重试", "output": output}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "output": ""}
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        ok = result.returncode == 0
        if ok:
            self._auth_state.update({"status": "authorized", "message": "百度网盘授权成功", "output": output[-4000:]})
        return {"ok": ok, "returncode": result.returncode, "output": output[-4000:]}

    def enqueue_recording(
        self,
        save_file_path: str,
        record_name: str = "",
        save_type: str = "",
        split_video_by_time: bool = False,
        converts_to_mp4: bool = False,
        source: str = "auto",
    ) -> dict:
        path = Path(str(save_file_path or "").strip()).expanduser()
        if not str(path):
            raise ValueError("上传文件路径不能为空")
        suffix = path.suffix.lower()
        if suffix and suffix not in VIDEO_EXTENSIONS:
            raise ValueError("只支持上传录制视频或音频文件")
        config = self.load_config()
        remote_dir = config["remote_dir"]
        if config.get("group_by_anchor") and record_name:
            remote_dir = f"{remote_dir.rstrip('/')}/{_safe_remote_part(record_name)}"
        item = {
            "id": uuid.uuid4().hex,
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "status": "pending",
            "source": source,
            "record_name": record_name or path.stem,
            "save_file_path": str(path),
            "save_type": (save_type or path.suffix.lstrip(".") or "TS").upper(),
            "split_video_by_time": bool(split_video_by_time or "%03d" in path.name),
            "converts_to_mp4": bool(converts_to_mp4),
            "remote_dir": remote_dir,
            "delete_after_upload": bool(config.get("delete_after_upload")),
            "wait_timeout": int(config.get("wait_timeout") or 900),
            "retries": int(config.get("retries") or 3),
            "keep_local_days": int(config.get("keep_local_days") or 0),
            "cleanup_below_free_gb": int(config.get("cleanup_below_free_gb") or 0),
            "bypy_bin": config.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"],
            "attempts": 0,
            "error": "",
            "remote_verified": False,
            "local_deleted": False,
            "file_size": path.stat().st_size if path.exists() and path.is_file() else 0,
        }
        with self._lock:
            queue = self._load_queue()
            for old in queue:
                if (
                    old.get("save_file_path") == item["save_file_path"]
                    and old.get("remote_dir") == item["remote_dir"]
                    and old.get("status") in {"pending", "uploading", "success"}
                ):
                    return old
            queue.append(item)
            self._save_queue(queue)
        self._append_log(f"已加入上传队列：{item['save_file_path']}")
        self._ensure_worker()
        return item

    def enqueue_archive(self, groups: list[dict]) -> dict:
        config = self.load_config()
        if not config.get("enabled"):
            raise RuntimeError("请先启用百度网盘上传并完成授权")
        added = 0
        existing = 0
        for group in groups:
            anchor = str(group.get("anchor") or "历史录像")
            for file_item in group.get("files") or []:
                before = len(self._load_queue())
                self.enqueue_recording(
                    str(file_item.get("path") or ""),
                    record_name=anchor,
                    save_type=Path(str(file_item.get("path") or "")).suffix.lstrip(".").upper(),
                    source="archive",
                )
                after = len(self._load_queue())
                if after > before:
                    added += 1
                else:
                    existing += 1
        return {"added": added, "existing": existing, "groups": len(groups), "status": self.status()}

    def retry(self, item_id: str) -> dict:
        with self._lock:
            queue = self._load_queue()
            item = next((entry for entry in queue if entry.get("id") == item_id), None)
            if not item:
                raise IndexError("上传任务不存在")
            item.update({"status": "pending", "error": "", "updated_at": int(time.time())})
            self._save_queue(queue)
        self._ensure_worker()
        return item

    def pause_item(self, item_id: str) -> dict:
        with self._lock:
            queue = self._load_queue()
            item = next((entry for entry in queue if entry.get("id") == item_id), None)
            if not item:
                raise IndexError("上传任务不存在")
            if item.get("status") not in {"pending", "uploading"}:
                raise RuntimeError("只有等待中或上传中的任务可以暂停")
            item.update({"status": "paused", "updated_at": int(time.time())})
            self._save_queue(queue)
            process = self._active_processes.get(item_id)
            if process and process.poll() is None:
                process.terminate()
        self._append_log(f"已暂停上传：{item.get('save_file_path')}")
        return item

    def cancel_item(self, item_id: str) -> dict:
        with self._lock:
            queue = self._load_queue()
            item = next((entry for entry in queue if entry.get("id") == item_id), None)
            if not item:
                raise IndexError("上传任务不存在")
            if item.get("status") not in {"pending", "uploading", "paused", "failed"}:
                raise RuntimeError("当前任务不能取消")
            item.update({"status": "cancelled", "updated_at": int(time.time()), "error": ""})
            self._save_queue(queue)
            process = self._active_processes.get(item_id)
            if process and process.poll() is None:
                process.terminate()
        self._append_log(f"已取消上传：{item.get('save_file_path')}")
        return item

    def _queue_status(self, item_id: str) -> str:
        with self._lock:
            item = next((entry for entry in self._load_queue() if entry.get("id") == item_id), None)
        return str(item.get("status") or "") if item else ""

    def clear_finished(self) -> dict:
        with self._lock:
            queue = [item for item in self._load_queue() if item.get("status") not in {"success", "failed", "cancelled"}]
            self._save_queue(queue)
        return self.status()

    def _ensure_worker(self) -> None:
        with self._lock:
            if not self.load_config().get("enabled"):
                return
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if self.load_config().get("paused"):
                return
            with self._lock:
                self._active_workers = {
                    item_id: worker for item_id, worker in self._active_workers.items() if worker.is_alive()
                }
                available = self.load_config()["max_concurrent_uploads"] - len(self._active_workers)
            items = self._claim_pending_items(available)
            for item in items:
                worker = threading.Thread(target=self._run_item, args=(item,), daemon=True)
                with self._lock:
                    self._active_workers[item["id"]] = worker
                worker.start()
            with self._lock:
                active = bool(self._active_workers)
            if not items and not active:
                return
            self._stop.wait(0.25)

    def _claim_pending_items(self, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        claimed = []
        now = int(time.time())
        with self._lock:
            queue = self._load_queue()
            for item in queue:
                if item.get("status") != "pending":
                    continue
                item["status"] = "uploading"
                item["attempts"] = int(item.get("attempts") or 0) + 1
                item["updated_at"] = now
                claimed.append(dict(item))
                if len(claimed) >= limit:
                    break
            if claimed:
                self._save_queue(queue)
        return claimed

    def _run_item(self, item: dict) -> None:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--upload-to-baidupan"]
        else:
            cmd = [sys.executable, str(self.script_path())]
        cmd.extend([
            "--remote-dir",
            str(item["remote_dir"]),
            "--bypy-bin",
            str(item.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"]),
            "--wait-timeout",
            str(item.get("wait_timeout") or 900),
            "--retries",
            str(item.get("retries") or 3),
            "--record_name",
            str(item.get("record_name") or Path(item["save_file_path"]).stem),
            "--save_file_path",
            str(item["save_file_path"]),
            "--save_type",
            str(item.get("save_type") or "TS"),
            "--split_video_by_time",
            str(bool(item.get("split_video_by_time"))),
            "--converts_to_mp4",
            str(bool(item.get("converts_to_mp4"))),
        ])
        self._append_log(f"开始上传：{item.get('save_file_path')}")
        with self._lock:
            self._progresses[item["id"]] = {
                "item_id": item["id"],
                "file": Path(item["save_file_path"]).name,
                "percent": 0,
                "stage": "正在准备",
                "speed_bps": 0,
                "eta_seconds": None,
                "started_at": time.time(),
            }
        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.project_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            with self._lock:
                self._active_processes[item["id"]] = process
                if item["id"] in self._progresses:
                    self._progresses[item["id"]]["stage"] = "正在上传"
            assert process.stdout is not None
            tail: deque[str] = deque(maxlen=20)
            uploaded_files: list[str] = []
            for line in process.stdout:
                tail.append(line.rstrip())
                self._append_log(line)
                uploaded = re.search(r"^\[baidupan\] uploaded: (.+?) -> ", line.rstrip())
                if uploaded:
                    uploaded_files.append(uploaded.group(1))
                percent = re.search(r"(?<!\d)(100|\d{1,2})(?:\.\d+)?%", line)
                if percent:
                    with self._lock:
                        if item["id"] in self._progresses:
                            progress = self._progresses[item["id"]]
                            value = int(percent.group(1))
                            elapsed = max(0.1, time.time() - float(progress.get("started_at") or time.time()))
                            size = int(item.get("file_size") or 0)
                            completed = size * value / 100
                            speed = completed / elapsed if completed > 0 else 0
                            progress.update({
                                "percent": value,
                                "stage": "正在确认远端文件" if value >= 100 else "正在上传",
                                "speed_bps": int(speed),
                                "eta_seconds": int((size - completed) / speed) if speed > 0 and value < 100 else 0 if value >= 100 else None,
                            })
            return_code = process.wait()
            current_status = self._queue_status(item["id"])
            if current_status in {"paused", "cancelled"}:
                return
            if return_code == 0:
                self._finish_item(item["id"], "success", "", remote_verified=True, uploaded_files=uploaded_files)
                self._append_log(f"上传完成：{item.get('save_file_path')}")
                self._cleanup_uploaded_files()
            else:
                self._finish_item(item["id"], "failed", "\n".join(tail)[-2000:] or f"退出码 {return_code}")
                self._append_log(f"上传失败：{item.get('save_file_path')}")
        except Exception as exc:
            self._finish_item(item["id"], "failed", str(exc))
            self._append_log(f"上传异常：{exc}")
        finally:
            with self._lock:
                self._active_processes.pop(item["id"], None)
                self._progresses.pop(item["id"], None)

    def _finish_item(self, item_id: str, status: str, error: str, remote_verified: bool = False, uploaded_files: list[str] | None = None) -> None:
        with self._lock:
            queue = self._load_queue()
            for item in queue:
                if item.get("id") == item_id:
                    item["status"] = status
                    item["error"] = error
                    item["updated_at"] = int(time.time())
                    item["remote_verified"] = bool(remote_verified)
                    if uploaded_files:
                        item["uploaded_files"] = list(dict.fromkeys(uploaded_files))
                        history = self._load_history()
                        for value in uploaded_files:
                            history[str(Path(value))] = {"uploaded_at": int(time.time()), "remote_dir": item.get("remote_dir", "")}
                        _atomic_json(self.history_path, history)
                    break
            self._save_queue(queue)

    def _cleanup_uploaded_files(self) -> None:
        with self._lock:
            queue = self._load_queue()
            changed = False
            now = time.time()
            for item in queue:
                if not (item.get("status") == "success" and item.get("remote_verified") and item.get("delete_after_upload")):
                    continue
                if item.get("local_deleted"):
                    continue
                paths = [Path(str(value)) for value in item.get("uploaded_files") or [item.get("save_file_path") or ""]]
                existing = [path for path in paths if path.exists() and path.is_file()]
                if existing:
                    keep_seconds = int(item.get("keep_local_days") or 0) * 86400
                    if keep_seconds and any(now - path.stat().st_mtime < keep_seconds for path in existing):
                        continue
                    threshold = int(item.get("cleanup_below_free_gb") or 0) * 1024 ** 3
                    if threshold and shutil.disk_usage(existing[0].parent).free >= threshold:
                        continue
                try:
                    for path in existing:
                        path.unlink()
                        self._append_log(f"远端已确认，已清理本地文件：{path}")
                    item["local_deleted"] = True
                    item["deleted_at"] = int(now)
                    changed = True
                except OSError as exc:
                    item["cleanup_error"] = str(exc)
                    changed = True
            if changed:
                self._save_queue(queue)
