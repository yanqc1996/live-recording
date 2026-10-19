"""Local media library grouped by anchor."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


MEDIA_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
RECORDING_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv", ".mp3", ".m4a"}


def scan_recordings(root: Path, limit: int | None = 100) -> list[dict]:
    if not root.exists():
        return []
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RECORDING_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append({"name": path.name, "path": str(path), "size": stat.st_size, "modified": stat.st_mtime})
    files.sort(key=lambda item: item["modified"], reverse=True)
    return files if limit is None else files[:limit]


class RecentRecordingCache:
    """Avoid repeatedly walking a large recording tree for frequent state polls."""

    def __init__(self, ttl_seconds: float = 15.0, limit: int = 100):
        self.ttl_seconds = ttl_seconds
        self.limit = limit
        self._lock = threading.Lock()
        self._root = ""
        self._expires_at = 0.0
        self._items: list[dict] = []

    def get(self, root: Path, force: bool = False) -> list[dict]:
        root_key = str(root.resolve())
        now = time.monotonic()
        with self._lock:
            if not force and root_key == self._root and now < self._expires_at:
                return list(self._items)
            items = self._scan(root)
            self._root = root_key
            self._expires_at = time.monotonic() + self.ttl_seconds
            self._items = items
            return list(items)

    def invalidate(self) -> None:
        with self._lock:
            self._expires_at = 0.0

    def _scan(self, root: Path) -> list[dict]:
        return scan_recordings(root, self.limit)


def group_recordings(files: list[dict]) -> list[dict]:
    """Group recorder segments that share the same anchor and start timestamp."""
    groups: dict[str, dict] = {}
    pattern = re.compile(r"^(?P<prefix>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_(?P<part>\d{3,}|完整)$")
    for item in files:
        path = Path(str(item.get("path") or ""))
        match = pattern.match(path.stem)
        group_stem = f"{match.group('prefix')}_{match.group('date')}_{match.group('time')}" if match else path.stem
        key = str(path.parent / group_stem)
        group = groups.setdefault(key, {
            "id": key,
            "anchor": path.parent.name or (match.group("prefix") if match else path.stem),
            "started_at": float(item.get("modified") or 0),
            "latest_modified": 0.0,
            "total_size": 0,
            "segment_count": 0,
            "formats": set(),
            "files": [],
            "segments": [],
            "merged_file": None,
        })
        if match:
            try:
                group["started_at"] = datetime.strptime(
                    f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H-%M-%S"
                ).timestamp()
            except ValueError:
                pass
        group["latest_modified"] = max(group["latest_modified"], float(item.get("modified") or 0))
        is_merged = bool(match and match.group("part") == "完整")
        if not is_merged:
            group["total_size"] += int(item.get("size") or 0)
            group["segment_count"] += 1
        group["formats"].add(path.suffix.lstrip(".").upper())
        group["files"].append(item)
        if is_merged:
            group["merged_file"] = item
        else:
            group["segments"].append(item)
    result = []
    for group in groups.values():
        group["files"].sort(key=lambda item: float(item.get("modified") or 0), reverse=True)
        group["path"] = group["files"][0].get("path", "")
        group["name"] = group["files"][0].get("name", "")
        group["format"] = "/".join(sorted(group.pop("formats")))
        group["duration_seconds"] = max(0, int(group["latest_modified"] - group["started_at"]))
        extensions = {Path(str(item.get("path") or "")).suffix.lower() for item in group["segments"]}
        group["settled"] = time.time() - group["latest_modified"] >= 60
        group["mergeable"] = (
            group["segment_count"] >= 2 and len(extensions) == 1
            and not group["merged_file"] and group["settled"]
        )
        result.append(group)
    result.sort(key=lambda group: group["latest_modified"], reverse=True)
    return result


def merge_recording_group(group: dict, ffmpeg: str | None = None, minimum_age_seconds: int = 60) -> dict:
    """Losslessly concatenate a completed recording's same-format segments."""
    segments = [Path(str(item.get("path") or "")).resolve() for item in group.get("segments") or []]
    if len(segments) < 2:
        raise ValueError("该场直播不足 2 个分段，无需合并")
    if any(not path.is_file() for path in segments):
        raise ValueError("部分录像分段已不存在，请刷新媒体库")
    parents = {path.parent for path in segments}
    suffixes = {path.suffix.lower() for path in segments}
    if len(parents) != 1 or len(suffixes) != 1:
        raise ValueError("仅支持合并同一目录、同一格式的录像分段")
    newest_mtime = max(path.stat().st_mtime for path in segments)
    if time.time() - newest_mtime < minimum_age_seconds:
        raise RuntimeError("录像分段仍可能正在写入，请结束录制并稍后再合并")
    if group.get("merged_file"):
        raise FileExistsError("该场直播已经生成完整文件")

    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("未找到 FFmpeg，无法合并录像")
    first = segments[0]
    match = re.match(r"^(?P<base>.+)_\d{3,}$", first.stem)
    base = match.group("base") if match else first.stem
    output = first.parent / f"{base}_完整{first.suffix.lower()}"
    if output.exists():
        raise FileExistsError(f"完整文件已存在：{output.name}")
    temporary_output = output.with_name(f".{output.stem}.merging{output.suffix}")

    ordered = sorted(segments, key=lambda path: path.name)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", dir=first.parent, delete=False) as handle:
        manifest = Path(handle.name)
        for path in ordered:
            escaped = str(path).replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    try:
        process = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", "-y", str(temporary_output)],
            capture_output=True, text=True, timeout=24 * 3600,
        )
        if process.returncode != 0 or not temporary_output.exists() or temporary_output.stat().st_size <= 0:
            message = (process.stderr or process.stdout or "FFmpeg 未生成有效文件").strip()
            raise RuntimeError(f"合并失败：{message[-500:]}")
        temporary_output.replace(output)
        stat = output.stat()
        return {"name": output.name, "path": str(output), "size": stat.st_size, "modified": stat.st_mtime}
    finally:
        manifest.unlink(missing_ok=True)
        temporary_output.unlink(missing_ok=True)


