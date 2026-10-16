"""Persistent live gift ledger and conservative sound-wave estimates."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path


# A single WebSocket gift event can contain a combo total, but room/user IDs are
# also large integers and may land in that field when Douyin changes its wire
# schema.  Treat values beyond a generous real-world combo ceiling as corrupt.
MAX_GIFT_EVENT_QUANTITY = 1_000_000


def _valid_event(item: dict) -> bool:
    if item.get("rank_snapshot"):
        return True
    try:
        quantity = int(item.get("quantity") or 0)
        combo_count = int(item.get("combo_count") or quantity)
    except (TypeError, ValueError):
        return False
    return 0 <= quantity <= MAX_GIFT_EVENT_QUANTITY and 0 <= combo_count <= MAX_GIFT_EVENT_QUANTITY


class GiftLedger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._context: dict = {}
        self._seen: set[str] = set()
        self._combos: dict[str, tuple[int, float]] = {}
        self._rank_snapshots: dict[str, dict[str, int]] = {}
        self._websocket_gift_sessions: set[str] = set()

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value.setdefault("events", [])
                value.setdefault("prices", {})
                value.setdefault("diagnostics", [])
                events = value["events"] if isinstance(value["events"], list) else []
                valid_events = [item for item in events if isinstance(item, dict) and _valid_event(item)]
                if len(valid_events) != len(events):
                    value["events"] = valid_events
                    self._save(value)
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {"events": [], "prices": {}, "diagnostics": []}

    def _save(self, value: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def begin(self, anchor: dict, room_url: str, activate: bool = True) -> dict:
        with self._lock:
            now = time.time()
            context = {
                "session_id": uuid.uuid4().hex,
                "anchor_id": str(anchor.get("id") or ""),
                "anchor_name": str(anchor.get("name") or "未知主播"),
                "room_url": room_url,
                "started_at": now,
            }
            if activate:
                self._context = context
                self._seen.clear()
                self._combos.clear()
            return dict(context)

    def end(self) -> None:
        with self._lock:
            if self._context:
                self._context["ended_at"] = time.time()
            self._combos.clear()

    def record(self, event: dict, context: dict | None = None) -> dict | None:
        if event.get("type") == "gift_schema":
            return self._record_schema(event, context)
        if event.get("type") == "gift_rank_snapshot":
            return self._record_rank_snapshot(event, context)
        if event.get("type") != "gift":
            return None
        with self._lock:
            active_context = context or self._context
            if not active_context:
                return None
            self._websocket_gift_sessions.add(str(active_context.get("session_id") or ""))
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
            if combo_count > MAX_GIFT_EVENT_QUANTITY:
                return None
            combo_key = "|".join((str(active_context.get("session_id") or ""), str(user.get("id") or user.get("sec_uid") or user.get("nickname") or "anonymous"), gift_id or gift_name))
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
                **active_context,
                "time": now,
                "message_id": message_id,
                "gift_id": gift_id,
                "gift_name": gift_name,
                "quantity": quantity,
                "combo_count": combo_count,
                "unit_value": unit_value,
                "sound_wave": unit_value * quantity,
                "value_known": bool(unit_value),
                "value_source": "platform" if reported_price else "estimated" if unit_value else "unknown",
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

    def _record_schema(self, event: dict, context: dict | None = None) -> dict | None:
        """Keep a bounded, value-free history of gift wire layouts for compatibility checks."""
        with self._lock:
            active_context = context or self._context
            if not active_context:
                return None
            data = self._load()
            diagnostics = data.setdefault("diagnostics", [])
            session_id = str(active_context.get("session_id") or "")
            fingerprint = str(event.get("schema_fingerprint") or "")
            method = str(event.get("source_method") or "")
            accepted = bool(event.get("accepted"))
            existing = next((item for item in reversed(diagnostics) if
                item.get("session_id") == session_id
                and item.get("fingerprint") == fingerprint
                and item.get("method") == method
                and bool(item.get("accepted")) == accepted), None)
            now = float(event.get("time") or time.time())
            if existing:
                existing["last_seen"] = now
                existing["count"] = int(existing.get("count") or 1) + 1
            else:
                diagnostics.append({
                    "session_id": session_id,
                    "anchor_id": str(active_context.get("anchor_id") or ""),
                    "anchor_name": str(active_context.get("anchor_name") or ""),
                    "method": method,
                    "fingerprint": fingerprint,
                    "schema": event.get("schema") if isinstance(event.get("schema"), dict) else {},
                    "accepted": accepted,
                    "gift_name_resolved": bool(event.get("gift_name_resolved")),
                    "user_resolved": bool(event.get("user_resolved")),
                    "first_seen": now,
                    "last_seen": now,
                    "count": 1,
                })
            data["diagnostics"] = diagnostics[-50:]
            self._save(data)
            return diagnostics[-1] if diagnostics else None

    def _record_rank_snapshot(self, event: dict, context: dict | None = None) -> dict | None:
        """Persist contribution-rank deltas when anonymous WebSocket omits gift messages."""
        with self._lock:
            active_context = context or self._context
            session_id = str(active_context.get("session_id") or "") if active_context else ""
            if not active_context or not session_id or session_id in self._websocket_gift_sessions:
                return None
            ranks = event.get("ranks") if isinstance(event.get("ranks"), list) else []
            previous = self._rank_snapshots.get(session_id, {})
            current: dict[str, int] = {}
            data = self._load()
            added = 0
            now = float(event.get("time") or time.time())
            for rank in ranks:
                user = rank.get("user") if isinstance(rank.get("user"), dict) else {}
                user_id = str(user.get("id") or user.get("sec_uid") or user.get("nickname") or "anonymous")
                contribution = max(0, int(rank.get("contribution") or 0))
                current[user_id] = contribution
                delta = max(0, contribution - int(previous.get(user_id) or 0))
                if not delta:
                    continue
                data["events"].append({
                    **active_context, "time": now, "message_id": f"rank:{session_id}:{user_id}:{contribution}",
                    "gift_id": "rank-contribution", "gift_name": "贡献榜音浪", "quantity": 0,
                    "combo_count": 0, "unit_value": delta, "sound_wave": delta, "value_known": True,
                    "value_source": "rank", "rank_snapshot": True,
                    "user": {"id": str(user.get("id") or ""), "nickname": str(user.get("nickname") or "匿名用户"), "display_id": str(user.get("display_id") or "")},
                })
                added += delta
            self._rank_snapshots[session_id] = current
            if added:
                data["events"] = data["events"][-20000:]
                self._save(data)
            return {"source": "rank", "sound_wave": added} if added else None

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
                if str(event.get("gift_id") or event.get("gift_name")) == key and event.get("value_source") != "platform":
                    event["unit_value"] = int(value)
                    event["sound_wave"] = int(value) * int(event.get("quantity") or 0)
                    event["value_known"] = bool(value)
                    event["value_source"] = "estimated" if value else "unknown"
            self._save(data)
            return self.stats()

    def remap_anchor(self, old_ids: list[str], new_id: str, new_name: str) -> int:
        """Move historical gift events to a surviving canonical anchor identity."""
        old_ids = {str(value) for value in old_ids if str(value)}
        if not old_ids:
            return 0
        with self._lock:
            data = self._load()
            changed = 0
            for event in data["events"]:
                if str(event.get("anchor_id") or "") in old_ids:
                    event["anchor_id"] = new_id
                    event["anchor_name"] = new_name
                    changed += 1
            if changed:
                self._save(data)
            return changed

    def stats(self, anchor_id: str = "", session_id: str = "", anchor_name: str = "", started_at: float = 0, ended_at: float = 0) -> dict:
        with self._lock:
            data = self._load()
            if not session_id and not anchor_name and not started_at and not ended_at and self._context and (not anchor_id or anchor_id == self._context.get("anchor_id")):
                session_id = str(self._context.get("session_id") or "")
            events = [item for item in data["events"] if
                (not anchor_id or item.get("anchor_id") == anchor_id)
                and (not anchor_name or item.get("anchor_name") == anchor_name)
                and (not session_id or item.get("session_id") == session_id)
                and (not started_at or float(item.get("time") or 0) >= started_at)
                and (not ended_at or float(item.get("time") or 0) <= ended_at)
            ]
            gifts: dict[str, dict] = {}
            users: dict[str, dict] = {}
            for item in events:
                if not item.get("rank_snapshot"):
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
                "rank_sound_wave": sum(int(item.get("sound_wave") or 0) for item in events if item.get("rank_snapshot")),
                "platform_count": sum(int(item.get("quantity") or 0) for item in events if item.get("value_source") == "platform"),
                "estimated_count": sum(int(item.get("quantity") or 0) for item in events if item.get("value_source") == "estimated"),
                "unknown_count": sum(int(item.get("quantity") or 0) for item in events if not item.get("value_known")),
                "coverage_percent": round(100 * sum(int(item.get("quantity") or 0) for item in events if item.get("value_known")) / max(1, sum(int(item.get("quantity") or 0) for item in events))),
                "donor_count": len(users),
                "gifts": sorted(gifts.values(), key=lambda item: (item["sound_wave"], item["quantity"]), reverse=True),
                "users": sorted(users.values(), key=lambda item: (item["sound_wave"], item["quantity"]), reverse=True),
                "recent": list(reversed(events[-30:])),
                "schema_samples": list(reversed(data.get("diagnostics", [])[-10:])),
            }
