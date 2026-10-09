"""Local media library grouped by anchor."""

from __future__ import annotations

import re
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
            files.append({
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        files.sort(key=lambda item: item["modified"], reverse=True)
        return files[:self.limit]


def group_recordings(files: list[dict]) -> list[dict]:
    """Group recorder segments that share the same anchor and start timestamp."""
    groups: dict[str, dict] = {}
    pattern = re.compile(r"^(?P<prefix>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})_(?P<part>\d{3,})$")
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
        })
        if match:
            try:
                group["started_at"] = datetime.strptime(
                    f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H-%M-%S"
                ).timestamp()
            except ValueError:
                pass
        group["latest_modified"] = max(group["latest_modified"], float(item.get("modified") or 0))
        group["total_size"] += int(item.get("size") or 0)
        group["segment_count"] += 1
        group["formats"].add(path.suffix.lstrip(".").upper())
        group["files"].append(item)
    result = []
    for group in groups.values():
        group["files"].sort(key=lambda item: float(item.get("modified") or 0), reverse=True)
        group["path"] = group["files"][0].get("path", "")
        group["name"] = group["files"][0].get("name", "")
        group["format"] = "/".join(sorted(group.pop("formats")))
        group["duration_seconds"] = max(0, int(group["latest_modified"] - group["started_at"]))
        result.append(group)
    result.sort(key=lambda group: group["latest_modified"], reverse=True)
    return result


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
