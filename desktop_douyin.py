"""Douyin live interaction helpers for the desktop app."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import base64
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import execjs
import requests
from bs4 import BeautifulSoup
from websocket import WebSocketApp

from douyin_static import Live_pb2


DOUYIN_LIVE_ORIGIN = "https://live.douyin.com"
DOUYIN_WEB_ORIGIN = "https://www.douyin.com"
LOGIN_COOKIE_NAMES = {"LOGIN_STATUS", "sessionid", "sessionid_ss", "sid_guard"}
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
MAX_GIFT_COMBO_COUNT = 1_000_000


def _protobuf_wire_fields(payload: bytes) -> dict[int, list[object]]:
    """Read the small protobuf subset needed for extra gift metadata."""
    fields: dict[int, list[object]] = {}
    offset = 0

    def read_varint(position: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while position < len(payload) and shift < 70:
            byte = payload[position]
            position += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, position
            shift += 7
        raise ValueError("invalid protobuf varint")

    while offset < len(payload):
        key, offset = read_varint(offset)
        number, wire_type = key >> 3, key & 7
        if not number:
            break
        if wire_type == 0:
            value, offset = read_varint(offset)
        elif wire_type == 1:
            value, offset = payload[offset:offset + 8], offset + 8
        elif wire_type == 2:
            size, offset = read_varint(offset)
            value, offset = payload[offset:offset + size], offset + size
        elif wire_type == 5:
            value, offset = payload[offset:offset + 4], offset + 4
        else:
            break
        fields.setdefault(number, []).append(value)
    return fields


def _protobuf_wire_shape(payload: bytes, nested_fields: tuple[int, ...] = (15,)) -> dict:
    """Describe protobuf layout without retaining message values or user content."""
    try:
        fields = _protobuf_wire_fields(payload)
    except (TypeError, ValueError, IndexError):
        return {"parse_error": True, "bytes": len(payload)}
    shape: dict[str, list[dict]] = {}
    for number, values in fields.items():
        samples = []
        for value in values[:3]:
            if isinstance(value, bytes):
                sample = {"kind": "bytes", "length": len(value)}
                if number in nested_fields and value:
                    sample["nested"] = _protobuf_wire_shape(value, ())
            else:
                sample = {"kind": "varint", "range": "large" if int(value) > MAX_GIFT_COMBO_COUNT else "small"}
            samples.append(sample)
        shape[str(number)] = samples
    return {"bytes": len(payload), "fields": shape}


def _gift_wire_metadata(payload: bytes) -> dict:
    try:
        fields = _protobuf_wire_fields(payload)
        gift_payload = next((value for value in fields.get(15, []) if isinstance(value, bytes)), b"")
        gift_fields = _protobuf_wire_fields(gift_payload) if gift_payload else {}
        name_value = next((value for value in gift_fields.get(16, []) if isinstance(value, bytes)), b"")
        gift_id_value = next(iter(fields.get(2, [])), "")
        if isinstance(gift_id_value, bytes):
            gift_id_value = gift_id_value.decode("utf-8", errors="ignore")
        return {
            "gift_id": str(gift_id_value or next(iter(gift_fields.get(5, [])), "")),
            "gift_name": name_value.decode("utf-8", errors="ignore"),
            "repeat_count": int(next(iter(fields.get(5, [])), 0) or 0),
            "combo_count": int(next(iter(fields.get(6, [])), 0) or 0),
            "repeat_end": bool(next(iter(fields.get(9, [])), 0)),
            "diamond_count": int(next(iter(gift_fields.get(12, [])), 0) or 0),
        }
    except (TypeError, ValueError, IndexError):
        return {}


def _gift_combo_count(*values: object) -> int | None:
    """Choose a plausible combo count and reject schema-mismatched identifiers."""
    candidates = []
    for value in values:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            continue
        if parsed:
            candidates.append(parsed)
    plausible = [value for value in candidates if 0 < value <= MAX_GIFT_COMBO_COUNT]
    if plausible:
        return plausible[0]
    return None if candidates else 1


def _audio_relay_command(ffmpeg: str, source_url: str) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_at_eof",
        "1",
        "-reconnect_delay_max",
        "5",
        "-rw_timeout",
        "15000000",
        "-user_agent",
        UA,
        "-headers",
        f"Referer: {DOUYIN_LIVE_ORIGIN}/\r\n",
        "-i",
        source_url,
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
    ]


def _asset_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def _compile_js(filename: str):
    root = _asset_root()
    candidates = [root / "douyin_static" / filename, Path(__file__).resolve().parent / "douyin_static" / filename]
    for candidate in candidates:
        if candidate.exists():
            return execjs.compile(candidate.read_text(encoding="utf-8"), cwd=str(root / "node_modules"))
    raise FileNotFoundError(f"缺少抖音签名脚本：{filename}")


_live_sign_js = None
_ab_js = None


def _live_signature(room_id: str, user_unique_id: str) -> str:
    global _live_sign_js
    if _live_sign_js is None:
        _live_sign_js = _compile_js("dy_live_sign.js")
    raw = (
        "live_id=1,aid=6383,version_code=180800,webcast_sdk_version=1.0.15,"
        f"room_id={room_id},sub_room_id=,sub_channel_id=,did_rule=3,"
        f"user_unique_id={user_unique_id},device_platform=web,device_type=,ac=,identity=audience"
    )
    stub = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return _live_sign_js.call("get_signature", stub).get("X-Bogus", "")


def _a_bogus(params: dict, data: dict | None = None) -> str:
    global _ab_js
    if _ab_js is None:
        _ab_js = _compile_js("dy_ab.js")
    query = urllib.parse.urlencode(params)
    payload = urllib.parse.urlencode(data or {})
    return _ab_js.call("get_ab", query, payload)


def _req_sign(payload: dict, private_key: str) -> str:
    global _ab_js
    if _ab_js is None:
        _ab_js = _compile_js("dy_ab.js")
    return _ab_js.call("get_req_sign", payload, private_key)


def _ree_key(private_key: str) -> str:
    global _ab_js
    if _ab_js is None:
        _ab_js = _compile_js("dy_ab.js")
    return _ab_js.call("get_ree_key", private_key)


def _bd_ticket_client_data(api: str, security: "DouyinSecurity") -> str:
    timestamp = int(time.time())
    sign_data = f"ticket={security.ticket}&path={api}&timestamp={timestamp}"
    payload = {
        "ts_sign": security.ts_sign,
        "req_content": "ticket,path,timestamp",
        "req_sign": _req_sign(sign_data, security.private_key),
        "timestamp": timestamp,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _parse_cookie(cookie: str) -> dict[str, str]:
    result = {}
    for item in cookie.split(";"):
        if "=" not in item:
            continue
        key, value = item.strip().split("=", 1)
        if key:
            result[key] = value
    return result


def _cookie_string(cookies: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def _ms_token(cookies: dict[str, str]) -> str:
    if cookies.get("msToken"):
        return cookies["msToken"]
    alphabet = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    token = "".join(random.choice(alphabet) for _ in range(107))
    cookies["msToken"] = token
    return token


def _csrf_token(cookie_str: str) -> str:
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "cache-control": "no-cache",
        "cookie": cookie_str,
        "pragma": "no-cache",
        "referer": f"{DOUYIN_WEB_ORIGIN}/?recommend=1",
        "user-agent": UA,
        "x-secsdk-csrf-request": "1",
        "x-secsdk-csrf-version": "1.2.22",
    }
    response = requests.head(
        f"{DOUYIN_WEB_ORIGIN}/service/2/abtest_config/",
        headers=headers,
        timeout=12,
        verify=False,
    )
    raw = response.headers.get("X-Ware-Csrf-Token", "")
    parts = raw.split(",")
    return parts[1] if len(parts) > 1 else ""


def _room_web_rid(value: str) -> str:
    match = re.search(r"live\.douyin\.com/([^/?#\s,，]+)", value)
    if not match:
        raise ValueError("请输入 live.douyin.com 直播间地址")
    return match.group(1)


def _is_live_status(value) -> bool:
    try:
        return int(value) == 2
    except (TypeError, ValueError):
        return False


def _room_url_from_data(data: dict, fallback_url: str = "") -> str:
    web_rid = (
        data.get("web_rid")
        or data.get("owner", {}).get("web_rid")
        or data.get("room", {}).get("owner", {}).get("web_rid")
    )
    if web_rid:
        return f"{DOUYIN_LIVE_ORIGIN}/{web_rid}"
    if "live.douyin.com/" in fallback_url:
        return fallback_url.split("?")[0]
    return ""


def _sec_user_id(value: str) -> str:
    for pattern in (
        r"/user/([A-Za-z0-9_.\-]+)",
        r"sec_user_id=([A-Za-z0-9_.\-]+)",
        r"(MS4wLjAB[A-Za-z0-9_-]+)",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def extract_douyin_share_url(value: str) -> str:
    """Extract the actionable Douyin URL from a full mobile share message."""
    value = str(value or "").strip()
    urls = re.findall(r"https?://[^\s<>\"'，。；：！？、）]+", value)
    for url in urls:
        cleaned = url.rstrip(".,;:!?，。；：！？、）)]}")
        if any(host in cleaned.lower() for host in ("douyin.com", "iesdouyin.com")):
            return cleaned
    return value


def _nested_value(value, key: str):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ""
    if isinstance(value, dict):
        if value.get(key):
            return value[key]
        for child in value.values():
            result = _nested_value(child, key)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _nested_value(child, key)
            if result:
                return result
    return ""


def _resolve_profile_live_room(auth: "DouyinAuthState", value: str) -> dict:
    sec_user_id = _sec_user_id(value)
    if not sec_user_id:
        raise ValueError("无法从主页识别 sec_user_id")
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "sec_user_id": sec_user_id,
        "from_user_page": "1",
    }
    response = requests.get(
        f"{DOUYIN_WEB_ORIGIN}/aweme/v1/web/user/profile/other/",
        params=params,
        headers={
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": value if value.startswith("http") else f"{DOUYIN_WEB_ORIGIN}/",
            "user-agent": UA,
        },
        cookies=auth.cookie,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status_code") not in (None, 0):
        raise RuntimeError(payload.get("status_msg") or "抖音用户资料接口返回异常")
    user = payload.get("user") or {}
    if not user:
        raise RuntimeError("抖音用户资料接口未返回主播信息")

    room_data = user.get("room_data") or {}
    web_rid = str(
        _nested_value(room_data, "web_rid")
        or user.get("unique_id")
        or (user.get("short_id") if str(user.get("short_id") or "") != "0" else "")
        or ""
    )
    room_id = str(user.get("room_id_str") or user.get("room_id") or _nested_value(room_data, "id_str") or "")
    if room_id == "0":
        room_id = ""
    is_live = str(user.get("live_status")) in {"1", "2"}
    room_url = f"{DOUYIN_LIVE_ORIGIN}/{web_rid}" if web_rid else ""
    return {
        "input_type": "user_profile",
        "is_live": is_live,
        "room_url": room_url,
        "web_rid": web_rid,
        "room_id": room_id,
        "anchor_id": str(user.get("uid") or ""),
        "sec_anchor_id": str(user.get("sec_uid") or sec_user_id),
        "nickname": str(user.get("nickname") or ""),
        "title": str(_nested_value(room_data, "title") or ""),
        "message": "已解析到直播间地址" if is_live else "已解析到直播间地址（当前未开播）",
    }


def _avatar_url(user: dict) -> str:
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        avatar = user.get(key) or {}
        urls = avatar.get("url_list") if isinstance(avatar, dict) else []
        if urls:
            return str(urls[0])
    return ""


def _normalize_user_search_results(payload: dict, limit: int = 12) -> list[dict]:
    """Collect user records from the response's version-dependent nesting."""
    results: list[dict] = []
    seen: set[str] = set()

    def visit(value) -> None:
        if len(results) >= limit:
            return
        if isinstance(value, list):
            for child in value:
                visit(child)
            return
        if not isinstance(value, dict):
            return
        user = value.get("user_info") or value.get("user")
        if not isinstance(user, dict):
            user = value
        sec_uid = str(user.get("sec_uid") or user.get("sec_user_id") or "").strip()
        nickname = str(user.get("nickname") or user.get("nick_name") or "").strip()
        if sec_uid and nickname and sec_uid not in seen:
            seen.add(sec_uid)
            unique_id = str(user.get("unique_id") or "").strip()
            short_id = str(user.get("short_id") or "").strip()
            display_id = unique_id or (short_id if short_id != "0" else "")
            follower_count = user.get("follower_count")
            try:
                follower_count = int(follower_count) if follower_count is not None else None
            except (TypeError, ValueError):
                follower_count = None
            results.append({
                "nickname": nickname,
                "display_id": display_id,
                "sec_user_id": sec_uid,
                "profile_url": f"{DOUYIN_WEB_ORIGIN}/user/{sec_uid}",
                "avatar_url": _avatar_url(user),
                "signature": str(user.get("signature") or user.get("signature_extra") or "").strip(),
                "follower_count": follower_count,
                "is_live": str(user.get("live_status") or "") in {"1", "2"},
            })
        for child in value.values():
            if child is not user:
                visit(child)

    visit(payload)
    return results


