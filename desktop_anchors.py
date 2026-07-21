"""Local anchor profile store shared by recorder, interaction, works and media library."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class AnchorStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"anchors": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("anchors"), list):
                return data
        except Exception:
            pass
        return {"anchors": []}

    def _save(self, data: dict) -> None:
        _atomic_json_write(self.path, data)

    def list(self) -> list[dict]:
        with self._lock:
            anchors = self._load()["anchors"]
            anchors.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or 0, reverse=True)
            return anchors

    def add(self, name: str, profile_url: str, live_url: str = "") -> dict:
        name = name.strip()
        profile_url = profile_url.strip()
        live_url = live_url.strip().split("?")[0]
        if not profile_url:
            raise ValueError("请填写主播主页、分享链接或直播间地址")
        if live_url and "live.douyin.com/" not in live_url:
            raise ValueError("额外直播间地址必须是 live.douyin.com 链接")
        with self._lock:
            data = self._load()
            for anchor in data["anchors"]:
                if anchor.get("profile_url") == profile_url:
                    raise ValueError("该主播入口已经存在")
            now = int(time.time())
            anchor = {
                "id": uuid.uuid4().hex,
                "name": name or "未命名主播",
                "profile_url": profile_url,
                "sec_user_id": "",
                "live_url": live_url,
                "web_rid": "",
                "room_id": "",
                "default_quality": "原画",
                "output_dir": "",
                "enabled_recording": True,
                "last_live_status": "unknown",
                "last_resolved_at": None,
                "created_at": now,
                "updated_at": now,
            }
            data["anchors"].append(anchor)
            self._save(data)
            return anchor

    def update(self, anchor_id: str, updates: dict) -> dict:
        allowed = {
            "name",
            "profile_url",
            "sec_user_id",
            "live_url",
            "web_rid",
            "room_id",
            "default_quality",
            "output_dir",
            "enabled_recording",
            "last_live_status",
            "last_resolved_at",
            "last_check_error",
        }
        with self._lock:
            data = self._load()
            for anchor in data["anchors"]:
                if anchor.get("id") == anchor_id:
                    for key, value in updates.items():
                        if key in allowed:
                            anchor[key] = value
                    anchor["updated_at"] = int(time.time())
                    self._save(data)
                    return anchor
        raise IndexError("主播不存在")

    def delete(self, anchor_id: str) -> None:
        with self._lock:
            data = self._load()
            before = len(data["anchors"])
            data["anchors"] = [anchor for anchor in data["anchors"] if anchor.get("id") != anchor_id]
            if len(data["anchors"]) == before:
                raise IndexError("主播不存在")
            self._save(data)
