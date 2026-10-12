"""Local anchor profile store shared by recorder, interaction, works and media library."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import urlparse


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _normalized_anchor_name(value: str) -> str:
    """Normalize display-name decoration for conservative legacy deduplication."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


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

    def get(self, anchor_id: str) -> dict:
        anchor = next((item for item in self.list() if item.get("id") == anchor_id), None)
        if not anchor:
            raise IndexError("主播不存在")
        return anchor

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

    def import_rooms(self, rooms: list[dict]) -> int:
        """Import legacy recorder entries without duplicating known URLs."""
        imported = 0
        changed = False
        with self._lock:
            data = self._load()
            known = {}
            known_names = {}
            for anchor in data["anchors"]:
                for key in ("profile_url", "live_url"):
                    value = str(anchor.get(key) or "").strip().split("?")[0]
                    if value:
                        known[value] = anchor
                normalized_name = _normalized_anchor_name(anchor.get("name", ""))
                if normalized_name:
                    known_names[normalized_name] = anchor
            now = int(time.time())
            for room in rooms:
                value = str(room.get("value") or "")
                match = re.search(r"https?://[^\s,，]+", value)
                if not match:
                    continue
                url = match.group(0).split("?")[0]
                name_match = re.search(r"主播\s*[:：]\s*([^,，]+)", value)
                imported_name = name_match.group(1).strip() if name_match else ""
                name_key = _normalized_anchor_name(imported_name)
                if url in known:
                    active = bool(room.get("active", True))
                    if known[url].get("enabled_recording", True) != active:
                        known[url]["enabled_recording"] = active
                        known[url]["updated_at"] = now
                        changed = True
                    continue
                if name_key and name_key in known_names:
                    # A legacy room URL can become stale while the canonical profile
                    # already contains the same decorated display name and a newer URL.
                    continue
                fallback = urlparse(url).netloc or "未命名主播"
                data["anchors"].append({
                    "id": uuid.uuid4().hex,
                    "name": imported_name or fallback,
                    "profile_url": url,
                    "sec_user_id": "",
                    "live_url": url if "live.douyin.com/" in url else "",
                    "web_rid": "",
                    "room_id": "",
                    "default_quality": "原画",
                    "output_dir": "",
                    "enabled_recording": bool(room.get("active", True)),
                    "last_live_status": "unknown",
                    "last_resolved_at": None,
                    "created_at": now,
                    "updated_at": now,
                })
                known[url] = data["anchors"][-1]
                if name_key:
                    known_names[name_key] = data["anchors"][-1]
                imported += 1
            if imported or changed:
                self._save(data)
        return imported

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
            cleaned = {key: value for key, value in updates.items() if key in allowed}
            if "name" in cleaned:
                cleaned["name"] = str(cleaned["name"] or "").strip() or "未命名主播"
            if "profile_url" in cleaned:
                cleaned["profile_url"] = str(cleaned["profile_url"] or "").strip()
                if not cleaned["profile_url"]:
                    raise ValueError("主播主页、分享链接或直播间地址不能为空")
                if any(
                    anchor.get("id") != anchor_id and anchor.get("profile_url") == cleaned["profile_url"]
                    for anchor in data["anchors"]
                ):
                    raise ValueError("该主播入口已经存在")
            if "live_url" in cleaned:
                cleaned["live_url"] = str(cleaned["live_url"] or "").strip().split("?")[0]
                if cleaned["live_url"] and "live.douyin.com/" not in cleaned["live_url"]:
                    raise ValueError("直播间地址必须是 live.douyin.com 链接")
            for key in ("sec_user_id", "web_rid", "room_id", "output_dir"):
                if key in cleaned:
                    cleaned[key] = str(cleaned[key] or "").strip()
            for anchor in data["anchors"]:
                if anchor.get("id") == anchor_id:
                    anchor.update(cleaned)
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