def media_audio_command(path: str | Path, ffmpeg: str | None = None) -> list[str]:
    """Build a streaming command that exposes only a recording's audio track."""
    executable = ffmpeg or shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("未找到 FFmpeg，无法播放录像音频")
    return [
        executable, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(Path(path)), "-map", "0:a:0?", "-vn", "-sn", "-dn",
        "-c:a", "libmp3lame", "-b:a", "160k", "-f", "mp3", "pipe:1",
    ]


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "other"


def _anchor_from_live_file(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return "未分组"
    parts = relative.parts
    if len(parts) >= 3 and parts[0].endswith("直播"):
        return parts[1] or "未分组"
    if len(parts) >= 2:
        return parts[-2] or "未分组"
    return "未分组"


def _anchor_from_work_file(path: Path, works_root: Path) -> str:
    try:
        relative = path.relative_to(works_root)
    except ValueError:
        return "未分组"
    if relative.parts:
        folder = relative.parts[0]
        return folder.rsplit("_", 1)[0] or folder
    return "未分组"


class MediaLibrary:
    def __init__(self, output_root: Path):
        self.output_root = output_root

    def scan(self, limit_per_anchor: int = 80) -> dict:
        root = self.output_root
        anchors: dict[str, dict] = {}
        files_by_anchor: dict[str, list[dict]] = defaultdict(list)

        for path in self._iter_media(root):
            source = "works" if "douyin_works" in path.parts else "recording"
            works_root = root / "douyin_works"
            anchor = _anchor_from_work_file(path, works_root) if source == "works" else _anchor_from_live_file(path, root)
            stat = path.stat()
            item = {
                "name": path.name,
                "path": str(path),
                "folder": str(path.parent),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "kind": _kind(path),
                "source": source,
            }
            if anchor not in anchors:
                anchors[anchor] = {
                    "anchor": anchor,
                    "folder": str(path.parent),
                    "total_files": 0,
                    "total_size": 0,
                    "latest_modified": 0,
                    "recording_count": 0,
                    "works_count": 0,
                    "video_count": 0,
                    "audio_count": 0,
                    "image_count": 0,
                }
            summary = anchors[anchor]
            summary["total_files"] += 1
            summary["total_size"] += stat.st_size
            summary["latest_modified"] = max(summary["latest_modified"], stat.st_mtime)
            summary["recording_count" if source == "recording" else "works_count"] += 1
            if item["kind"] == "video":
                summary["video_count"] += 1
            elif item["kind"] == "audio":
                summary["audio_count"] += 1
            elif item["kind"] == "image":
                summary["image_count"] += 1
            files_by_anchor[anchor].append(item)

        anchor_list = sorted(anchors.values(), key=lambda item: item["latest_modified"], reverse=True)
        for summary in anchor_list:
            anchor_files = sorted(files_by_anchor[summary["anchor"]], key=lambda item: item["modified"], reverse=True)
            summary["files"] = anchor_files[:limit_per_anchor]
            summary["recording_sessions"] = group_recordings(
                [item for item in anchor_files if item["source"] == "recording" and item["kind"] in {"video", "audio"}]
            )
        return {
            "root": str(root),
            "anchors": anchor_list,
            "total_anchors": len(anchor_list),
            "total_files": sum(item["total_files"] for item in anchor_list),
            "total_size": sum(item["total_size"] for item in anchor_list),
        }

    def _iter_media(self, root: Path):
        if not root.exists():
            return
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                yield path
