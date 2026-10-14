"""Cached media integrity checks for completed recordings."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def inspect_media_file(path: Path, ffmpeg: str | None = None) -> dict:
    path = path.resolve()
    checked_at = int(time.time())
    if not path.is_file() or path.stat().st_size <= 0:
        return {"status": "failed", "error": "文件不存在或大小为 0", "checked_at": checked_at}
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        return {"status": "failed", "error": "未找到 FFmpeg", "checked_at": checked_at}
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-v", "info", "-i", str(path), "-map", "0", "-c", "copy", "-f", "null", "-"],
            capture_output=True, text=True, timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "error": f"检查失败：{exc}", "checked_at": checked_at}
    output = f"{result.stdout}\n{result.stderr}"
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    duration = 0.0
    if duration_match:
        duration = int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3))
    has_video = bool(re.search(r"Stream #.*Video:", output))
    has_audio = bool(re.search(r"Stream #.*Audio:", output))
    errors = [line.strip() for line in output.splitlines() if re.search(r"invalid|corrupt|error|failed", line, re.I)]
    if result.returncode != 0:
        return {"status": "failed", "error": errors[-1] if errors else f"FFmpeg 返回码 {result.returncode}", "duration_seconds": duration, "has_video": has_video, "has_audio": has_audio, "checked_at": checked_at}
    warning = "视频中未检测到音轨" if has_video and not has_audio else ""
    return {"status": "warning" if warning else "healthy", "warning": warning, "duration_seconds": duration, "has_video": has_video, "has_audio": has_audio, "checked_at": checked_at}


class MediaIntegrityStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def results(self) -> dict:
        with self._lock:
            return self._load()

    def inspect(self, media_path: str, force: bool = False) -> dict:
        path = Path(media_path).resolve()
        stat = path.stat() if path.exists() else None
        signature = f"{stat.st_size}:{stat.st_mtime_ns}" if stat else "missing"
        with self._lock:
            cached = self._load().get(str(path), {})
            if not force and cached.get("signature") == signature:
                return cached
        result = {**inspect_media_file(path), "path": str(path), "signature": signature}
        with self._lock:
            data = self._load()
            data[str(path)] = result
            _atomic_json(self.path, data)
        return result
