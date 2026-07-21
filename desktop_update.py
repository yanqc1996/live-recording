"""Semi-automatic update checking for the desktop app."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_CONFIG = {
    "manifest_url": "",
    "last_checked_at": 0,
    "last_result": {},
}


def _safe_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("更新地址必须是 http 或 https 链接")
    return url


def _version_parts(value: str) -> list[int | str]:
    parts: list[int | str] = []
    for part in re.split(r"[.\-+_]", str(value or "").strip().lstrip("vV")):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part.lower())
    return parts


def compare_versions(left: str, right: str) -> int:
    """Return 1 if left > right, 0 if equal, -1 if left < right."""
    a = _version_parts(left)
    b = _version_parts(right)
    size = max(len(a), len(b))
    for index in range(size):
        av = a[index] if index < len(a) else 0
        bv = b[index] if index < len(b) else 0
        if av == bv:
            continue
        if isinstance(av, int) and isinstance(bv, int):
            return 1 if av > bv else -1
        return 1 if str(av) > str(bv) else -1
    return 0


class UpdateManager:
    def __init__(self, path: Path, current_version: str):
        self.path = path
        self.current_version = str(current_version or "0.0.0")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_CONFIG)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULT_CONFIG, **data}
        except Exception:
            pass
        return dict(DEFAULT_CONFIG)

    def _save(self, data: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({**DEFAULT_CONFIG, **data}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        return self._load()

    def status(self) -> dict[str, Any]:
        config = self._load()
        return {
            "current_version": self.current_version,
            "manifest_url": config.get("manifest_url", ""),
            "last_checked_at": config.get("last_checked_at", 0),
            "last_result": config.get("last_result") or {},
        }

    def save_config(self, manifest_url: str) -> dict[str, Any]:
        config = self._load()
        config["manifest_url"] = _safe_url(manifest_url)
        return self._save(config)

    def check(self, manifest_url: str = "") -> dict[str, Any]:
        config = self._load()
        url = _safe_url(manifest_url or str(config.get("manifest_url") or ""))
        if not url:
            raise ValueError("请先填写远程更新 JSON 地址")

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"Boluzhushou/{self.current_version}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                raw = response.read(1_000_000)
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"检查更新失败：{exc}") from exc

        try:
            manifest = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("远程更新文件不是有效 JSON") from exc
        if not isinstance(manifest, dict):
            raise ValueError("远程更新文件格式不正确")

        latest_version = str(manifest.get("version") or manifest.get("latest_version") or "").strip()
        download_url = _safe_url(str(manifest.get("download_url") or manifest.get("url") or "").strip())
        if not latest_version:
            raise ValueError("远程更新文件缺少 version 字段")
        if not download_url:
            raise ValueError("远程更新文件缺少 download_url 字段")

        result = {
            "ok": True,
            "has_update": compare_versions(latest_version, self.current_version) > 0,
            "current_version": self.current_version,
            "version": latest_version,
            "title": str(manifest.get("title") or f"播录助手 v{latest_version}"),
            "notes": str(manifest.get("notes") or manifest.get("changelog") or ""),
            "download_url": download_url,
            "published_at": manifest.get("published_at", ""),
            "content_type": content_type,
            "checked_at": int(time.time()),
        }
        config["manifest_url"] = url
        config["last_checked_at"] = result["checked_at"]
        config["last_result"] = result
        self._save(config)
        return {"update": self.status() | {"last_result": result}, "result": result}

    def open_download(self, url: str = "") -> dict[str, Any]:
        target = _safe_url(url)
        if not target:
            last = self.status().get("last_result") or {}
            target = _safe_url(str(last.get("download_url") or ""))
        if not target:
            raise ValueError("没有可打开的下载链接")
        webbrowser.open(target)
        return {"ok": True, "url": target}
