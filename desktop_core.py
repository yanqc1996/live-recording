"""Local configuration and process control used by the visual recorder UI."""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


TEXT_ENCODING = "utf-8-sig"
RECORDING_SECTION = "录制设置"

SETTING_KEYS = {
    "output_path": "直播保存路径(不填则默认)",
    "format": "视频保存格式ts|mkv|flv|mp4|mp3音频|m4a音频",
    "quality": "原画|超清|高清|标清|流畅",
    "split_enabled": "分段录制是否开启",
    "split_seconds": "视频分段时间(秒)",
    "convert_to_mp4": "录制完成后自动转为mp4格式",
    "delete_original": "追加格式后删除原文件",
    "use_proxy": "是否使用代理ip(是/否)",
    "proxy_address": "代理地址",
    "check_interval": "循环时间(秒)",
    "disk_warning_gb": "磁盘空间预警阈值(GB)",
    "disk_stop_gb": "磁盘空间停止录制阈值(GB)",
}

DEFAULT_SETTINGS = {
    "output_path": "",
    "format": "TS",
    "quality": "原画",
    "split_enabled": True,
    "split_seconds": 1800,
    "convert_to_mp4": True,
    "delete_original": True,
    "use_proxy": False,
    "proxy_address": "",
    "check_interval": 300,
    "disk_warning_gb": 30,
    "disk_stop_gb": 10,
}


def normalize_recorder_anchor_name(value: str) -> str:
    """Remove the recorder engine's transient sequence prefix from display names."""
    return re.sub(r"^序号\d+\s+", "", str(value or "").strip()).strip()

BOOL_FIELDS = {"split_enabled", "convert_to_mp4", "delete_original", "use_proxy"}
INT_FIELDS = {"split_seconds", "check_interval", "disk_warning_gb", "disk_stop_gb"}
ALLOWED_FORMATS = {"TS", "MKV", "FLV", "MP4", "MP3", "M4A", "MP3音频", "M4A音频"}
ALLOWED_QUALITIES = {"原画", "超清", "高清", "标清", "流畅"}


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".desktop.tmp")
    temporary.write_text(content, encoding=TEXT_ENCODING)
    os.replace(temporary, path)


@dataclass
class RoomEntry:
    line: str
    active: bool

    @property
    def value(self) -> str:
        return self.line[1:].lstrip() if self.line.startswith("#") else self.line

    def to_dict(self, index: int) -> dict:
        return {"id": index, "value": self.value, "active": self.active}


class RoomStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def _all_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding=TEXT_ENCODING, errors="ignore").splitlines()

    def list(self) -> list[dict]:
        with self._lock:
            entries = []
            for line in self._all_lines():
                stripped = line.strip()
                if not stripped or stripped.startswith("##"):
                    continue
                value = stripped[1:].lstrip() if stripped.startswith("#") else stripped
                if "http://" not in value and "https://" not in value:
                    continue
                entries.append(RoomEntry(stripped, not stripped.startswith("#")))
            return [entry.to_dict(index) for index, entry in enumerate(entries)]

    def _editable_positions(self, lines: list[str]) -> list[int]:
        positions = []
        for index, line in enumerate(lines):
            value = line.strip().lstrip("#").lstrip()
            if "http://" in value or "https://" in value:
                positions.append(index)
        return positions

    def add(self, value: str) -> None:
        value = value.strip()
        if not re.search(r"https?://[^\s]+", value):
            raise ValueError("请输入有效的 http:// 或 https:// 直播间地址")
        with self._lock:
            lines = self._all_lines()
            if any(line.strip().lstrip("#").lstrip() == value for line in lines):
                raise ValueError("该直播间已经存在")
            lines.append(value)
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")

    def upsert_active(self, value: str) -> dict:
        value = value.strip()
        if not re.search(r"https?://[^\s]+", value):
            raise ValueError("请输入有效的 http:// 或 https:// 直播间地址")
        with self._lock:
            lines = self._all_lines()
            positions = self._editable_positions(lines)
            for room_id, position in enumerate(positions):
                current = lines[position].strip().lstrip("#").lstrip()
                if current == value:
                    lines[position] = value
                    _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")
                    return {"id": room_id, "value": value, "active": True, "created": False}
            lines.append(value)
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")
            return {"id": len(positions), "value": value, "active": True, "created": True}

    def set_active(self, room_id: int, active: bool) -> None:
        with self._lock:
            lines = self._all_lines()
            positions = self._editable_positions(lines)
            if room_id < 0 or room_id >= len(positions):
                raise IndexError("直播间不存在")
            position = positions[room_id]
            value = lines[position].strip().lstrip("#").lstrip()
            lines[position] = value if active else f"#{value}"
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")

    def replace_all(self, rooms: list[dict]) -> list[dict]:
        """Replace all editable recording entries while preserving comments and settings."""
        with self._lock:
            lines = self._all_lines()
            positions = self._editable_positions(lines)
            if len(rooms) != len(positions):
                raise ValueError("录制主播集合已发生变化，请刷新后重试")
            ids = [int(room.get("id", -1)) for room in rooms]
            if sorted(ids) != list(range(len(positions))):
                raise ValueError("录制主播集合序号不匹配，请刷新后重试")
            ordered = sorted(rooms, key=lambda room: int(room.get("id", -1)))
            values = [str(room.get("value", "")).strip() for room in ordered]
            if any(not re.search(r"https?://[^\s]+", value) for value in values):
                raise ValueError("每条录制数据都必须包含有效的直播间地址")
            if len(values) != len(set(values)):
                raise ValueError("录制主播集合中存在重复数据")
            for position, room, value in zip(positions, ordered, values):
                lines[position] = value if bool(room.get("active", True)) else f"#{value}"
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")
            return self.list()

    def sync_from_anchors(self, anchors: list[dict]) -> list[dict]:
        """Regenerate recorder entries from the canonical anchor collection."""
        with self._lock:
            lines = self._all_lines()
            positions = set(self._editable_positions(lines))
            preserved = [line for index, line in enumerate(lines) if index not in positions]
            entries = []
            seen = set()
            for anchor in anchors:
                live_url = str(anchor.get("live_url") or "").strip().split("?")[0]
                profile_url = str(anchor.get("profile_url") or "").strip().split("?")[0]
                url = live_url or (profile_url if "live.douyin.com/" in profile_url else "")
                if not url or url in seen:
                    continue
                seen.add(url)
                room_id = str(anchor.get("room_id") or "").strip()
                sec_user_id = str(anchor.get("sec_user_id") or "").strip()
                if "live.douyin.com/" in url and sec_user_id:
                    identity = {
                        "lr_room_id": room_id,
                        "lr_sec_user_id": sec_user_id,
                    }
                    if bool(anchor.get("anonymous_recording", False)):
                        identity["lr_anonymous_recording"] = "1"
                    url += "?" + urllib.parse.urlencode(identity)
                elif "live.douyin.com/" in url and bool(anchor.get("anonymous_recording", False)):
                    url += "?" + urllib.parse.urlencode({"lr_anonymous_recording": "1"})
                name = str(anchor.get("name") or "未命名主播").strip().replace("\n", " ").replace(",", "，")
                value = f"{url},主播: {name}"
                entries.append(value if bool(anchor.get("enabled_recording", True)) else f"#{value}")
            output = preserved + entries
            _atomic_write(self.path, "\n".join(output).rstrip() + "\n")
            return self.list()

    def delete(self, room_id: int) -> None:
        with self._lock:
            lines = self._all_lines()
            positions = self._editable_positions(lines)
            if room_id < 0 or room_id >= len(positions):
                raise IndexError("直播间不存在")
            del lines[positions[room_id]]
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")


