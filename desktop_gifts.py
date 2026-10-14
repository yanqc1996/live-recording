"""Persistent live gift ledger and conservative sound-wave estimates."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path


class GiftLedger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._context: dict = {}
        self._seen: set[str] = set()
        self._combos: dict[str, tuple[int, float]] = {}

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value.setdefault("events", [])
                value.setdefault("prices", {})
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {"events": [], "prices": {}}

    def _save(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def begin(self, anchor: dict, room_url: str) -> dict:
        with self._lock:
            now = time.time()
            self._context = {
                "session_id": uuid.uuid4().hex,
                "anchor_id": str(anchor.get("id") or ""),
                "anchor_name": str(anchor.get("name") or "未知主播"),
                "room_url": room_url,
                "started_at": now,
            }
            self._seen.clear()
            self._combos.clear()
            return dict(self._context)

    def end(self) -> None:
        with self._lock:
            if self._context:
                self._context["ended_at"] = time.time()
            self._combos.clear()

    def record(self, event: dict) -> dict | None:
        if event.get("type") != "gift":
            return None
        with self._lock:
            if not self._context:
                return None
            message_id = str(event.get("message_id") or "")
            if message_id and message_id in self._seen:
                return None
            if message_id:
                self._seen.add(message_id)
            now = float(event.get("time") or time.time())
            user = event.get("user") if isinstance(event.get("user"), dict) else {}
            gift_id = str(event.get("gift_id") or "")
            gift_name = str(event.get("gift_name") or "未知礼物")
            combo_count = max(1, int(event.get("combo_count") or 1))
            combo_key = "|".join((str(user.get("id") or user.get("sec_uid") or user.get("nickname") or "anonymous"), gift_id or gift_name))
            previous = self._combos.get(combo_key)
            quantity = combo_count
            if previous and now - previous[1] <= 20 and combo_count >= previous[0]:
                quantity = combo_count - previous[0]
            self._combos[combo_key] = (combo_count, now)
            if event.get("repeat_end"):
                self._combos.pop(combo_key, None)
            if quantity <= 0:
                return None

            data = self._load()
            price_key = gift_id or gift_name
            reported_price = max(0, int(event.get("diamond_count") or 0))
            if reported_price:
                data["prices"][price_key] = {"name": gift_name, "value": reported_price, "source": "live"}
            configured = data["prices"].get(price_key) or data["prices"].get(gift_name) or {}
            unit_value = reported_price or max(0, int(configured.get("value") or 0))
            item = {
                **self._context,
                "time": now,
                "message_id": message_id,
                "gift_id": gift_id,
                "gift_name": gift_name,
                "quantity": quantity,
                "combo_count": combo_count,
                "unit_value": unit_value,
                "sound_wave": unit_value * quantity,
                "value_known": bool(unit_value),
                "user": {
                    "id": str(user.get("id") or ""),
                    "nickname": str(user.get("nickname") or "匿名用户"),
                    "display_id": str(user.get("display_id") or ""),
                },
            }
            data["events"].append(item)
            data["events"] = data["events"][-20000:]
            self._save(data)
            return item

    def set_price(self, gift_id: str, gift_name: str, value: int) -> dict:
        if value < 0:
            raise ValueError("礼物音浪不能小于 0")
        key = str(gift_id or gift_name).strip()
        if not key:
            raise ValueError("缺少礼物标识")
        with self._lock:
            data = self._load()
            data["prices"][key] = {"name": gift_name or key, "value": int(value), "source": "manual"}
            for event in data["events"]:
                if str(event.get("gift_id") or event.get("gift_name")) == key:
                    event["unit_value"] = int(value)
                    event["sound_wave"] = int(value) * int(event.get("quantity") or 0)
                    event["value_known"] = bool(value)
            self._save(data)
            return self.stats()

    def stats(self, anchor_id: str = "", session_id: str = "") -> dict:
        with self._lock:
            data = self._load()
            if not session_id and self._context and (not anchor_id or anchor_id == self._context.get("anchor_id")):
                session_id = str(self._context.get("session_id") or "")
            events = [item for item in data["events"] if (not anchor_id or item.get("anchor_id") == anchor_id) and (not session_id or item.get("session_id") == session_id)]
            gifts: dict[str, dict] = {}
            users: dict[str, dict] = {}
            for item in events:
                gift_key = str(item.get("gift_id") or item.get("gift_name"))
                gift = gifts.setdefault(gift_key, {"gift_id": item.get("gift_id"), "name": item.get("gift_name"), "quantity": 0, "sound_wave": 0, "value_known": True, "unit_value": item.get("unit_value") or 0})
                gift["quantity"] += int(item.get("quantity") or 0)
                gift["sound_wave"] += int(item.get("sound_wave") or 0)
                gift["value_known"] = gift["value_known"] and bool(item.get("value_known"))
                user_data = item.get("user") or {}
                user_key = str(user_data.get("id") or user_data.get("nickname") or "anonymous")
                user = users.setdefault(user_key, {"id": user_data.get("id"), "nickname": user_data.get("nickname") or "匿名用户", "quantity": 0, "sound_wave": 0})
                user["quantity"] += int(item.get("quantity") or 0)
                user["sound_wave"] += int(item.get("sound_wave") or 0)
            return {
                "session_id": session_id,
                "anchor_id": anchor_id or (self._context.get("anchor_id") if self._context else ""),
                "gift_count": sum(int(item.get("quantity") or 0) for item in events),
                "event_count": len(events),
                "sound_wave": sum(int(item.get("sound_wave") or 0) for item in events),
                "unknown_count": sum(int(item.get("quantity") or 0) for item in events if not item.get("value_known")),
                "donor_count": len(users),
                "gifts": sorted(gifts.values(), key=lambda item: (item["sound_wave"], item["quantity"]), reverse=True),
                "users": sorted(users.values(), key=lambda item: (item["sound_wave"], item["quantity"]), reverse=True),
                "recent": list(reversed(events[-30:])),
            }
