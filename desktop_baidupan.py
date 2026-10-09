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
from collections import deque
from pathlib import Path
from typing import Callable


VIDEO_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv", ".mp3", ".m4a"}

DEFAULT_CONFIG = {
    "enabled": False,
    "auto_upload": False,
    "remote_dir": "/apps/LiveRecorder",
    "group_by_anchor": True,
    "delete_after_upload": False,
    "wait_timeout": 900,
    "retries": 3,
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
        self.logs: deque[str] = deque(maxlen=800)
        self._log_offset = 0
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._auth_process: subprocess.Popen | None = None
        self._auth_state = {"status": "idle", "authorization_url": "", "message": "尚未授权", "output": ""}

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
        config["group_by_anchor"] = bool(config.get("group_by_anchor"))
        config["delete_after_upload"] = bool(config.get("delete_after_upload"))
        config["remote_dir"] = _normalize_remote_dir(config.get("remote_dir", ""))
        for key in ("wait_timeout", "retries"):
            try:
                config[key] = int(config.get(key) or DEFAULT_CONFIG[key])
            except (TypeError, ValueError):
                config[key] = DEFAULT_CONFIG[key]
        config["wait_timeout"] = max(10, min(config["wait_timeout"], 24 * 3600))
        config["retries"] = max(1, min(config["retries"], 10))
        config["bypy_bin"] = str(config.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"]).strip()
        return config

    def save_config(self, supplied: dict) -> dict:
        current = self.load_config()
        config = {**current, **{key: supplied[key] for key in supplied if key in DEFAULT_CONFIG}}
        config["remote_dir"] = _normalize_remote_dir(config.get("remote_dir", ""))
        config["enabled"] = bool(config.get("enabled"))
        config["auto_upload"] = bool(config.get("auto_upload"))
        config["group_by_anchor"] = bool(config.get("group_by_anchor"))
        config["delete_after_upload"] = bool(config.get("delete_after_upload"))
        config["wait_timeout"] = max(10, min(int(config.get("wait_timeout") or 900), 24 * 3600))
        config["retries"] = max(1, min(int(config.get("retries") or 3), 10))
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

    def status(self) -> dict:
        with self._lock:
            queue = self._load_queue()
        return {
            "config": self.load_config(),
            "queue": sorted(queue, key=lambda item: item.get("created_at", 0), reverse=True)[:80],
            "running": bool(self._worker and self._worker.is_alive()),
            "pending": len([item for item in queue if item.get("status") in {"pending", "uploading"}]),
            "auth": dict(self._auth_state),
        }

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
        return {"ok": result.returncode == 0, "returncode": result.returncode, "output": output[-4000:]}

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
            "bypy_bin": config.get("bypy_bin") or DEFAULT_CONFIG["bypy_bin"],
            "attempts": 0,
            "error": "",
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

    def clear_finished(self) -> dict:
        with self._lock:
            queue = [item for item in self._load_queue() if item.get("status") not in {"success", "failed", "cancelled"}]
            self._save_queue(queue)
        return self.status()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            item = None
            with self._lock:
                queue = self._load_queue()
                item = next((entry for entry in queue if entry.get("status") == "pending"), None)
                if item:
                    item["status"] = "uploading"
                    item["attempts"] = int(item.get("attempts") or 0) + 1
                    item["updated_at"] = int(time.time())
                    self._save_queue(queue)
            if not item:
                return
            self._run_item(item)

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
        if item.get("delete_after_upload"):
            cmd.append("--delete-after-upload")
        self._append_log(f"开始上传：{item.get('save_file_path')}")
        try:
            process = subprocess.Popen(
                cmd,
                cwd=self.project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
            assert process.stdout is not None
            tail: deque[str] = deque(maxlen=20)
            for line in process.stdout:
                tail.append(line.rstrip())
                self._append_log(line)
            return_code = process.wait()
            if return_code == 0:
                self._finish_item(item["id"], "success", "")
                self._append_log(f"上传完成：{item.get('save_file_path')}")
            else:
                self._finish_item(item["id"], "failed", "\n".join(tail)[-2000:] or f"退出码 {return_code}")
                self._append_log(f"上传失败：{item.get('save_file_path')}")
        except Exception as exc:
            self._finish_item(item["id"], "failed", str(exc))
            self._append_log(f"上传异常：{exc}")

    def _finish_item(self, item_id: str, status: str, error: str) -> None:
        with self._lock:
            queue = self._load_queue()
            for item in queue:
                if item.get("id") == item_id:
                    item["status"] = status
                    item["error"] = error
                    item["updated_at"] = int(time.time())
                    break
            self._save_queue(queue)