def search_douyin_users(auth: "DouyinAuthState", keyword: str, limit: int = 12) -> list[dict]:
    keyword = str(keyword or "").strip()
    if not keyword:
        raise ValueError("请输入主播昵称或抖音号")
    if len(keyword) > 60:
        raise ValueError("搜索内容过长，请输入主播昵称或抖音号")
    limit = max(1, min(int(limit or 12), 20))
    params = {
        "device_platform": "webapp", "aid": "6383", "channel": "channel_pc_web",
        "search_channel": "aweme_user_web", "keyword": keyword,
        "search_source": "normal_search", "query_correct_type": "1",
        "is_filter_search": "0", "offset": "0", "count": str(limit),
        "need_filter_settings": "1", "list_type": "single", "pc_client_type": "1",
        "cookie_enabled": "true", "browser_language": "zh-CN",
        "browser_platform": "MacIntel", "browser_name": "Chrome",
        "screen_width": "1920", "screen_height": "1080", "msToken": _ms_token(auth.cookie),
    }
    try:
        params["a_bogus"] = _a_bogus(params)
    except Exception:
        pass
    response = requests.get(
        f"{DOUYIN_WEB_ORIGIN}/aweme/v1/web/general/search/single/",
        params=params,
        headers={
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": f"{DOUYIN_WEB_ORIGIN}/search/{urllib.parse.quote(keyword)}?type=user",
            "user-agent": UA,
        },
        cookies=auth.cookie,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status_code") not in (None, 0):
        raise RuntimeError(payload.get("status_msg") or "抖音搜索接口返回异常")
    return _normalize_user_search_results(payload, limit)


@dataclass
class DouyinSecurity:
    ticket: str = ""
    ts_sign: str = ""
    private_key: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.ticket and self.ts_sign and self.private_key)


