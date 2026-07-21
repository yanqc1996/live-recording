"""One-shot Douyin user works puller with persistent diff state."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

DOUYIN_WEB_ORIGIN = "https://www.douyin.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.6261.95 Safari/537.36"
)
PAGE_COUNT_PER_REQUEST = 50
_WORK_ABOGUS = None


def _work_a_bogus(params: dict) -> str:
    """Generate a_bogus for Douyin work APIs, falling back to the live signer if optional deps are missing."""

    global _WORK_ABOGUS
    try:
        if _WORK_ABOGUS is None:
            from douyin_static.work_abogus import ABogus

            _WORK_ABOGUS = ABogus()
        return urllib.parse.quote(_WORK_ABOGUS.get_value(params), safe="")
    except Exception:
        from desktop_douyin import _a_bogus

        return _a_bogus(params)


def _now() -> int:
    return int(time.time())


def _atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _sanitize_filename(value: str, max_length: int = 120) -> str:
    value = urllib.parse.unquote(str(value or "unknown"))
    value = re.sub(r'[\\/*?:"<>|#\r\n\t]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        value = "unknown"
    if len(value) > max_length:
        value = value[: max_length - 3] + "..."
    return value


def _extension_from_url(url: str, default: str) -> str:
    try:
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1]
        if 1 < len(ext) <= 6:
            return ext
    except Exception:
        pass
    return default


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


def _ensure_ms_token(cookies: dict[str, str]) -> None:
    if cookies.get("msToken"):
        return
    alphabet = "ABCDEFGHIGKLMNOPQRSTUVWXYZabcdefghigklmnopqrstuvwxyz0123456789="
    cookies["msToken"] = "".join(random.choice(alphabet) for _ in range(107))


def _safe_json_response(response: requests.Response) -> dict:
    try:
        data = response.json()
        if isinstance(data, dict):
            data.setdefault("_http_status", response.status_code)
            data.setdefault("_content_type", response.headers.get("content-type", ""))
            return data
        return {"_http_status": response.status_code, "_content_type": response.headers.get("content-type", ""), "_raw_type": type(data).__name__}
    except ValueError:
        preview = (response.text or "").strip()[:300]
        return {
            "_http_status": response.status_code,
            "_content_type": response.headers.get("content-type", ""),
            "_raw_preview": preview,
            "_json_error": "接口返回非 JSON",
        }


def extract_sec_user_id(value: str) -> str:
    for pattern in (
        r"/user/([A-Za-z0-9_.\-]+)",
        r"sec_user_id=([A-Za-z0-9_.\-]+)",
        r"(MS4wLjAB[A-Za-z0-9_-]+)",
    ):
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def _aweme_time(aweme: dict[str, Any]) -> int:
    try:
        return int(aweme.get("create_time") or 0)
    except (TypeError, ValueError):
        return 0


def _date_prefix(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "unknown-date"


def _best_url_from_bit_rates(bit_rates: list[dict[str, Any]]) -> str:
    if not bit_rates:
        return ""
    best = max(bit_rates, key=lambda item: int(item.get("bit_rate") or 0))
    urls = best.get("play_addr", {}).get("url_list", [])
    return str(urls[0]) if urls else ""


@dataclass
class MediaItem:
    url: str
    filename: str
    kind: str


def media_items_from_aweme(aweme: dict[str, Any]) -> list[MediaItem]:
    aweme_id = str(aweme.get("aweme_id") or aweme.get("group_id") or "")
    created_at = _aweme_time(aweme)
    desc = _sanitize_filename(str(aweme.get("desc") or aweme_id or "work"), 80)
    prefix = f"{_date_prefix(created_at)}_{aweme_id}_{desc}"
    items: list[MediaItem] = []

    video_url = _best_url_from_bit_rates(aweme.get("video", {}).get("bit_rate", []) or [])
    if video_url:
        items.append(MediaItem(video_url, _sanitize_filename(prefix, 150) + _extension_from_url(video_url, ".mp4"), "video"))

    for index, image in enumerate(aweme.get("images") or [], start=1):
        if not isinstance(image, dict):
            continue
        live_url = _best_url_from_bit_rates(image.get("video", {}).get("bit_rate", []) or [])
        if live_url:
            items.append(
                MediaItem(
                    live_url,
                    _sanitize_filename(f"{prefix}_live{index}", 150) + _extension_from_url(live_url, ".mp4"),
                    "live_image",
                )
            )
            continue
        urls = image.get("url_list") or []
        if urls:
            image_url = str(urls[-1])
            items.append(
                MediaItem(
                    image_url,
                    _sanitize_filename(f"{prefix}_p{index}", 150) + _extension_from_url(image_url, ".jpg"),
                    "image",
                )
            )
    return items


class WorkPullManager:
    """Manual one-shot pull task; state is only used for diff/skip decisions."""

    def __init__(self, state_path: Path, default_output: Path):
        self.state_path = state_path
        self.default_output = default_output
        self._cookie = ""
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._logs: deque[str] = deque(maxlen=1200)
        self._log_offset = 0
        self._status = {
            "running": False,
            "message": "未开始",
            "user": None,
            "started_at": None,
            "finished_at": None,
            "stats": {},
        }

    def set_auth(self, cookie: str) -> None:
        with self._lock:
            self._cookie = cookie.strip()

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def logs(self, cursor: int = 0) -> dict:
        with self._lock:
            base = self._log_offset
            lines = list(self._logs)
            if cursor < base:
                cursor = base
            start = max(0, cursor - base)
            return {"cursor": base + len(lines), "lines": lines[start:]}

    def start(self, user_url: str, output_path: str = "", force: bool = False) -> dict:
        user_url = user_url.strip()
        if not user_url:
            raise ValueError("请粘贴用户主页、分享链接或 sec_user_id")
        with self._lock:
            if self._status.get("running"):
                raise ValueError("已有作品拉取任务正在运行")
            if not self._cookie:
                raise ValueError("请先登录抖音账号，再拉取用户作品")
            self._stop.clear()
            self._set_status_locked(
                running=True,
                message="准备拉取",
                user=None,
                started_at=_now(),
                finished_at=None,
                stats={"fetched": 0, "new": 0, "skipped": 0, "downloaded": 0, "failed": 0},
            )
            self._thread = threading.Thread(
                target=self._run,
                args=(user_url, output_path.strip(), force, self._cookie),
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def _set_status_locked(self, **updates) -> None:
        self._status.update(updates)

    def _log(self, line: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            if self._logs.maxlen and len(self._logs) == self._logs.maxlen:
                self._log_offset += 1
            self._logs.append(f"[{stamp}] {line}")

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"users": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"users": {}}
        except Exception:
            return {"users": {}}

    def _save_state(self, state: dict) -> None:
        _atomic_json_write(self.state_path, state)

    def _session(self, cookie: str) -> requests.Session:
        cookies = _parse_cookie(cookie)
        _ensure_ms_token(cookies)
        session = requests.Session()
        session.headers.update(
            {
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                "cookie": _cookie_string(cookies),
                "referer": f"{DOUYIN_WEB_ORIGIN}/",
                "user-agent": UA,
            }
        )
        session.cookies.update(cookies)
        return session

    def _resolve_sec_user_id(self, session: requests.Session, value: str) -> str:
        sec_user_id = extract_sec_user_id(value)
        if sec_user_id:
            return sec_user_id
        response = session.get(value, allow_redirects=True, timeout=12)
        sec_user_id = extract_sec_user_id(response.url or value) or extract_sec_user_id(response.text[:20000])
        if not sec_user_id:
            raise ValueError("无法从链接中识别 sec_user_id，请使用用户主页链接或包含 sec_user_id 的链接")
        return sec_user_id

    def _profile(self, session: requests.Session, sec_user_id: str) -> dict:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "sec_user_id": sec_user_id,
            "from_user_page": "1",
        }
        response = session.get(f"{DOUYIN_WEB_ORIGIN}/aweme/v1/web/user/profile/other/", params=params, timeout=15)
        data = _safe_json_response(response)
        if data.get("_json_error"):
            raise ValueError(f"用户资料接口返回异常：HTTP {data.get('_http_status')} / {data.get('_content_type')} / {data.get('_raw_preview')}")
        user = data.get("user") or {}
        return {
            "nickname": user.get("nickname") or sec_user_id[-8:],
            "unique_id": user.get("unique_id") or "",
            "aweme_count": user.get("aweme_count"),
            "profile_status": data.get("status_code"),
            "profile_message": data.get("status_msg") or data.get("message") or "",
        }

    def _post_page(self, session: requests.Session, sec_user_id: str, cursor: int, first: bool) -> dict:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "sec_user_id": sec_user_id,
            "max_cursor": str(cursor),
            "count": str(PAGE_COUNT_PER_REQUEST),
            "locate_query": "false",
            "show_live_replay_strategy": "1",
            "need_time_list": "1" if first else "0",
            "publish_video_strategy_type": "2",
            "from_user_page": "1",
            "update_version_code": "170400",
        }
        params["a_bogus"] = _work_a_bogus(params)
        response = session.get(f"{DOUYIN_WEB_ORIGIN}/aweme/v1/web/aweme/post/", params=params, timeout=20)
        data = _safe_json_response(response)
        if response.status_code != 200:
            data["_request_error"] = f"HTTP {response.status_code}"
        return data

    def _download(self, session: requests.Session, item: MediaItem, folder: Path) -> tuple[bool, Path]:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / item.filename
        if target.exists() and target.stat().st_size > 0:
            return False, target
        temporary = target.with_suffix(target.suffix + ".part")
        headers = {"referer": DOUYIN_WEB_ORIGIN, "user-agent": UA}
        with session.get(item.url, headers=headers, stream=True, timeout=40) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
        os.replace(temporary, target)
        return True, target

    def _run(self, user_url: str, output_path: str, force: bool, cookie: str) -> None:
        stats = {"fetched": 0, "new": 0, "skipped": 0, "downloaded": 0, "failed": 0}
        try:
            session = self._session(cookie)
            sec_user_id = self._resolve_sec_user_id(session, user_url)
            profile = self._profile(session, sec_user_id)
            nickname = _sanitize_filename(profile["nickname"], 80)
            root = Path(output_path).expanduser() if output_path else self.default_output
            folder = root / "douyin_works" / f"{nickname}_{sec_user_id[-8:]}"
            state = self._load_state()
            users = state.setdefault("users", {})
            user_state = users.setdefault(
                sec_user_id,
                {
                    "nickname": profile["nickname"],
                    "unique_id": profile.get("unique_id", ""),
                    "user_url": user_url,
                    "last_pull_time": 0,
                    "processed_aweme_ids": {},
                },
            )
            user_state.update({"nickname": profile["nickname"], "unique_id": profile.get("unique_id", ""), "user_url": user_url})
            processed = user_state.setdefault("processed_aweme_ids", {})
            last_pull_time = int(user_state.get("last_pull_time") or 0)
            with self._lock:
                self._set_status_locked(user={"sec_user_id": sec_user_id, **profile}, message="拉取中", stats=stats)
            self._log(f"开始拉取：{profile['nickname']}，保存到 {folder}")
            self._log(f"用户 sec_user_id：{sec_user_id}")
            if profile.get("aweme_count") not in (None, ""):
                self._log(f"主页作品数：{profile.get('aweme_count')}")
            if profile.get("profile_status") not in (None, 0):
                self._log(f"用户资料接口状态：{profile.get('profile_status')} / {profile.get('profile_message')}")
            if last_pull_time and not force:
                self._log(f"增量模式：只处理 {datetime.fromtimestamp(last_pull_time)} 之后的新作品")
            elif force:
                self._log("强制模式：忽略上次拉取时间，但仍会跳过已记录作品 ID")

            cursor = 0
            first = True
            page_index = 1
            newest_seen = last_pull_time
            should_stop = False
            while not should_stop:
                before_fetched = stats["fetched"]
                before_skipped = stats["skipped"]
                before_new = stats["new"]
                page = self._post_page(session, sec_user_id, cursor, first)
                first = False
                if page.get("_json_error") or page.get("_request_error"):
                    self._log(
                        "作品接口异常："
                        f"{page.get('_request_error') or page.get('_json_error')} / "
                        f"{page.get('_content_type') or ''} / "
                        f"{page.get('_raw_preview') or ''}"
                    )
                    break
                status_code = page.get("status_code")
                status_msg = page.get("status_msg") or page.get("message") or ""
                if status_code not in (None, 0):
                    self._log(f"作品接口状态：{status_code} / {status_msg}")
                awemes = page.get("aweme_list") or []
                if not awemes:
                    detail = []
                    if page.get("has_more") not in (None, ""):
                        detail.append(f"has_more={page.get('has_more')}")
                    if page.get("max_cursor") not in (None, ""):
                        detail.append(f"max_cursor={page.get('max_cursor')}")
                    if profile.get("aweme_count"):
                        detail.append("资料页显示有作品，可能是作品接口被风控、Cookie 登录状态不足、签名参数失效或作品权限限制")
                    self._log("没有更多作品" + (f"（{'；'.join(detail)}）" if detail else ""))
                    break
                for aweme in awemes:
                    aweme_id = str(aweme.get("aweme_id") or aweme.get("group_id") or "")
                    created_at = _aweme_time(aweme)
                    newest_seen = max(newest_seen, created_at)
                    stats["fetched"] += 1
                    if aweme_id in processed:
                        stats["skipped"] += 1
                        continue
                    if not force and last_pull_time and created_at <= last_pull_time:
                        stats["skipped"] += 1
                        should_stop = True
                        continue
                    items = media_items_from_aweme(aweme)
                    if not items:
                        processed[aweme_id] = {"create_time": created_at, "status": "no_media", "handled_at": _now()}
                        stats["skipped"] += 1
                        continue
                    stats["new"] += 1
                    failed = 0
                    downloaded_paths = []
                    for item in items:
                        try:
                            downloaded, path = self._download(session, item, folder)
                            downloaded_paths.append(str(path))
                            if downloaded:
                                stats["downloaded"] += 1
                                self._log(f"已下载：{path.name}")
                            else:
                                stats["skipped"] += 1
                                self._log(f"本地已存在，跳过：{path.name}")
                        except Exception as exc:
                            failed += 1
                            stats["failed"] += 1
                            self._log(f"下载失败：{aweme_id} / {item.kind} / {exc}")
                    if failed == 0:
                        processed[aweme_id] = {
                            "create_time": created_at,
                            "status": "handled",
                            "handled_at": _now(),
                            "media_count": len(items),
                            "paths": downloaded_paths[:20],
                            "desc": str(aweme.get("desc") or "")[:120],
                        }
                        user_state["last_pull_time"] = max(int(user_state.get("last_pull_time") or 0), created_at)
                        self._save_state(state)
                    with self._lock:
                        self._set_status_locked(stats=dict(stats))
                page_fetched = stats["fetched"] - before_fetched
                page_new = stats["new"] - before_new
                page_skipped = stats["skipped"] - before_skipped
                self._log(f"第 {page_index} 页处理：作品 {page_fetched}，新增 {page_new}，跳过 {page_skipped}")
                page_index += 1
                if should_stop or not page.get("has_more"):
                    break
                try:
                    cursor = int(page.get("max_cursor") or 0)
                except (TypeError, ValueError):
                    break
                time.sleep(0.8)

            if newest_seen:
                user_state["last_seen_time"] = newest_seen
            self._save_state(state)
            self._log(f"拉取结束：新增作品 {stats['new']}，下载文件 {stats['downloaded']}，跳过 {stats['skipped']}，失败 {stats['failed']}")
            with self._lock:
                self._set_status_locked(running=False, message="已完成", finished_at=_now(), stats=dict(stats))
        except Exception as exc:
            self._log(f"拉取失败：{exc}")
            with self._lock:
                self._set_status_locked(running=False, message=f"失败：{exc}", finished_at=_now(), stats=dict(stats))
