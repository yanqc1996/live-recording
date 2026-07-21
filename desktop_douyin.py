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
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


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
    match = re.search(r"live\.douyin\.com/([^/?#\s]+)", value)
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
        return bool(self.cookie_str)


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
    live_response = Live_pb2.LiveResponse()
    live_response.ParseFromString(response.content)
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
            "raw_message": f"礼物榜接口暂不可用（HTTP {response.status_code}），可能未开播、登录失效或接口被风控",
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
                "礼物榜接口返回了非 JSON 数据，可能未开播、登录失效或接口被风控"
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
    value = value.strip()
    if not value:
        raise ValueError("请粘贴直播间地址、用户主页或分享链接")
    if "live.douyin.com/" in value:
        info = fetch_live_room_info(auth, value)
        room_url = f"{DOUYIN_LIVE_ORIGIN}/{info.web_rid}"
        return {
            "input_type": "live_room",
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
                return profile_result
        except (requests.RequestException, ValueError, RuntimeError, json.JSONDecodeError):
            pass

    from src import spider

    data = asyncio.run(spider.get_douyin_stream_data(value, cookies=auth.cookie_str))
    room_url = _room_url_from_data(data, value)
    is_live = _is_live_status(data.get("status")) and bool(room_url)
    if not is_live:
        return {
            "input_type": "user_profile",
            "is_live": False,
            "room_url": room_url,
            "web_rid": "",
            "room_id": str(data.get("id_str") or data.get("room_id") or data.get("id") or ""),
            "nickname": data.get("anchor_name") or data.get("owner", {}).get("nickname") or "",
            "title": data.get("title", ""),
            "message": "该用户当前未开播，或暂时无法从主页解析直播间",
        }
    web_rid = room_url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "input_type": "user_profile",
        "is_live": True,
        "room_url": room_url,
        "web_rid": web_rid,
        "room_id": str(data.get("id_str") or data.get("room_id") or data.get("id") or ""),
        "anchor_id": str(data.get("owner", {}).get("id_str") or data.get("owner", {}).get("id") or ""),
        "sec_anchor_id": data.get("owner", {}).get("sec_uid") or "",
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

    def start(self) -> None:
        self.info = fetch_live_room_info(self.auth, self.room_url)
        initial = fetch_initial_live_response(self.auth, self.info)
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
            frame = Live_pb2.PushFrame()
            frame.ParseFromString(message)
            response = Live_pb2.LiveResponse()
            response.ParseFromString(gzip.decompress(frame.payload))
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
        if item.method == "WebcastChatMessage":
            msg = Live_pb2.ChatMessage()
            msg.ParseFromString(item.payload)
            self.on_event({"type": "chat", "user": _user_to_dict(msg.user), "content": msg.content})
        elif item.method == "WebcastMemberMessage":
            msg = Live_pb2.MemberMessage()
            msg.ParseFromString(item.payload)
            self.on_event({"type": "member", "user": _user_to_dict(msg.user), "content": "进入直播间"})
        elif item.method == "WebcastGiftMessage":
            msg = Live_pb2.GiftMessage()
            msg.ParseFromString(item.payload)
            self.on_event({
                "type": "gift",
                "user": _user_to_dict(msg.user),
                "content": f"送出 {msg.gift.name} x {msg.comboCount}",
            })
        elif item.method == "WebcastSocialMessage":
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
    def __init__(self):
        self._lock = threading.RLock()
        self._auth = DouyinAuthState()
        self._session: DouyinLiveSession | None = None
        self._thread: threading.Thread | None = None
        self._events: deque[dict] = deque(maxlen=1500)
        self._offset = 0
        self._room_url = ""
        self._audio_process: subprocess.Popen | None = None

    def set_auth(self, cookie: str, security: dict | None = None) -> None:
        with self._lock:
            self._auth = DouyinAuthState.from_cookie(cookie, security)

    @property
    def connected(self) -> bool:
        return self._auth.connected

    def status(self) -> dict:
        with self._lock:
            return {
                "connected": self.connected,
                "listening": bool(self._thread and self._thread.is_alive()),
                "room_url": self._room_url,
                "can_send": self._auth.security.complete,
                "audio_playing": bool(self._audio_process and self._audio_process.poll() is None),
            }

    def _append(self, event: dict) -> None:
        event = {"time": time.time(), **event}
        with self._lock:
            if self._events.maxlen and len(self._events) == self._events.maxlen:
                self._offset += 1
            self._events.append(event)

    def events(self, cursor: int = 0) -> dict:
        with self._lock:
            start = max(0, cursor - self._offset)
            return {"cursor": self._offset + len(self._events), "events": list(self._events)[start:]}

    def start_listening(self, room_url: str) -> dict:
        if not self.connected:
            raise RuntimeError("请先登录抖音账号")
        self.stop_listening()
        with self._lock:
            self._room_url = room_url.strip()
            self._session = DouyinLiveSession(self._room_url, self._auth, self._append)
            self._thread = threading.Thread(target=self._run_session, daemon=True)
            self._thread.start()
        self._append({"type": "system", "message": "正在连接直播间弹幕…"})
        return self.status()

    def _run_session(self) -> None:
        try:
            assert self._session is not None
            self._session.start()
        except Exception as exc:
            self._append({"type": "error", "message": str(exc)})

    def stop_listening(self) -> dict:
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
        if not self.connected:
            raise RuntimeError("请先登录抖音账号")
        from src import spider, stream

        room_url = room_url.strip()
        data = asyncio.run(spider.get_douyin_web_stream_data(room_url, cookies=self._auth.cookie_str))
        info = asyncio.run(stream.get_douyin_stream_url(data, quality, ""))
        if not info.get("is_live"):
            raise RuntimeError("直播间未开播或无法取得音频源")
        url = info.get("m3u8_url") or info.get("flv_url") or info.get("record_url")
        return {
            "url": url,
            "title": info.get("title", ""),
            "anchor_name": info.get("anchor_name", ""),
            "quality": info.get("quality", quality),
            "format": "hls" if ".m3u8" in str(url) else "flv",
        }

    def gift_rank(self, room_url: str) -> dict:
        if not self.connected:
            raise RuntimeError("请先登录抖音账号")
        room_url = (room_url or self._room_url).strip()
        if not room_url:
            raise ValueError("请先选择直播间")
        return fetch_gift_rank(self._auth, room_url)

    def resolve_live_room(self, value: str) -> dict:
        if not self.connected:
            raise RuntimeError("请先登录抖音账号")
        return resolve_live_room(self._auth, value)
