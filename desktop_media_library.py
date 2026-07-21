"""Local media library grouped by anchor."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


MEDIA_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".ts", ".mp4", ".mkv", ".flv"}
AUDIO_EXTENSIONS = {".mp3", ".m4a"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


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
