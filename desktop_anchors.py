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
            data = self._load()
            anchors = data["anchors"]
            changed = False
            for anchor in anchors:
                if "aliases" not in anchor:
                    anchor["aliases"] = self._aliases_for(anchor)
                    changed = True
            if changed:
                self._save(data)
            anchors.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or 0, reverse=True)
            return anchors

    @staticmethod
    def _aliases_for(anchor: dict) -> dict:
        aliases = anchor.get("aliases") if isinstance(anchor.get("aliases"), dict) else {}
        fields = {
            "names": "name", "profile_urls": "profile_url", "live_urls": "live_url",
            "platform_user_ids": "platform_user_id", "sec_user_ids": "sec_user_id",
            "web_rids": "web_rid", "room_ids": "room_id",
        }
        result = {}
        for plural, singular in fields.items():
            values = [str(value).strip() for value in aliases.get(plural, []) if str(value).strip()]
            current = str(anchor.get(singular) or "").strip()
            if current:
                values.append(current)
            result[plural] = list(dict.fromkeys(values))
        return result

    @staticmethod
    def _identity_values(anchor: dict) -> set[tuple[str, str]]:
        aliases = AnchorStore._aliases_for(anchor)
        identities = set()
        for field in ("platform_user_ids", "sec_user_ids", "profile_urls"):
            for value in aliases[field]:
                normalized = value.split("?", 1)[0].strip()
                if normalized:
                    identities.add((field, normalized))
        return identities

    def find_by_identity(self, candidate: dict) -> dict | None:
        wanted = self._identity_values(candidate)
        if not wanted:
            return None
        return next((anchor for anchor in self.list() if wanted & self._identity_values(anchor)), None)

    def get(self, anchor_id: str) -> dict:
        anchor = next((item for item in self.list() if item.get("id") == anchor_id), None)
        if not anchor:
            raise IndexError("主播不存在")
        return anchor

    def find_id_by_name(self, name: str) -> str | None:
        """Resolve a recorder display name to one unambiguous canonical anchor id."""
        key = _normalized_anchor_name(name)
        if not key:
            return None
        matches = [str(item.get("id") or "") for item in self.list() if _normalized_anchor_name(item.get("name", "")) == key]
        matches = [value for value in matches if value]
        return matches[0] if len(matches) == 1 else None

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
                "platform_user_id": "",
                "live_url": live_url,
                "web_rid": "",
                "room_id": "",
                "default_quality": "原画",
                "output_dir": "",
                "enabled_recording": True,
                "anonymous_recording": False,
                "last_live_status": "unknown",
                "last_resolved_at": None,
                "created_at": now,
                "updated_at": now,
            }
            anchor["aliases"] = self._aliases_for(anchor)
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
                    "platform_user_id": "",
                    "live_url": url if "live.douyin.com/" in url else "",
                    "web_rid": "",
                    "room_id": "",
                    "default_quality": "原画",
                    "output_dir": "",
                    "enabled_recording": bool(room.get("active", True)),
                    "anonymous_recording": False,
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
            "platform_user_id",
            "live_url",
            "web_rid",
            "room_id",
            "default_quality",
            "output_dir",
            "enabled_recording",
            "anonymous_recording",
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
            for key in ("platform_user_id", "sec_user_id", "web_rid", "room_id", "output_dir"):
                if key in cleaned:
                    cleaned[key] = str(cleaned[key] or "").strip()
            for anchor in data["anchors"]:
                if anchor.get("id") == anchor_id:
                    previous = dict(anchor)
                    anchor.update(cleaned)
                    aliases = self._aliases_for(previous)
                    current_aliases = self._aliases_for(anchor)
                    anchor["aliases"] = {
                        key: list(dict.fromkeys(aliases.get(key, []) + current_aliases.get(key, [])))
                        for key in current_aliases
                    }
                    anchor["updated_at"] = int(time.time())
                    self._save(data)
                    return anchor
        raise IndexError("主播不存在")

    def merge(self, primary_id: str, duplicate_ids: list[str]) -> dict:
        """Merge duplicate profiles while retaining the primary UUID and all known aliases."""
        duplicate_ids = [str(value) for value in duplicate_ids if str(value) and str(value) != primary_id]
        with self._lock:
            data = self._load()
            primary = next((item for item in data["anchors"] if item.get("id") == primary_id), None)
            duplicates = [item for item in data["anchors"] if item.get("id") in duplicate_ids]
            if not primary:
                raise IndexError("主主播记录不存在")
            if not duplicates:
                raise ValueError("请选择需要合并的重复主播")
            aliases = self._aliases_for(primary)
            for duplicate in duplicates:
                other = self._aliases_for(duplicate)
                for key in aliases:
                    aliases[key] = list(dict.fromkeys(aliases[key] + other[key]))
                for field in ("platform_user_id", "sec_user_id", "profile_url", "live_url", "web_rid", "room_id", "output_dir"):
                    if not primary.get(field) and duplicate.get(field):
                        primary[field] = duplicate[field]
                primary["enabled_recording"] = bool(primary.get("enabled_recording", True) or duplicate.get("enabled_recording", True))
                primary["anonymous_recording"] = bool(primary.get("anonymous_recording", False) or duplicate.get("anonymous_recording", False))
                primary["created_at"] = min(primary.get("created_at") or time.time(), duplicate.get("created_at") or time.time())
            primary["aliases"] = aliases
            primary["updated_at"] = int(time.time())
            removed = {item.get("id") for item in duplicates}
            data["anchors"] = [item for item in data["anchors"] if item.get("id") not in removed]
            self._save(data)
            return primary

    def duplicate_groups(self) -> list[dict]:
        anchors = self.list()
        parent = {str(anchor["id"]): str(anchor["id"]) for anchor in anchors}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        seen: dict[tuple[str, str], str] = {}
        for anchor in anchors:
            anchor_id = str(anchor["id"])
            for identity in self._identity_values(anchor):
                if identity in seen:
                    left, right = find(anchor_id), find(seen[identity])
                    if left != right:
                        parent[left] = right
                else:
                    seen[identity] = anchor_id
        groups: dict[str, list[dict]] = {}
        for anchor in anchors:
            groups.setdefault(find(str(anchor["id"])), []).append(anchor)
        return [{"anchors": values, "reason": "相同的稳定账号标识或主页地址"} for values in groups.values() if len(values) > 1]

    def delete(self, anchor_id: str) -> None:
        with self._lock:
            data = self._load()
            before = len(data["anchors"])
            data["anchors"] = [anchor for anchor in data["anchors"] if anchor.get("id") != anchor_id]
            if len(data["anchors"]) == before:
                raise IndexError("主播不存在")
            self._save(data)