@dataclass
class DouyinAuthState:
    cookie: dict[str, str] = field(default_factory=dict)
    cookie_str: str = ""
    security: DouyinSecurity = field(default_factory=DouyinSecurity)

    @classmethod
    def from_cookie(cls, cookie: str, security: dict | None = None) -> "DouyinAuthState":
        cookies = _parse_cookie(cookie)
        _ms_token(cookies)
        cookies.setdefault("xgplayer_user_id", str(random.randint(10**18, 10**19 - 1)))
        security = security or {}
        return cls(
            cookie=cookies,
            cookie_str=_cookie_string(cookies),
            security=DouyinSecurity(
                ticket=str(security.get("ticket", "")),
                ts_sign=str(security.get("ts_sign", "")),
                private_key=str(security.get("private_key", "")),
            ),
        )

    @property
    def connected(self) -> bool:
        return any(self.cookie.get(name) not in {None, "", "0"} for name in LOGIN_COOKIE_NAMES)

    @property
    def access_mode(self) -> str:
        return "authenticated" if self.connected else "anonymous"

    def update_cookies(self, cookies: dict[str, str]) -> None:
        for name, value in cookies.items():
            if name and value:
                self.cookie[str(name)] = str(value)
        _ms_token(self.cookie)
        self.cookie.setdefault("xgplayer_user_id", str(random.randint(10**18, 10**19 - 1)))
        self.cookie_str = _cookie_string(self.cookie)


@dataclass
class LiveRoomInfo:
    web_rid: str
    room_id: str
    user_id: str
    title: str
    status: str
    anchor_id: str = ""
    sec_anchor_id: str = ""
    ttwid: str = ""


def fetch_live_room_info(auth: DouyinAuthState, room_url: str) -> LiveRoomInfo:
    web_rid = _room_web_rid(room_url)
    url = f"{DOUYIN_LIVE_ORIGIN}/{web_rid}"
    response = requests.get(
        url,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "cache-control": "no-cache",
            "referer": f"{DOUYIN_LIVE_ORIGIN}/?from_nav=1",
            "user-agent": UA,
        },
        cookies=auth.cookie,
        timeout=15,
        verify=False,
    )
    auth.update_cookies(response.cookies.get_dict())
    soup = BeautifulSoup(response.text, "html.parser")
    for script_tag in soup.select("script"):
        script = script_tag.string or ""
        if "roomId" not in script:
            continue
        try:
            room_match = re.search(
                r'\\"roomInfo\\":\{\\"room\\":\{\\"id_str\\":\\"(\d+)\\",'
                r'.*?\\"status\\":(\d+).*?\\"title\\":\\"(.*?)\\"',
                script,
            )
            if not room_match:
                continue
            room_id, status, title = room_match.groups()
            user_match = re.search(r'\\"user_unique_id\\":\\"(\d+)\\"', script)
            user_id = user_match.group(1) if user_match else str(auth.cookie.get("xgplayer_user_id") or "")
            anchor_id = ""
            sec_anchor_id = ""
            owner_match = re.search(
                r'\\"(?:owner|anchor)\\":\{.*?\\"id_str\\":\\"(\d+)\\".*?'
                r'\\"sec_uid\\":\\"([^"]+)\\"',
                script,
            )
            if owner_match:
                anchor_id, sec_anchor_id = owner_match.groups()
            if not anchor_id:
                anchor_match = re.search(r'\\"anchor_id\\":\\"?(\d+)\\"?', script)
                anchor_id = anchor_match.group(1) if anchor_match else ""
            if not sec_anchor_id:
                sec_match = re.search(r'\\"sec_uid\\":\\"(MS4wLjAB[^"\\]+)\\"', script)
                sec_anchor_id = sec_match.group(1) if sec_match else ""
            return LiveRoomInfo(
                web_rid=web_rid,
                room_id=room_id,
                user_id=user_id or anchor_id,
                title=title,
                status=status,
                anchor_id=anchor_id,
                sec_anchor_id=sec_anchor_id,
                ttwid=response.cookies.get_dict().get("ttwid", ""),
            )
        except (IndexError, ValueError):
            continue
    raise RuntimeError("无法解析直播间信息，可能未开播、链接不正确或触发了抖音风控")


