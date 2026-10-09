"""Run the LiveRecorder local visual control panel."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from desktop_anchors import AnchorStore
from desktop_baidupan import BaiduPanUploadManager
from desktop_core import RecorderProcess, RoomStore, SettingsStore
from desktop_media_library import MediaLibrary, RecentRecordingCache, group_recordings, scan_recordings
from desktop_update import UpdateManager
from desktop_work_pull import WorkPullManager


BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PROJECT_ROOT = Path(os.environ.get("LIVERECORDER_DATA_ROOT", Path(__file__).resolve().parent)).resolve()
STATIC_FILE = BUNDLE_ROOT / "desktop" / "index.html"
APP_VERSION = os.environ.get("BOLU_APP_VERSION") or os.environ.get("npm_package_version") or "0.1.0"
BUILD_COMMIT = os.environ.get("BOLU_BUILD_COMMIT", "").strip()


class LazyDouyinInteraction:
    def __init__(self):
        self._manager = None
        self._cookie = ""
        self._security: dict = {}

    def _load(self):
        if self._manager is None:
            from desktop_douyin import DouyinInteractionManager

            self._manager = DouyinInteractionManager()
            if self._cookie or self._security:
                self._manager.set_auth(self._cookie, self._security)
        return self._manager

    def set_auth(self, cookie: str, security: dict | None = None) -> None:
        self._cookie = cookie
        self._security = security or {}
        if self._manager is not None:
            self._manager.set_auth(cookie, self._security)

    def status(self) -> dict:
        if self._manager is None:
            return {
                "connected": bool(self._cookie),
                "access_mode": "authenticated" if self._cookie else "anonymous",
                "public_access": True,
                "listening": False,
                "room_url": "",
                "can_send": bool(
                    self._cookie
                    and self._security.get("ticket")
                    and self._security.get("ts_sign")
                    and self._security.get("private_key")
                ),
                "audio_playing": False,
            }
        return self._manager.status()

    def events(self, cursor: int = 0) -> dict:
        return {"cursor": 0, "events": []} if self._manager is None else self._manager.events(cursor)

    def start_listening(self, room_url: str) -> dict:
        return self._load().start_listening(room_url)

    def stop_listening(self) -> dict:
        return self.status() if self._manager is None else self._manager.stop_listening()

    def send_chat(self, content: str) -> dict:
        return self._load().send_chat(content)

    def audio_source(self, room_url: str, quality: str = "原画") -> dict:
        return self._load().audio_source(room_url, quality)

    def start_audio_stream(self, stream_id: str):
        return self._load().start_audio_stream(stream_id)

    def finish_audio_stream(self, process) -> None:
        if self._manager is not None:
            self._manager.finish_audio_stream(process)

    def stop_audio(self) -> None:
        if self._manager is not None:
            self._manager.stop_audio()

    def gift_rank(self, room_url: str) -> dict:
        return self._load().gift_rank(room_url)

    def resolve_live_room(self, value: str) -> dict:
        return self._load().resolve_live_room(value)


class AppState:
    def __init__(self):
        self.rooms = RoomStore(PROJECT_ROOT / "config" / "URL_config.ini")
        self.anchors = AnchorStore(PROJECT_ROOT / "config" / "anchors.json")
        self.settings = SettingsStore(PROJECT_ROOT / "config" / "config.ini")
        self.updates = UpdateManager(PROJECT_ROOT / "config" / "update.json", APP_VERSION, BUILD_COMMIT)
        self.uploads = BaiduPanUploadManager(PROJECT_ROOT, BUNDLE_ROOT)
        self._last_recording_candidate: dict | None = None
        self._recordings = RecentRecordingCache()
        self.recorder = RecorderProcess(PROJECT_ROOT, on_log=self._on_recorder_log)
        self.interaction = LazyDouyinInteraction()
        self.work_pull = WorkPullManager(PROJECT_ROOT / "douyin_work_pull" / "state.json", self.output_path())

    def _on_recorder_log(self, line: str) -> None:
        candidate_match = re.search(r"(?P<name>.+?)\s+准备开始录制(?:视频|音频):\s*(?P<path>.+)$", line.strip())
        if candidate_match:
            self._last_recording_candidate = {
                "record_name": candidate_match.group("name").strip(),
                "save_file_path": candidate_match.group("path").strip(),
                "created_at": time.time(),
            }
            return
        if "直播录制完成" not in line:
            return
        config = self.uploads.load_config()
        if not (config.get("enabled") and config.get("auto_upload")):
            return
        candidate = self._last_recording_candidate
        if not candidate or time.time() - float(candidate.get("created_at") or 0) > 24 * 3600:
            return
        settings = self.settings.load()
        try:
            self.uploads.enqueue_recording(
                str(candidate.get("save_file_path") or ""),
                record_name=str(candidate.get("record_name") or ""),
                save_type=str(settings.get("format") or ""),
                split_video_by_time=bool(settings.get("split_enabled")),
                converts_to_mp4=bool(settings.get("convert_to_mp4")),
                source="recording",
            )
        except Exception as exc:
            self.recorder._append_log(f"桌面控制台：录制完成后加入百度网盘上传队列失败：{exc}")

    def media_library(self) -> dict:
        return MediaLibrary(self.output_path()).scan()

    def check_anchors_live_status(self) -> dict:
        results = []
        for anchor in self.anchors.list():
            anchor_id = anchor.get("id", "")
            value = str(anchor.get("profile_url") or anchor.get("live_url") or "").strip()
            updates = {"last_resolved_at": int(time.time()), "last_check_error": ""}
            live_room = None
            try:
                live_room = self.interaction.resolve_live_room(value)
                updates.update({
                    "live_url": live_room.get("room_url") or anchor.get("live_url", ""),
                    "web_rid": live_room.get("web_rid", ""),
                    "room_id": live_room.get("room_id", ""),
                    "last_live_status": "live" if live_room.get("is_live") else "offline",
                })
                if live_room.get("nickname"):
                    updates["name"] = live_room["nickname"]
                updated = self.anchors.update(anchor_id, updates)
                results.append({"anchor": updated, "live_room": live_room, "ok": True})
            except Exception as exc:
                updates.update({"last_live_status": "error", "last_check_error": str(exc)})
                try:
                    updated = self.anchors.update(anchor_id, updates)
                except Exception:
                    updated = anchor
                results.append({"anchor": updated, "live_room": None, "ok": False, "error": str(exc)})
        return {"results": results, "anchors": self.anchors.list(), "checked_at": int(time.time())}

    def recordings(self, force: bool = False) -> list[dict]:
        settings = self.settings.load()
        root = Path(settings["output_path"]) if settings["output_path"] else PROJECT_ROOT / "downloads"
        return self._recordings.get(root, force=force)

    def recording_archive_groups(self) -> list[dict]:
        return group_recordings(scan_recordings(self.output_path(), limit=None))

    def output_path(self) -> Path:
        configured = self.settings.load()["output_path"]
        return Path(configured) if configured else PROJECT_ROOT / "downloads"

def open_in_file_manager(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def make_handler(state: AppState, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LiveRecorderDesktop/1.0"

        def log_message(self, _format: str, *args) -> None:
            return

        def _authorized(self) -> bool:
            query_token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
            return secrets.compare_digest(self.headers.get("X-LiveRecorder-Token", "") or query_token, token)

        def _json(self, payload, status=HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("请求内容过大")
            return json.loads(self.rfile.read(length) or b"{}")

        def _route(self) -> tuple[str, list[str]]:
            path = urlparse(self.path).path.rstrip("/") or "/"
            return path, [part for part in path.split("/") if part]

        def do_GET(self) -> None:
            if not self._authorized():
                self._json({"error": "未授权"}, HTTPStatus.FORBIDDEN)
                return
            path, _ = self._route()
            try:
                if path == "/":
                    body = STATIC_FILE.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/state":
                    recordings = state.recordings()
                    self._json({
                        "rooms": state.rooms.list(),
                        "anchors": state.anchors.list(),
                        "settings": state.settings.load(),
                        "status": state.recorder.status(),
                        "baidupan": state.uploads.status(),
                        "auth": {"douyin_connected": state.recorder.has_douyin_session},
                        "update": state.updates.status(),
                        "interaction": state.interaction.status(),
                        "work_pull": state.work_pull.status(),
                        "recordings": recordings,
                        "recording_groups": group_recordings(recordings),
                    })
                elif path == "/api/logs":
                    query = parse_qs(urlparse(self.path).query)
                    cursor = int(query.get("cursor", ["0"])[0])
                    detailed = query.get("detail", ["0"])[0] == "1"
                    self._json(state.recorder.log_snapshot(cursor, important_only=not detailed))
                elif path == "/api/interaction/events":
                    cursor = int(parse_qs(urlparse(self.path).query).get("cursor", ["0"])[0])
                    self._json(state.interaction.events(cursor))
                elif path == "/api/interaction/audio-stream":
                    stream_id = parse_qs(urlparse(self.path).query).get("id", [""])[0]
                    process = state.interaction.start_audio_stream(stream_id)
                    if not process.stdout:
                        state.interaction.finish_audio_stream(process)
                        raise RuntimeError("无法读取 FFmpeg 音频输出")
                    first_chunk = process.stdout.read(4096)
                    if not first_chunk:
                        state.interaction.finish_audio_stream(process)
                        raise RuntimeError("FFmpeg 未能转换直播音频，请重新获取音频源")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "audio/mpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    try:
                        self.wfile.write(first_chunk)
                        while True:
                            chunk = process.stdout.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    except (ConnectionResetError, OSError):
                        pass
                    finally:
                        state.interaction.finish_audio_stream(process)
                elif path == "/api/work-pull/logs":
                    cursor = int(parse_qs(urlparse(self.path).query).get("cursor", ["0"])[0])
                    self._json(state.work_pull.logs(cursor))
                elif path == "/api/baidupan/logs":
                    cursor = int(parse_qs(urlparse(self.path).query).get("cursor", ["0"])[0])
                    self._json(state.uploads.logs_snapshot(cursor))
                elif path == "/api/media-library":
                    self._json({"library": state.media_library()})
                elif path == "/api/anchors":
                    self._json({"anchors": state.anchors.list()})
                else:
                    self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            if not self._authorized():
                self._json({"error": "未授权"}, HTTPStatus.FORBIDDEN)
                return
            path, parts = self._route()
            try:
                body = self._body()
                if path == "/api/rooms":
                    state.rooms.add(body.get("value", ""))
                    self._json({"rooms": state.rooms.list()}, HTTPStatus.CREATED)
                elif path == "/api/anchors":
                    anchor = state.anchors.add(
                        str(body.get("name", "")),
                        str(body.get("profile_url", "")),
                        str(body.get("live_url", "")),
                    )
                    self._json({"anchor": anchor, "anchors": state.anchors.list()}, HTTPStatus.CREATED)
                elif len(parts) == 4 and parts[:2] == ["api", "anchors"] and parts[3] == "resolve":
                    anchor_id = parts[2]
                    anchor = next((item for item in state.anchors.list() if item.get("id") == anchor_id), None)
                    if not anchor:
                        raise IndexError("主播不存在")
                    live_room = state.interaction.resolve_live_room(str(anchor.get("profile_url") or anchor.get("live_url") or ""))
                    updates = {
                        "live_url": live_room.get("room_url") or anchor.get("live_url", ""),
                        "web_rid": live_room.get("web_rid", ""),
                        "room_id": live_room.get("room_id", ""),
                        "last_live_status": "live" if live_room.get("is_live") else "offline",
                        "last_resolved_at": int(time.time()),
                    }
                    if live_room.get("nickname"):
                        updates["name"] = live_room["nickname"]
                    anchor = state.anchors.update(anchor_id, updates)
                    self._json({"anchor": anchor, "live_room": live_room, "anchors": state.anchors.list()})
                elif len(parts) == 4 and parts[:2] == ["api", "anchors"] and parts[3] == "use-recording":
                    anchor_id = parts[2]
                    anchor = next((item for item in state.anchors.list() if item.get("id") == anchor_id), None)
                    if not anchor:
                        raise IndexError("主播不存在")
                    live_url = str(anchor.get("live_url") or "").strip()
                    live_room = None
                    if not live_url:
                        profile_url = str(anchor.get("profile_url") or "").strip()
                        if "live.douyin.com/" in profile_url:
                            live_url = profile_url.split("?")[0]
                            anchor = state.anchors.update(anchor_id, {"live_url": live_url, "last_resolved_at": int(time.time())})
                        else:
                            live_room = state.interaction.resolve_live_room(profile_url)
                            live_url = str(live_room.get("room_url") or "").strip()
                            updates = {
                                "live_url": live_url,
                                "web_rid": live_room.get("web_rid", ""),
                                "room_id": live_room.get("room_id", ""),
                                "last_live_status": "live" if live_room.get("is_live") else "offline",
                                "last_resolved_at": int(time.time()),
                            }
                            if live_room.get("nickname"):
                                updates["name"] = live_room["nickname"]
                            anchor = state.anchors.update(anchor_id, updates)
                    if not live_url:
                        raise ValueError("该主播还没有可用直播间地址，请先解析直播间")
                    room = state.rooms.upsert_active(live_url)
                    self._json({"anchor": anchor, "room": room, "rooms": state.rooms.list(), "live_room": live_room})
                elif path == "/api/anchors/check-live":
                    self._json(state.check_anchors_live_status())
                elif len(parts) == 3 and parts[:2] == ["api", "rooms"]:
                    if state.recorder.is_running:
                        raise RuntimeError("录制期间不可启用或暂停直播间，请先停止并保存")
                    state.rooms.set_active(int(parts[2]), bool(body.get("active")))
                    self._json({"rooms": state.rooms.list()})
                elif path == "/api/settings":
                    self._json({"settings": state.settings.save(body)})
                elif path == "/api/update/settings":
                    self._json({"update": state.updates.save_config(str(body.get("manifest_url", "")))})
                elif path == "/api/update/check":
                    self._json(state.updates.check(str(body.get("manifest_url", ""))))
                elif path == "/api/update/open-download":
                    self._json(state.updates.open_download(str(body.get("url", ""))))
                elif path == "/api/baidupan/settings":
                    self._json({"baidupan": state.uploads.save_config(body), "status": state.uploads.status()})
                elif path == "/api/baidupan/check":
                    self._json({"check": state.uploads.check_auth(), "baidupan": state.uploads.status()})
                elif path == "/api/baidupan/auth/start":
                    self._json({"auth": state.uploads.start_auth(), "baidupan": state.uploads.status()})
                elif path == "/api/baidupan/auth/submit":
                    self._json({"auth": state.uploads.submit_auth_code(str(body.get("code", ""))), "baidupan": state.uploads.status()})
                elif path == "/api/baidupan/enqueue":
                    item = state.uploads.enqueue_recording(
                        str(body.get("save_file_path", "")),
                        record_name=str(body.get("record_name", "")),
                        save_type=str(body.get("save_type", "")),
                        split_video_by_time=bool(body.get("split_video_by_time")),
                        converts_to_mp4=bool(body.get("converts_to_mp4")),
                        source=str(body.get("source", "manual")),
                    )
                    self._json({"item": item, "baidupan": state.uploads.status()}, HTTPStatus.CREATED)
                elif path == "/api/baidupan/enqueue-archive":
                    self._json(state.uploads.enqueue_archive(state.recording_archive_groups()), HTTPStatus.CREATED)
                elif len(parts) == 4 and parts[:2] == ["api", "baidupan"] and parts[3] == "retry":
                    item = state.uploads.retry(parts[2])
                    self._json({"item": item, "baidupan": state.uploads.status()})
                elif path == "/api/baidupan/clear-finished":
                    self._json({"baidupan": state.uploads.clear_finished()})
                elif path == "/api/start":
                    if not any(room["active"] for room in state.rooms.list()):
                        raise ValueError("请至少启用一个直播间")
                    state.settings.save(body.get("settings", {}))
                    state.recorder.start()
                    self._json({"status": state.recorder.status()})
                elif path == "/api/stop":
                    state.recorder.stop()
                    state._recordings.invalidate()
                    self._json({"status": state.recorder.status()})
                elif path == "/api/open-output":
                    open_in_file_manager(state.output_path())
                    self._json({"ok": True})
                elif path == "/api/open-work-output":
                    target = Path(str(body.get("output_path", "")).strip()).expanduser() if str(body.get("output_path", "")).strip() else state.output_path()
                    open_in_file_manager(target / "douyin_works")
                    self._json({"ok": True})
                elif path == "/api/open-media-folder":
                    folder = Path(str(body.get("folder", "")).strip()).expanduser()
                    if not folder:
                        raise ValueError("目录不能为空")
                    if not folder.exists() or not folder.is_dir():
                        raise ValueError("目录不存在")
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", str(folder)])
                    elif os.name == "nt":
                        os.startfile(str(folder))  # type: ignore[attr-defined]
                    else:
                        subprocess.Popen(["xdg-open", str(folder)])
                    self._json({"ok": True})
                elif path == "/api/auth/douyin":
                    state.recorder.set_douyin_cookie(str(body.get("cookie", "")))
                    state.interaction.set_auth(str(body.get("cookie", "")), body.get("security") or {})
                    state.work_pull.set_auth(str(body.get("cookie", "")))
                    self._json({"connected": state.recorder.has_douyin_session})
                elif path == "/api/interaction/start":
                    self._json({"interaction": state.interaction.start_listening(str(body.get("room_url", "")))})
                elif path == "/api/interaction/stop":
                    self._json({"interaction": state.interaction.stop_listening()})
                elif path == "/api/interaction/send":
                    self._json(state.interaction.send_chat(str(body.get("content", ""))))
                elif path == "/api/interaction/audio-source":
                    self._json({
                        "audio": state.interaction.audio_source(
                            str(body.get("room_url", "")),
                            str(body.get("quality", "原画")),
                        )
                    })
                elif path == "/api/interaction/audio-stop":
                    state.interaction.stop_audio()
                    self._json({"ok": True})
                elif path == "/api/interaction/gift-rank":
                    self._json({"gift_rank": state.interaction.gift_rank(str(body.get("room_url", "")))})
                elif path == "/api/douyin/resolve-live-room":
                    self._json({"live_room": state.interaction.resolve_live_room(str(body.get("url", "")))})
                elif path == "/api/work-pull/start":
                    self._json({
                        "work_pull": state.work_pull.start(
                            str(body.get("user_url", "")),
                            str(body.get("output_path", "") or state.output_path()),
                            bool(body.get("force")),
                        )
                    }, HTTPStatus.CREATED)
                else:
                    self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

        def do_DELETE(self) -> None:
            if not self._authorized():
                self._json({"error": "未授权"}, HTTPStatus.FORBIDDEN)
                return
            _, parts = self._route()
            try:
                if len(parts) == 3 and parts[:2] == ["api", "rooms"]:
                    if state.recorder.is_running:
                        raise RuntimeError("录制期间不可删除直播间，请先停止并保存")
                    state.rooms.delete(int(parts[2]))
                    self._json({"rooms": state.rooms.list()})
                elif len(parts) == 3 and parts[:2] == ["api", "anchors"]:
                    state.anchors.delete(parts[2])
                    self._json({"anchors": state.anchors.list()})
                else:
                    self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="LiveRecorder 本地可视化控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17860, help="传入 0 可随机选择空闲端口")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--ready-file", default="", help="启动完成后写入本地访问 URL")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("桌面控制台仅允许监听本机地址")
    if not STATIC_FILE.exists():
        parser.error(f"缺少界面文件：{STATIC_FILE}")

    token = secrets.token_urlsafe(24)
    state = AppState()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state, token))
    url = f"http://127.0.0.1:{server.server_port}/?token={token}"
    print(f"LiveRecorder 桌面控制台：{url}", flush=True)
    if args.ready_file:
        ready_path = Path(args.ready_file)
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = ready_path.with_suffix(ready_path.suffix + ".tmp")
        temporary.write_text(url, encoding="utf-8")
        os.replace(temporary, ready_path)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.recorder.stop()
        state.interaction.stop_audio()
        state.interaction.stop_listening()
        server.server_close()


if __name__ == "__main__":
    main()