class SettingsStore:
    """Update selected INI values while retaining comments and unrelated secrets."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def load(self) -> dict:
        values = dict(DEFAULT_SETTINGS)
        parser = configparser.RawConfigParser(strict=False)
        parser.optionxform = str
        if self.path.exists():
            parser.read(self.path, encoding=TEXT_ENCODING)
        for field, key in SETTING_KEYS.items():
            raw = parser.get(RECORDING_SECTION, key, fallback=None)
            if raw is None:
                continue
            if field in BOOL_FIELDS:
                values[field] = raw.strip() == "是"
            elif field in INT_FIELDS:
                try:
                    values[field] = int(raw)
                except ValueError:
                    pass
            else:
                values[field] = raw.strip()
        values["format"] = str(values["format"]).upper()
        return values

    def save(self, supplied: dict) -> dict:
        values = self._validate({**self.load(), **supplied})
        replacements = {}
        for field, key in SETTING_KEYS.items():
            value = values[field]
            replacements[key] = "是" if field in BOOL_FIELDS and value else "否" if field in BOOL_FIELDS else str(value)
        # The desktop MVP deliberately never executes upload/post-processing scripts.
        replacements["是否录制完成后执行自定义脚本"] = "否"
        with self._lock:
            text = self.path.read_text(encoding=TEXT_ENCODING) if self.path.exists() else ""
            lines = text.splitlines()
            section_start = next((i for i, line in enumerate(lines) if line.strip() == f"[{RECORDING_SECTION}]"), None)
            if section_start is None:
                lines.extend(([f"[{RECORDING_SECTION}]"] if not lines else ["", f"[{RECORDING_SECTION}]"]))
                section_start = len(lines) - 1
            section_end = next(
                (i for i in range(section_start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines)
            )
            found = set()
            for index in range(section_start + 1, section_end):
                if "=" not in lines[index] or lines[index].lstrip().startswith(('#', ';')):
                    continue
                key = lines[index].split("=", 1)[0].strip()
                if key in replacements:
                    lines[index] = f"{key} = {replacements[key]}"
                    found.add(key)
            for key, value in replacements.items():
                if key not in found:
                    lines.insert(section_end, f"{key} = {value}")
                    section_end += 1
            _atomic_write(self.path, "\n".join(lines).rstrip() + "\n")
        return values

    @staticmethod
    def _validate(values: dict) -> dict:
        if str(values["format"]).upper() not in ALLOWED_FORMATS:
            raise ValueError("不支持的视频格式")
        values["format"] = str(values["format"]).upper()
        if values["quality"] not in ALLOWED_QUALITIES:
            raise ValueError("不支持的录制画质")
        for field in INT_FIELDS:
            try:
                values[field] = int(values[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} 必须是整数") from exc
            if values[field] < (0 if field.startswith("disk_") else 1):
                raise ValueError(f"{field} 的数值不正确")
        if values["disk_warning_gb"] and values["disk_stop_gb"] > values["disk_warning_gb"]:
            raise ValueError("停止录制阈值不能高于空间预警阈值")
        for field in BOOL_FIELDS:
            values[field] = bool(values[field])
        values["output_path"] = str(values["output_path"]).strip()
        values["proxy_address"] = str(values["proxy_address"]).strip()
        return values


class RecorderProcess:
    def __init__(self, project_root: Path, on_log: Callable[[str], None] | None = None, resolve_anchor_id: Callable[[str], str | None] | None = None):
        self.project_root = project_root
        self.on_log = on_log
        self.resolve_anchor_id = resolve_anchor_id
        self.process: subprocess.Popen[str] | None = None
        self.started_at: float | None = None
        self.logs: deque[str] = deque(maxlen=1200)
        self._log_offset = 0
        self._douyin_cookie = ""
        self._room_states: dict[str, dict] = {}
        self._room_state_keys: dict[str, str] = {}
        self._lock = threading.RLock()
        self._desired_running = False
        self._restart_attempts = 0
        self._last_exit_code: int | None = None
        self._restart_timer: threading.Timer | None = None
        self._missed_incidents: deque[dict] = deque(maxlen=100)
        self.missed_recording_threshold = 120
        self.recording_stale_threshold = 90
        self.finalizing_display_seconds = 15

    def _transition_room(self, key: str, name: str, state: str, **details) -> dict:
        previous = self._room_states.get(key, {})
        now = time.time()
        changed = previous.get("state") != state
        history = list(previous.get("history") or [])
        if changed:
            history.append({"state": state, "at": now})
            history = history[-20:]
        value = {
            **previous, **details, "anchor_id": key if key != name else "", "name": name,
            "state": state, "stage": state, "updated_at": now, "history": history,
        }
        self._room_states[key] = value
        return value

    def set_douyin_cookie(self, cookie: str) -> None:
        """Keep the browser session in memory and pass it only to the recorder child."""
        with self._lock:
            value = cookie.strip()
            if value == self._douyin_cookie:
                return
            if self.is_running:
                self._send_control({"action": "auth", "cookie": value})
                self._append_log("桌面控制台：登录状态已热更新，下次拉流使用新凭据")
            self._douyin_cookie = value

    def _send_control(self, command: dict) -> None:
        with self._lock:
            if not self.is_running or not self.process.stdin:
                raise RuntimeError("录制服务未运行，无法发送重试指令")
            try:
                self.process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise RuntimeError("录制服务控制通道不可用，请重新启动录制服务") from exc

    def retry_anchor(self, anchor: dict, reason: str = "手动立即重试") -> bool:
        with self._lock:
            key = anchor['id']
            previous = self._room_states.get(key, {})
            now = time.time()
            # A manual retry must never interrupt a healthy capture.
            if previous.get('state') == 'recording' and now - float(previous.get('last_file_growth_at') or 0) < self.recording_stale_threshold:
                return False
            if now - float(previous.get('last_retry_at') or 0) < 30:
                return False
            url = str(anchor.get('live_url') or '')
            if not url:
                raise ValueError("未获得直播间地址，暂时无法重试")
            identity = {
                key: str(anchor.get(key) or '').strip()
                for key in ('room_id', 'sec_user_id')
                if str(anchor.get(key) or '').strip()
            }
            if identity.get('sec_user_id'):
                parsed = urllib.parse.urlparse(url)
                query = urllib.parse.parse_qs(parsed.query)
                query.update({f'lr_{key}': [value] for key, value in identity.items()})
                url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
            if anchor.get('anonymous_recording', False):
                parsed = urllib.parse.urlparse(url)
                query = urllib.parse.parse_qs(parsed.query)
                query['lr_anonymous_recording'] = ['1']
                url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))
            self._send_control({'action': 'retry', 'url': url})
            self._transition_room(key, anchor['name'], 'reconnecting', last_retry_at=now,
                                  retry_count=int(previous.get('retry_count') or 0) + 1,
                                  error=reason + '，已唤醒该主播的录制检查')
            self._append_log(f"桌面控制台：{anchor['name']} {reason}")
            return True

    def observe_anchor(self, anchor: dict) -> None:
        """Independent profile evidence catches failures before engine logs 'live'."""
        with self._lock:
            if not self.is_running or not anchor.get('enabled_recording', True):
                return
            self._refresh_room_health()
            key = anchor['id']
            previous = self._room_states.get(key, {})
            if anchor.get('last_live_status') != 'live':
                previous.pop('profile_live_since', None)
                return
            since = previous.get('profile_live_since') or time.time()
            previous['profile_checked_at'] = time.time()
            if previous.get('state') not in {'recording', 'finalizing'}:
                previous = self._transition_room(key, anchor['name'], 'live',
                    live_detected_at=since, profile_live_since=since, profile_checked_at=time.time())
            else:
                previous['profile_live_since'] = since
            self._refresh_room_health()
            self._refresh_missed_recordings()
            # A profile check is independent of the recorder engine's slower
            # polling loop. Wake the room worker as soon as it confirms a live
            # session; otherwise a room still marked "waiting" may not be
            # checked by the engine for several minutes.
            current_state = self._room_states.get(key, {}).get('state')
            if current_state in {'live', 'missed', 'reconnecting'}:
                self.retry_anchor(anchor, '检测到开播但未正常写入，自动恢复')

    @property
    def has_douyin_session(self) -> bool:
        return bool(self._douyin_cookie)

    def _append_log(self, line: str) -> None:
        line = line.rstrip()
        if line:
            with self._lock:
                self._track_room_state(line)
            if self.logs.maxlen and len(self.logs) == self.logs.maxlen:
                self._log_offset += 1
            self.logs.append(line)
            if self.on_log:
                self.on_log(line)

    def _track_room_state(self, line: str) -> None:
        started = re.search(r"(?P<name>.+?)\s+准备开始录制(?:视频|音频):\s*(?P<path>.+)$", line.strip())
        if started:
            name = normalize_recorder_anchor_name(started.group("name"))
            key = (self.resolve_anchor_id(name) if self.resolve_anchor_id else None) or name
            self._room_state_keys[name] = key
            self._transition_room(key, name, "recording", started_at=time.time(), path=started.group("path").strip(),
                                  last_file_size=0, last_file_growth_at=time.time(), suspected_missed=False)
            return
        completed = re.search(
            r"(?P<name>.+?)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+直播录制完成",
            line.strip(),
        )
        if completed:
            name = normalize_recorder_anchor_name(completed.group("name"))
            key = self._room_state_keys.get(name) or ((self.resolve_anchor_id(name) if self.resolve_anchor_id else None) or name)
            self._transition_room(key, name, "finalizing", completed_at=time.time())
            return
        waiting = re.search(r"(?P<name>.+?)\s+等待直播", line.strip())
        if waiting:
            name = normalize_recorder_anchor_name(waiting.group("name"))
            key = self._room_state_keys.get(name) or ((self.resolve_anchor_id(name) if self.resolve_anchor_id else None) or name)
            self._room_state_keys[name] = key
            previous = self._room_states.get(key, {})
            if previous.get('profile_live_since') and time.time() - previous.get('profile_checked_at', 0) < 120:
                self._transition_room(key, name, 'reconnecting',
                    error='近期检测到开播，但录制接口返回未开播，正在重新核验', path='')
                return
            self._transition_room(key, name, "waiting", offline_detected_at=time.time(), path="")
            return
        failed = re.search(r"(?P<name>.+?)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+直播录制出错", line.strip())
        if failed:
            name = normalize_recorder_anchor_name(failed.group("name"))
            key = self._room_state_keys.get(name) or ((self.resolve_anchor_id(name) if self.resolve_anchor_id else None) or name)
            self._transition_room(key, name, "reconnecting", error="直播流中断，等待自动重连", reconnecting_at=time.time())
            return
        live = re.search(r"(?P<name>.+?)\s+正在直播中", line.strip())
        if live:
            name = normalize_recorder_anchor_name(live.group("name"))
            key = self._room_state_keys.get(name) or ((self.resolve_anchor_id(name) if self.resolve_anchor_id else None) or name)
            self._room_state_keys[name] = key
            previous = self._room_states.get(key, {})
            if previous.get("state") != "recording":
                self._transition_room(key, name, "live", live_detected_at=previous.get("live_detected_at") or time.time())

    @staticmethod
    def _recording_size(path_value: str) -> int | None:
        path = Path(path_value)
        try:
            if "%" not in path.name:
                return path.stat().st_size if path.exists() else None
            pattern = re.sub(r"%0?\d*d", "*", path.name)
            files = list(path.parent.glob(pattern))
            return sum(item.stat().st_size for item in files if item.is_file()) if files else None
        except OSError:
            return None

    def _refresh_room_health(self) -> None:
        now = time.time()
        for key, state in list(self._room_states.items()):
            if state.get("state") == "finalizing" and now - float(state.get("completed_at") or now) >= self.finalizing_display_seconds:
                self._transition_room(key, str(state.get("name") or key), "waiting", path="")
                continue
            if state.get("state") not in {"recording", "reconnecting"} or not state.get("path"):
                continue
            size = self._recording_size(str(state["path"]))
            if size is None:
                size = 0
            previous_size = int(state.get("last_file_size") or 0)
            if size > previous_size:
                state.update({"last_file_size": size, "last_file_growth_at": now, "updated_at": now})
                if state.get("state") == "reconnecting":
                    self._transition_room(key, str(state.get("name") or key), "recording", error="")
            elif now - float(state.get("last_file_growth_at") or state.get("started_at") or now) >= self.recording_stale_threshold:
                self._transition_room(key, str(state.get("name") or key), "reconnecting", error="录像文件停止增长，正在等待拉流恢复", reconnecting_at=now)

    def _refresh_missed_recordings(self) -> None:
        now = time.time()
        for key, state in list(self._room_states.items()):
            detected_at = float(state.get("live_detected_at") or 0)
            if state.get("state") != "live" or not detected_at or now - detected_at < self.missed_recording_threshold:
                continue
            state.update({"state": "missed", "suspected_missed": True, "suspected_at": now, "updated_at": now})
            incident = {
                "anchor_id": state.get("anchor_id") or key,
                "name": state.get("name") or key,
                "detected_at": detected_at,
                "suspected_at": now,
                "reason": "检测到开播后未在规定时间内开始录制",
            }
            if not any(item['anchor_id'] == incident['anchor_id'] and item['detected_at'] == detected_at for item in self._missed_incidents):
                self._missed_incidents.append(incident)
                self._append_log(f"桌面控制台：疑似漏录：{incident['name']} 已开播但尚未开始写入录像")

    def preflight(self) -> list[str]:
        missing = []
        if shutil.which("ffmpeg") is None and not (self.project_root / "ffmpeg.exe").exists():
            missing.append("FFmpeg")
        if shutil.which("node") is None:
            missing.append("Node.js")
        return missing

    def start(self) -> None:
        with self._lock:
            if self.is_running:
                raise RuntimeError("录制服务已经在运行")
            self._desired_running = True
            self._restart_attempts = 0
            self._launch()

    def _launch(self) -> None:
        with self._lock:
            if self.is_running or not self._desired_running:
                return
            self._room_states.clear()
            self._room_state_keys.clear()
            missing = self.preflight()
            if missing:
                raise RuntimeError("缺少运行依赖：" + "、".join(missing))
            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            environment["LIVERECORDER_CONTROL_PIPE"] = "1"
            if self._douyin_cookie:
                environment["LIVERECORDER_DOUYIN_COOKIE"] = self._douyin_cookie
            else:
                environment.pop("LIVERECORDER_DOUYIN_COOKIE", None)
            packaged_engine = os.environ.get("LIVERECORDER_ENGINE_EXECUTABLE", "").strip()
            command = [packaged_engine, "--engine"] if packaged_engine else [
                sys.executable, "-u", str(self.project_root / "main.py")
            ]
            self.process = subprocess.Popen(
                command,
                cwd=self.project_root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                env=environment,
                **kwargs,
            )
            self.started_at = time.time()
            self._append_log("桌面控制台：录制服务已启动")
            threading.Thread(target=self._read_output, args=(self.process,), daemon=True).start()

    def _read_output(self, process: subprocess.Popen[str]) -> None:
        if not process or not process.stdout:
            return
        for line in process.stdout:
            self._append_log(line)
        code = process.wait()
        if self.process is not process:
            return
        self._last_exit_code = code
        for state in self._room_states.values():
            state.update({"state": "stopped", "updated_at": time.time()})
        self._append_log(f"桌面控制台：录制服务已退出（代码 {code}）")
        with self._lock:
            should_restart = self._desired_running
            if should_restart:
                self._restart_attempts += 1
                delay = min(60, 2 ** min(self._restart_attempts, 5))
                self._append_log(f"桌面控制台：录制服务异常中断，{delay} 秒后自动恢复（第 {self._restart_attempts} 次）")
                self._restart_timer = threading.Timer(delay, self._restart_after_exit)
                self._restart_timer.daemon = True
                self._restart_timer.start()

    def _restart_after_exit(self) -> None:
        try:
            self._launch()
        except Exception as exc:
            self._append_log(f"桌面控制台：录制服务自动恢复失败：{exc}")
            with self._lock:
                if self._desired_running:
                    self._restart_attempts += 1
                    delay = min(60, 2 ** min(self._restart_attempts, 5))
                    self._restart_timer = threading.Timer(delay, self._restart_after_exit)
                    self._restart_timer.daemon = True
                    self._restart_timer.start()

    def stop(self) -> None:
        with self._lock:
            self._desired_running = False
            if self._restart_timer:
                self._restart_timer.cancel()
                self._restart_timer = None
            process = self.process
            if not process or process.poll() is not None:
                return
            self._append_log("桌面控制台：正在安全停止并封装视频…")
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=12)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                if process.poll() is None:
                    if os.name == "nt":
                        process.terminate()
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def status(self) -> dict:
        with self._lock:
            return self._status_snapshot()

    def _status_snapshot(self) -> dict:
        self._refresh_room_health()
        self._refresh_missed_recordings()
        return {
            "running": self.is_running,
            "pid": self.process.pid if self.is_running and self.process else None,
            "started_at": self.started_at if self.is_running else None,
            "missing_dependencies": self.preflight(),
            "room_states": {anchor_id: dict(value) for anchor_id, value in self._room_states.items()},
            "auto_recovery": {
                "enabled": self._desired_running,
                "restart_attempts": self._restart_attempts,
                "last_exit_code": self._last_exit_code,
                "recovering": bool(self._desired_running and not self.is_running),
            },
            "missed_recordings": list(self._missed_incidents),
        }

    @staticmethod
    def _is_key_log(line: str) -> bool:
        markers = (
            "桌面控制台：", "准备开始录制", "直播录制完成", "正在直播中",
            "错误", "失败", "异常", "Error", "Traceback",
        )
        return any(marker in line for marker in markers)

    def log_snapshot(self, after: int = 0, important_only: bool = False) -> dict:
        lines = list(self.logs)
        start = max(0, min(after - self._log_offset, len(lines)))
        selected = lines[start:]
        if important_only:
            selected = [line for line in selected if self._is_key_log(line)]
        return {"lines": selected, "cursor": self._log_offset + len(lines)}