def fetch_initial_live_response(auth: DouyinAuthState, info: LiveRoomInfo) -> Live_pb2.LiveResponse:
    params = {
        "resp_content_type": "protobuf",
        "did_rule": "3",
        "device_id": "",
        "app_name": "douyin_web",
        "endpoint": "live_pc",
        "support_wrds": "1",
        "user_unique_id": info.user_id,
        "identity": "audience",
        "need_persist_msg_count": "15",
        "insert_task_id": "",
        "live_reason": "",
        "room_id": info.room_id,
        "version_code": "180800",
        "last_rtt": "0",
        "live_id": "1",
        "aid": "6383",
        "fetch_rule": "1",
        "cursor": "",
        "internal_ext": "",
        "device_platform": "web",
        "cookie_enabled": "true",
        "screen_width": "2560",
        "screen_height": "1440",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Mozilla",
        "browser_version": UA.split("Mozilla/")[-1],
        "browser_online": "true",
        "tz_name": "Asia/Shanghai",
        "msToken": _ms_token(auth.cookie),
    }
    params["a_bogus"] = _a_bogus(params)
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "origin": DOUYIN_LIVE_ORIGIN,
        "referer": f"{DOUYIN_LIVE_ORIGIN}/{info.web_rid}",
        "user-agent": UA,
        "x-secsdk-csrf-token": _csrf_token(auth.cookie_str),
    }
    response = requests.get(
        f"{DOUYIN_LIVE_ORIGIN}/webcast/im/fetch/",
        headers=headers,
        params=params,
        cookies=auth.cookie,
        timeout=15,
        verify=False,
    )
    response.raise_for_status()
    live_response = Live_pb2.LiveResponse()
    live_response.ParseFromString(response.content)
    return live_response


def _decode_live_response(frame) -> Live_pb2.LiveResponse:
    """Decode a webcast push payload without assuming every frame is gzipped."""
    payload = bytes(frame.payload)
    if not payload:
        raise ValueError("直播间返回了空消息")

    encoding = str(frame.payloadEncoding or "").strip().lower()
    is_gzip = payload.startswith(b"\x1f\x8b")
    if is_gzip or "gzip" in encoding:
        try:
            payload = gzip.decompress(payload)
        except (EOFError, OSError):
            # Some gateways have already decompressed the payload but leave the
            # original payloadEncoding metadata on the frame.
            if is_gzip:
                raise

    live_response = Live_pb2.LiveResponse()
    live_response.ParseFromString(payload)
    return live_response


def _user_to_dict(user) -> dict:
    return {
        "id": str(getattr(user, "id", "")),
        "sec_uid": getattr(user, "sec_uid", ""),
        "nickname": getattr(user, "nickname", "") or "匿名用户",
        "display_id": getattr(user, "display_id", ""),
        "level": getattr(user, "level", 0),
    }


def _first_url(value) -> str:
    if isinstance(value, dict):
        urls = value.get("url_list") or value.get("urlList") or []
        if isinstance(urls, list) and urls:
            return str(urls[0])
        for key in ("uri", "url"):
            if value.get(key):
                return str(value[key])
    return ""


def _pick_rank_entries(payload: dict) -> list:
    candidates = []
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                if key in {"ranks", "rank_list", "ranklist", "audience_list", "user_list", "list"} and isinstance(value, list):
                    candidates.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            for value in item:
                if isinstance(value, (dict, list)):
                    stack.append(value)
    return max(candidates, key=len, default=[])


def _rank_value(entry: dict) -> str:
    for key in (
        "score",
        "rank_score",
        "rankScore",
        "diamond_count",
        "diamondCount",
        "contribution",
        "coin_count",
        "coinCount",
        "value",
        "display_score",
        "displayScore",
        "gap_description",
        "gapDescription",
    ):
        value = entry.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalize_rank_entry(entry: dict, fallback_rank: int) -> dict:
    user = entry.get("user") or entry.get("user_info") or entry.get("userInfo") or entry
    avatar = (
        _first_url(user.get("avatar_thumb") or user.get("avatarThumb") or {})
        or _first_url(user.get("avatar_medium") or user.get("avatarMedium") or {})
        or _first_url(user.get("avatar") or {})
    )
    try:
        rank = int(entry.get("rank") or entry.get("rank_index") or entry.get("rankIndex") or fallback_rank)
    except (TypeError, ValueError):
        rank = fallback_rank
    return {
        "rank": rank,
        "user": {
            "id": str(user.get("id") or user.get("id_str") or user.get("idStr") or user.get("user_id") or ""),
            "sec_uid": user.get("sec_uid") or user.get("secUid") or "",
            "nickname": user.get("nickname") or user.get("nick_name") or user.get("display_id") or "匿名用户",
            "display_id": user.get("display_id") or user.get("unique_id") or "",
            "avatar": avatar,
        },
        "contribution": _rank_value(entry),
        "raw": entry,
    }


def fetch_gift_rank(auth: DouyinAuthState, room_url: str) -> dict:
    info = fetch_live_room_info(auth, room_url)
    params = {
        "aid": "6383",
        "app_name": "douyin_web",
        "live_id": "1",
        "device_platform": "web",
        "language": "zh-CN",
        "enter_from": "web_live",
        "cookie_enabled": "true",
        "screen_width": "2560",
        "screen_height": "1600",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "138.0.0.0",
        "webcast_sdk_version": "2450",
        "room_id": info.room_id,
        "ignoreToast": "true",
        "rank_type": "30",
        "update_scene": "rank_message",
        "msToken": _ms_token(auth.cookie),
    }
    if info.anchor_id:
        params["anchor_id"] = info.anchor_id
    if info.sec_anchor_id:
        params["sec_anchor_id"] = info.sec_anchor_id
    params["a_bogus"] = _a_bogus(params)
    response = requests.get(
        f"{DOUYIN_LIVE_ORIGIN}/webcast/ranklist/audience/",
        headers={
            "accept": "application/json, text/plain, */*",
            "referer": f"{DOUYIN_LIVE_ORIGIN}/{info.web_rid}",
            "user-agent": UA,
        },
        params=params,
        cookies=auth.cookie,
        timeout=15,
        verify=False,
    )
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200:
        return {
            "room": info.__dict__,
            "updated_at": time.time(),
            "ranks": [],
            "total": 0,
            "raw_status": response.status_code,
            "raw_message": f"礼物榜接口暂不可用（HTTP {response.status_code}），可能未开播、匿名访问受限、登录失效或接口被风控",
        }
    text_preview = (response.text or "").strip()[:200]
    try:
        payload = response.json()
    except ValueError:
        return {
            "room": info.__dict__,
            "updated_at": time.time(),
            "ranks": [],
            "total": 0,
            "raw_status": response.status_code,
            "raw_message": (
                "礼物榜接口返回了非 JSON 数据，可能未开播、匿名访问受限、登录失效或接口被风控"
                + (f"：{text_preview}" if text_preview else "")
            ),
            "content_type": content_type,
        }
    entries = _pick_rank_entries(payload)
    ranks = [
        _normalize_rank_entry(entry, index)
        for index, entry in enumerate(entries, start=1)
        if isinstance(entry, dict)
    ]
    return {
        "room": info.__dict__,
        "updated_at": time.time(),
        "ranks": ranks[:100],
        "total": len(ranks),
        "raw_status": payload.get("status_code") if isinstance(payload, dict) else None,
        "raw_message": payload.get("status_msg") or payload.get("message") if isinstance(payload, dict) else "",
    }


def resolve_live_room(auth: DouyinAuthState, value: str) -> dict:
    value = extract_douyin_share_url(value)
    if not value:
        raise ValueError("请粘贴直播间地址、用户主页或分享链接")
    if "live.douyin.com/" in value:
        info = fetch_live_room_info(auth, value)
        room_url = f"{DOUYIN_LIVE_ORIGIN}/{info.web_rid}"
        return {
            "input_type": "live_room",
            "source_url": value,
            "profile_url": value,
            "is_live": _is_live_status(info.status),
            "room_url": room_url,
            "web_rid": info.web_rid,
            "room_id": info.room_id,
            "anchor_id": info.anchor_id,
            "sec_anchor_id": info.sec_anchor_id,
            "nickname": "",
            "title": info.title,
            "message": "直播间已解析" if _is_live_status(info.status) else "直播间当前未开播",
        }

    if _sec_user_id(value):
        try:
            profile_result = _resolve_profile_live_room(auth, value)
            if profile_result.get("room_url"):
                profile_result["source_url"] = value
                profile_result["profile_url"] = f"{DOUYIN_WEB_ORIGIN}/user/{profile_result.get('sec_anchor_id') or _sec_user_id(value)}"
                return profile_result
        except (requests.RequestException, ValueError, RuntimeError, json.JSONDecodeError):
            pass

    from src import spider

    data = asyncio.run(spider.get_douyin_stream_data(value, cookies=auth.cookie_str))
    room_url = _room_url_from_data(data, value)
    is_live = _is_live_status(data.get("status")) and bool(room_url)
    if not is_live:
        sec_anchor_id = str(data.get("owner", {}).get("sec_uid") or "")
        return {
            "input_type": "user_profile",
            "source_url": value,
            "profile_url": f"{DOUYIN_WEB_ORIGIN}/user/{sec_anchor_id}" if sec_anchor_id else value,
            "is_live": False,
            "room_url": room_url,
            "web_rid": "",
            "room_id": str(data.get("id_str") or data.get("room_id") or data.get("id") or ""),
            "sec_anchor_id": sec_anchor_id,
            "nickname": data.get("anchor_name") or data.get("owner", {}).get("nickname") or "",
            "title": data.get("title", ""),
            "message": "该用户当前未开播，或暂时无法从主页解析直播间",
        }
    web_rid = room_url.rstrip("/").rsplit("/", 1)[-1]
    sec_anchor_id = str(data.get("owner", {}).get("sec_uid") or "")
    return {
        "input_type": "user_profile",
        "source_url": value,
        "profile_url": f"{DOUYIN_WEB_ORIGIN}/user/{sec_anchor_id}" if sec_anchor_id else value,
        "is_live": True,
        "room_url": room_url,
        "web_rid": web_rid,
        "room_id": str(data.get("id_str") or data.get("room_id") or data.get("id") or ""),
        "anchor_id": str(data.get("owner", {}).get("id_str") or data.get("owner", {}).get("id") or ""),
        "sec_anchor_id": sec_anchor_id,
        "nickname": data.get("anchor_name") or data.get("owner", {}).get("nickname") or "",
        "title": data.get("title", ""),
        "message": "已解析到直播间地址",
    }


class DouyinLiveSession:
    def __init__(self, room_url: str, auth: DouyinAuthState, on_event: Callable[[dict], None]):
        self.room_url = room_url
        self.auth = auth
        self.on_event = on_event
        self.info: LiveRoomInfo | None = None
        self.ws: WebSocketApp | None = None
        self._closed = threading.Event()
        self.method_counts: dict[str, int] = {}

    def start(self) -> None:
        self.info = fetch_live_room_info(self.auth, self.room_url)
        try:
            initial = fetch_initial_live_response(self.auth, self.info)
        except Exception:
            # The HTTP bootstrap endpoint is occasionally rejected by Douyin
            # with an HTML/JSON risk-control response. The websocket can still
            # establish its own cursor, so do not abort listening here.
            initial = Live_pb2.LiveResponse()
            self.on_event({"type": "system", "message": "初始化接口暂不可用，正在直接连接弹幕服务…"})
        params = {
            "app_name": "douyin_web",
            "version_code": "180800",
            "webcast_sdk_version": "1.0.15",
            "update_version_code": "1.0.15",
            "compress": "gzip",
            "device_platform": "web",
            "cookie_enabled": "true",
            "screen_width": "1707",
            "screen_height": "960",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Mozilla",
            "browser_version": UA.split("Mozilla/")[-1],
            "browser_online": "true",
            "tz_name": "Asia/Shanghai",
            "cursor": str(initial.cursor),
            "internal_ext": initial.internalExt,
            "host": DOUYIN_LIVE_ORIGIN,
            "aid": "6383",
            "live_id": "1",
            "did_rule": "3",
            "endpoint": "live_pc",
            "support_wrds": "1",
            "user_unique_id": self.info.user_id,
            "im_path": "/webcast/im/fetch/",
            "identity": "audience",
            "need_persist_msg_count": "15",
            "insert_task_id": "",
            "live_reason": "",
            "room_id": self.info.room_id,
            "heartbeatDuration": "0",
            "signature": _live_signature(self.info.room_id, self.info.user_id),
        }
        url = f"wss://webcast100-ws-web-hl.douyin.com/webcast/im/push/v2/?{urllib.parse.urlencode(params)}"
        self.ws = WebSocketApp(
            url=url,
            header={
                "Pragma": "no-cache",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": UA,
                "Upgrade": "websocket",
                "Cache-Control": "no-cache",
                "Connection": "Upgrade",
            },
            cookie=self.auth.cookie_str,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self.ws.run_forever(origin=DOUYIN_LIVE_ORIGIN)

    def stop(self) -> None:
        self._closed.set()
        if self.ws:
            self.ws.close()

    def _on_open(self, ws) -> None:
        self.on_event({"type": "system", "message": "弹幕监听已连接", "room": self.info.__dict__ if self.info else {}})
        threading.Thread(target=self._ping, args=(ws,), daemon=True).start()

    def _ping(self, ws) -> None:
        while not self._closed.is_set():
            frame = Live_pb2.PushFrame()
            frame.payloadType = "hb"
            try:
                ws.send(frame.SerializeToString(), opcode=0x02)
            except Exception:
                break
            self._closed.wait(5)

    def _on_message(self, ws, message: bytes) -> None:
        try:
            if isinstance(message, str):
                return
            frame = Live_pb2.PushFrame()
            frame.ParseFromString(message)
            if frame.payloadType in {"hb", "ack"} or not frame.payload:
                return
            response = _decode_live_response(frame)
            if response.needAck:
                ack = Live_pb2.PushFrame()
                ack.payloadType = "ack"
                ack.payload = response.internalExt.encode("utf-8")
                ack.logId = frame.logId
                ws.send(ack.SerializeToString(), opcode=0x02)
            for item in response.messagesList:
                self._handle_message(item)
        except Exception as exc:
            self.on_event({"type": "error", "message": f"弹幕解析失败：{exc}"})

    def _handle_message(self, item) -> None:
        method = str(item.method or "")
        self.method_counts[method] = self.method_counts.get(method, 0) + 1
        if method == "WebcastChatMessage":
            msg = Live_pb2.ChatMessage()
            msg.ParseFromString(item.payload)
            self.on_event({"type": "chat", "user": _user_to_dict(msg.user), "content": msg.content})
        elif method == "WebcastMemberMessage":
            msg = Live_pb2.MemberMessage()
            msg.ParseFromString(item.payload)
            self.on_event({"type": "member", "user": _user_to_dict(msg.user), "content": "进入直播间"})
        elif "GiftMessage" in method:
            msg = Live_pb2.GiftMessage()
            msg.ParseFromString(item.payload)
            wire = _gift_wire_metadata(item.payload)
            gift_id = str(msg.giftId or msg.gift.id or wire.get("gift_id") or "")
            gift_name = str(msg.gift.name or wire.get("gift_name") or "未知礼物")
            combo_count = _gift_combo_count(msg.comboCount, wire.get("combo_count"), wire.get("repeat_count"))
            shape = _protobuf_wire_shape(item.payload)
            fingerprint = hashlib.sha256(json.dumps(shape, sort_keys=True).encode("utf-8")).hexdigest()[:12]
            schema_event = {
                "type": "gift_schema",
                "source_method": method,
                "message_id": str(getattr(item, "msgId", "") or ""),
                "schema_fingerprint": fingerprint,
                "schema": shape,
                "accepted": combo_count is not None,
                "gift_name_resolved": bool(gift_name and gift_name != "未知礼物"),
                "user_resolved": bool(getattr(msg.user, "nickname", "")),
            }
            if combo_count is None:
                self.on_event(schema_event)
                self.on_event({
                    "type": "error",
                    "message": "收到字段结构异常的礼物消息，已忽略以防止错误计数",
                    "source_method": method,
                })
                return
            self.on_event({
                "type": "gift",
                "user": _user_to_dict(msg.user),
                "message_id": str(getattr(item, "msgId", "") or ""),
                "gift_id": gift_id,
                "gift_name": gift_name,
                "combo_count": combo_count,
                "repeat_end": bool(wire.get("repeat_end")),
                "diamond_count": int(wire.get("diamond_count") or 0),
                "content": f"送出 {gift_name} x {combo_count}",
                "source_method": method,
            })
            self.on_event(schema_event)
        elif method == "WebcastSocialMessage":
            msg = Live_pb2.SocialMessage()
            msg.ParseFromString(item.payload)
            if msg.action == 1:
                self.on_event({"type": "follow", "user": _user_to_dict(msg.user), "content": "关注了主播"})

    def _on_error(self, _ws, error) -> None:
        self.on_event({"type": "error", "message": str(error)})

    def _on_close(self, _ws, code, message) -> None:
        if not self._closed.is_set():
            self.on_event({"type": "system", "message": f"弹幕监听已断开：{code or ''} {message or ''}".strip()})


class DouyinInteractionManager:
    def __init__(self, on_event=None):
        self._lock = threading.RLock()
        self._auth = DouyinAuthState.from_cookie("")
        self._anonymous_auth = DouyinAuthState.from_cookie("")
        self._anonymous_live_access = True
        self._session: DouyinLiveSession | None = None
        self._thread: threading.Thread | None = None
        self._events: deque[dict] = deque(maxlen=1500)
        self._offset = 0
        self._room_url = ""
        self._audio_process: subprocess.Popen[bytes] | None = None
        self._audio_source_url = ""
        self._audio_stream_id = ""
        self._event_callback = on_event
        self._event_callback_errors = 0
        self._last_event_callback_error = ""
        self._rank_stop = threading.Event()
        self._rank_thread: threading.Thread | None = None
        self._rank_error = ""

    def set_auth(self, cookie: str, security: dict | None = None, anonymous_live_access: bool = True) -> None:
        self.stop_audio()
        with self._lock:
            self._auth = DouyinAuthState.from_cookie(cookie, security)
            self._anonymous_live_access = bool(anonymous_live_access)

    def set_live_access_mode(self, anonymous: bool) -> None:
        self.stop_audio()
        with self._lock:
            self._anonymous_live_access = bool(anonymous)

    def _live_auth(self) -> DouyinAuthState:
        return self._anonymous_auth if self._anonymous_live_access else self._auth

    @property
    def connected(self) -> bool:
        return self._auth.connected

    def status(self) -> dict:
        with self._lock:
            methods = dict(self._session.method_counts) if self._session else {}
            return {
                "connected": self.connected,
                "access_mode": self._live_auth().access_mode,
                "account_connected": self.connected,
                "anonymous_live_access": self._anonymous_live_access,
                "public_access": True,
                "listening": bool(self._thread and self._thread.is_alive()),
                "room_url": self._room_url,
                "can_send": self.connected and self._auth.security.complete,
                "audio_playing": bool(self._audio_process and self._audio_process.poll() is None),
                "gift_messages_seen": sum(count for method, count in methods.items() if "GiftMessage" in method),
                "message_types": methods,
                "event_callback_errors": self._event_callback_errors,
                "last_event_callback_error": self._last_event_callback_error,
                "gift_rank_fallback": bool(self._rank_thread and self._rank_thread.is_alive()),
                "gift_rank_error": self._rank_error,
            }

    def _append(self, event: dict) -> None:
        event = {"time": time.time(), **event}
        if event.get("type") != "gift_schema":
            with self._lock:
                if self._events.maxlen and len(self._events) == self._events.maxlen:
                    self._offset += 1
                self._events.append(event)
        if self._event_callback:
            try:
                self._event_callback(dict(event))
            except Exception as exc:
                self._event_callback_errors += 1
                self._last_event_callback_error = str(exc)

    def events(self, cursor: int = 0) -> dict:
        with self._lock:
            start = max(0, cursor - self._offset)
            return {"cursor": self._offset + len(self._events), "events": list(self._events)[start:]}

    def start_listening(self, room_url: str) -> dict:
        room_url = room_url.strip()
        if not room_url:
            raise ValueError("请先选择直播间")
        if "live.douyin.com/" in room_url:
            room_url = f"{DOUYIN_LIVE_ORIGIN}/{_room_web_rid(room_url)}"
        self.stop_listening()
        live_auth = self._live_auth()
        with self._lock:
            self._room_url = room_url
            self._session = DouyinLiveSession(self._room_url, live_auth, self._append)
            self._thread = threading.Thread(target=self._run_session, daemon=True)
            self._thread.start()
        mode = "登录增强模式" if live_auth.connected else "匿名模式"
        self._append({"type": "system", "message": f"正在以{mode}连接直播间弹幕…"})
        self._rank_stop.clear()
        self._rank_thread = threading.Thread(target=self._poll_gift_rank, daemon=True, name="douyin-gift-rank")
        self._rank_thread.start()
        return self.status()

    def _poll_gift_rank(self) -> None:
        while not self._rank_stop.is_set():
            try:
                result = fetch_gift_rank(self._live_auth(), self._room_url)
                self._rank_error = str(result.get("raw_message") or "")
                if result.get("ranks"):
                    self._append({"type": "gift_rank_snapshot", "ranks": result["ranks"], "updated_at": result.get("updated_at")})
            except Exception as exc:
                self._rank_error = str(exc)
            self._rank_stop.wait(30)

    def _run_session(self) -> None:
        try:
            assert self._session is not None
            self._session.start()
        except Exception as exc:
            message = str(exc)
            if not self._live_auth().connected:
                message += "；匿名访问可能受到抖音限制，可登录后重试"
            self._append({"type": "error", "message": message})

    def stop_listening(self) -> dict:
        self._rank_stop.set()
        rank_thread = self._rank_thread
        if rank_thread and rank_thread.is_alive() and threading.current_thread() is not rank_thread:
            rank_thread.join(timeout=2)
        self._rank_thread = None
        with self._lock:
            session = self._session
            self._session = None
            self._thread = None
        if session:
            session.stop()
            self._append({"type": "system", "message": "弹幕监听已停止"})
        return self.status()

    def send_chat(self, content: str) -> dict:
        content = content.strip()
        if not content:
            raise ValueError("弹幕内容不能为空")
        if not self._room_url:
            raise ValueError("请先选择直播间并启动监听")
        if not self.connected:
            raise RuntimeError("发送弹幕属于账号操作，请先登录抖音账号")
        if not self._auth.security.complete:
            raise RuntimeError("当前仅同步了 Cookie，缺少发送弹幕所需的 web_protect 安全字段")
        info = fetch_live_room_info(self._auth, self._room_url)
        api = "/webcast/room/chat/"
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "enter_from": "web_others_homepage",
            "cookie_enabled": "true",
            "screen_width": "2560",
            "screen_height": "1440",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Edge",
            "browser_version": "130.0.0.0",
            "room_id": info.room_id,
            "content": content,
            "type": "0",
            "msToken": _ms_token(self._auth.cookie),
        }
        params["a_bogus"] = _a_bogus(params)
        headers = {
            "accept": "application/json, text/plain, */*",
            "origin": DOUYIN_WEB_ORIGIN,
            "referer": f"{DOUYIN_LIVE_ORIGIN}/{info.web_rid}",
            "user-agent": UA,
            "x-secsdk-csrf-token": _csrf_token(self._auth.cookie_str),
            "bd-ticket-guard-client-data": _bd_ticket_client_data(api, self._auth.security),
            "bd-ticket-guard-iteration-version": "1",
            "bd-ticket-guard-ree-public-key": _ree_key(self._auth.security.private_key),
            "bd-ticket-guard-version": "2",
            "bd-ticket-guard-web-version": "1",
        }
        response = requests.get(
            f"{DOUYIN_LIVE_ORIGIN}{api}",
            headers=headers,
            params=params,
            cookies=self._auth.cookie,
            timeout=15,
            verify=False,
        )
        result = response.json()
        self._append({"type": "self", "content": content, "result": result})
        return {"ok": True, "result": result}

    def audio_source(self, room_url: str, quality: str = "原画") -> dict:
        from src import spider, stream

        room_url = room_url.strip()
        if not room_url:
            raise ValueError("请先选择直播间")
        if "live.douyin.com/" in room_url:
            room_url = f"{DOUYIN_LIVE_ORIGIN}/{_room_web_rid(room_url)}"
        live_auth = self._live_auth()

        # The public room page issues cookies such as ``ttwid``. Calling the
        # webcast enter API with only the generated anonymous cookies is often
        # classified as risk traffic, even though the room page itself is
        # accessible. Warm the public session first and retry once when Douyin
        # returns an empty/non-live response.
        confirmed_live = False
        try:
            room_info = fetch_live_room_info(live_auth, room_url)
            confirmed_live = _is_live_status(room_info.status)
        except Exception:
            room_info = None

        info: dict = {}
        last_error: Exception | None = None
        for attempt in range(2):
            if attempt:
                try:
                    room_info = fetch_live_room_info(live_auth, room_url)
                    confirmed_live = confirmed_live or _is_live_status(room_info.status)
                except Exception:
                    pass
            try:
                data = asyncio.run(
                    spider.get_douyin_web_stream_data(room_url, cookies=live_auth.cookie_str)
                )
                info = asyncio.run(stream.get_douyin_stream_url(data, quality, "")) or {}
            except Exception as exc:
                last_error = exc
                continue
            if info.get("is_live") and (
                info.get("flv_url") or info.get("m3u8_url") or info.get("record_url")
            ):
                break
        else:
            if confirmed_live:
                raise RuntimeError("直播间已确认开播，但音频源接口暂时受限；已自动重试，请稍后再试") from last_error
            if last_error:
                raise RuntimeError(f"无法获取直播音频：{last_error}；已自动刷新匿名会话并重试") from last_error
            raise RuntimeError("直播间未开播或暂时无法取得音频源；已自动刷新匿名会话并重试")

        # The FLV pull URL is more reliable for FFmpeg than Douyin's HLS
        # playlist, whose media segments may reject a request after the
        # playlist itself passed the availability probe.
        url = info.get("flv_url") or info.get("m3u8_url") or info.get("record_url")
        if not url:
            raise RuntimeError("直播间已开播，但没有可用的音频流地址")
        self.stop_audio()
        stream_id = secrets.token_urlsafe(18)
        with self._lock:
            self._audio_source_url = str(url)
            self._audio_stream_id = stream_id
        return {
            "stream_id": stream_id,
            "title": info.get("title", ""),
            "anchor_name": info.get("anchor_name", ""),
            "quality": info.get("quality", quality),
            "format": "mp3",
            "source_format": "hls" if ".m3u8" in str(url) else "flv",
            "access_mode": live_auth.access_mode,
        }

    def start_audio_stream(self, stream_id: str) -> subprocess.Popen[bytes]:
        self.stop_audio()
        with self._lock:
            if not stream_id or stream_id != self._audio_stream_id or not self._audio_source_url:
                raise ValueError("音频播放凭证已失效，请重新获取音频源")
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise RuntimeError("缺少 FFmpeg，无法转换直播音频")
            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            process = subprocess.Popen(
                _audio_relay_command(ffmpeg, self._audio_source_url),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                **kwargs,
            )
            self._audio_process = process
            return process

    def finish_audio_stream(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._audio_process is process:
                self._audio_process = None
        self._terminate_audio_process(process)

    def stop_audio(self) -> None:
        with self._lock:
            process = self._audio_process
            self._audio_process = None
        if process:
            self._terminate_audio_process(process)

    @staticmethod
    def _terminate_audio_process(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def gift_rank(self, room_url: str) -> dict:
        room_url = (room_url or self._room_url).strip()
        if not room_url:
            raise ValueError("请先选择直播间")
        live_auth = self._live_auth()
        try:
            result = fetch_gift_rank(live_auth, room_url)
        except Exception as exc:
            suffix = "；匿名访问可能受到抖音限制，可切换登录增强后重试" if not live_auth.connected else ""
            raise RuntimeError(f"无法获取礼物贡献榜：{exc}{suffix}") from exc
        result["access_mode"] = live_auth.access_mode
        return result

    def resolve_live_room(self, value: str) -> dict:
        try:
            result = resolve_live_room(self._auth, value)
        except Exception as exc:
            suffix = "；匿名访问可能受到抖音限制，可登录后重试" if not self.connected else ""
            raise RuntimeError(f"无法解析直播间：{exc}{suffix}") from exc
        result["access_mode"] = self._auth.access_mode
        return result

    def search_users(self, keyword: str, limit: int = 12) -> dict:
        try:
            users = search_douyin_users(self._auth, keyword, limit)
        except Exception as exc:
            suffix = "；登录抖音后搜索通常更稳定" if not self.connected else ""
            raise RuntimeError(f"无法搜索主播：{exc}{suffix}") from exc
        return {"keyword": str(keyword or "").strip(), "users": users, "access_mode": self._auth.access_mode}
