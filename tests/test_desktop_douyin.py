import gzip
import unittest
from unittest.mock import AsyncMock, patch

from desktop_douyin import (
    DouyinAuthState,
    DouyinInteractionManager,
    DouyinLiveSession,
    LiveRoomInfo,
    _audio_relay_command,
    _decode_live_response,
    extract_douyin_share_url,
    fetch_live_room_info,
    resolve_live_room,
    search_douyin_users,
)
from douyin_static import Live_pb2


PROFILE_URL = (
    "https://www.douyin.com/user/"
    "MS4wLjABAAAAgbRE2r0x59BHXG05lLRtBJ66RE3eiJ_xXqnIFhQGg8rUOYXgTuU6OO6u4Ry6gKYU"
)


class FakeResponse:
    def __init__(self, payload=None, text="", cookies=None):
        self._payload = payload or {}
        self.text = text
        cookie_values = cookies or {}
        self.cookies = type("Cookies", (), {"get_dict": lambda self: cookie_values})()

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DouyinProfileResolverTest(unittest.TestCase):
    def test_new_gift_message_variants_are_not_silently_ignored(self):
        events = []
        session = DouyinLiveSession("https://live.douyin.com/1", DouyinAuthState.from_cookie(""), events.append)
        gift = Live_pb2.GiftMessage()
        gift.giftId = "88"
        gift.comboCount = 2
        gift.gift.id = 88
        gift.gift.name = "小心心"
        item = Live_pb2.Message(method="WebcastGiftMessageV2", payload=gift.SerializeToString())

        session._handle_message(item)

        self.assertEqual("gift", events[0]["type"])
        self.assertEqual("WebcastGiftMessageV2", events[0]["source_method"])
        self.assertEqual(2, events[0]["combo_count"])

    def test_extracts_short_url_from_mobile_share_text(self):
        text = "复制此链接，打开抖音搜索 https://v.douyin.com/AbCd12/ 8@1.com"
        self.assertEqual("https://v.douyin.com/AbCd12/", extract_douyin_share_url(text))

    def test_extracts_url_without_trailing_chinese_punctuation(self):
        self.assertEqual(PROFILE_URL, extract_douyin_share_url(f"分享主播主页：{PROFILE_URL}，欢迎关注"))

    @patch("desktop_douyin.requests.get")
    def test_offline_profile_still_returns_stable_live_url(self, request_get):
        request_get.return_value = FakeResponse(
            {
                "status_code": 0,
                "user": {
                    "nickname": "O泡",
                    "unique_id": "200612o4",
                    "short_id": "0",
                    "uid": "7476439385123636282",
                    "sec_uid": PROFILE_URL.rsplit("/", 1)[-1],
                    "room_id": 0,
                    "room_id_str": "0",
                    "live_status": 0,
                },
            }
        )

        result = resolve_live_room(DouyinAuthState.from_cookie("ttwid=value"), PROFILE_URL)

        self.assertFalse(result["is_live"])
        self.assertEqual("O泡", result["nickname"])
        self.assertEqual("https://live.douyin.com/200612o4", result["room_url"])
        self.assertIn("当前未开播", result["message"])

    @patch("desktop_douyin._a_bogus", return_value="signed")
    @patch("desktop_douyin.requests.get")
    def test_user_search_normalizes_nested_candidates(self, request_get, _sign):
        request_get.return_value = FakeResponse({"status_code": 0, "data": [{"user_list": [{"user_info": {
            "nickname": "晚风电台", "unique_id": "wanfengFM", "sec_uid": "MS4wLjAB-search-result",
            "signature": "睡前聊天", "follower_count": "12345", "live_status": 1,
            "avatar_thumb": {"url_list": ["https://example.com/avatar.jpg"]},
        }}]}]})

        users = search_douyin_users(DouyinAuthState.from_cookie("sessionid_ss=token"), "晚风", 10)

        self.assertEqual(1, len(users))
        self.assertEqual("晚风电台", users[0]["nickname"])
        self.assertEqual("wanfengFM", users[0]["display_id"])
        self.assertEqual(12345, users[0]["follower_count"])
        self.assertTrue(users[0]["is_live"])
        self.assertTrue(users[0]["profile_url"].endswith("MS4wLjAB-search-result"))
        self.assertEqual("aweme_user_web", request_get.call_args.kwargs["params"]["search_channel"])

    @patch("desktop_douyin.requests.get")
    def test_current_live_page_script_without_nonce_is_supported(self, request_get):
        script = (
            r'self.__pace_f.push([1,"roomStore\":{\"roomInfo\":{\"room\":{'
            r'\"id_str\":\"7663365710281870121\",\"status\":4,'
            r'\"status_str\":\"4\",\"title\":\"随便刷\"}},'
            r'\"roomId\":\"7663365710281870121\",\"web_rid\":\"200612o4\",'
            r'\"anchor\":{\"id_str\":\"7476439385123636282\",'
            r'\"sec_uid\":\"MS4wLjABAAA-test\"}}"]);'
        )
        request_get.return_value = FakeResponse(text=f"<html><script>{script}</script></html>")

        info = fetch_live_room_info(
            DouyinAuthState.from_cookie("xgplayer_user_id=123456"),
            "https://live.douyin.com/200612o4",
        )

        self.assertEqual("7663365710281870121", info.room_id)
        self.assertEqual("4", info.status)
        self.assertEqual("O泡" if False else "随便刷", info.title)
        self.assertEqual("7476439385123636282", info.anchor_id)

    @patch("desktop_douyin.requests.get")
    def test_public_room_response_cookies_are_reused(self, request_get):
        script = (
            r'self.__pace_f.push([1,"roomStore\":{\"roomInfo\":{\"room\":{'
            r'\"id_str\":\"7663365710281870121\",\"status\":2,'
            r'\"title\":\"直播\"}},\"roomId\":\"7663365710281870121\"}"]);'
        )
        request_get.return_value = FakeResponse(text=f"<script>{script}</script>", cookies={"ttwid": "public-token"})
        auth = DouyinAuthState.from_cookie("")

        fetch_live_room_info(auth, "https://live.douyin.com/123")

        self.assertEqual("public-token", auth.cookie["ttwid"])
        self.assertIn("ttwid=public-token", auth.cookie_str)
        self.assertFalse(auth.connected)


class DouyinAnonymousAccessTest(unittest.TestCase):
    def test_anonymous_state_has_public_session_but_is_not_logged_in(self):
        auth = DouyinAuthState.from_cookie("")

        self.assertFalse(auth.connected)
        self.assertEqual("anonymous", auth.access_mode)
        self.assertTrue(auth.cookie.get("msToken"))
        self.assertTrue(auth.cookie.get("xgplayer_user_id"))

    def test_login_cookie_switches_to_authenticated_mode(self):
        auth = DouyinAuthState.from_cookie("sessionid_ss=login-token")

        self.assertTrue(auth.connected)
        self.assertEqual("authenticated", auth.access_mode)

    @patch("desktop_douyin.threading.Thread")
    def test_live_listener_can_start_anonymously(self, thread):
        manager = DouyinInteractionManager()

        status = manager.start_listening("https://live.douyin.com/123")

        self.assertFalse(status["connected"])
        self.assertEqual("anonymous", status["access_mode"])
        self.assertEqual(2, thread.return_value.start.call_count)

    @patch("desktop_douyin.threading.Thread")
    def test_logged_in_account_can_keep_live_listener_anonymous(self, thread):
        manager = DouyinInteractionManager()
        manager.set_auth("sessionid_ss=login-token", anonymous_live_access=True)

        status = manager.start_listening("https://live.douyin.com/123")

        self.assertTrue(status["connected"])
        self.assertTrue(status["account_connected"])
        self.assertEqual("anonymous", status["access_mode"])
        self.assertFalse(manager._session.auth.connected)

    @patch("desktop_douyin.threading.Thread")
    def test_live_listener_can_opt_into_authenticated_access(self, thread):
        manager = DouyinInteractionManager()
        manager.set_auth("sessionid_ss=login-token", anonymous_live_access=False)

        status = manager.start_listening("https://live.douyin.com/123")

        self.assertEqual("authenticated", status["access_mode"])
        self.assertTrue(manager._session.auth.connected)

    @patch("src.stream.get_douyin_stream_url", new_callable=AsyncMock)
    @patch("src.spider.get_douyin_web_stream_data", new_callable=AsyncMock)
    @patch("desktop_douyin.fetch_live_room_info")
    def test_audio_source_can_be_resolved_anonymously(self, fetch_room, stream_data, stream_url):
        fetch_room.return_value = LiveRoomInfo("123", "456", "789", "直播", "2")
        stream_data.return_value = {"status": 2}
        stream_url.return_value = {
            "is_live": True,
            "flv_url": "https://pull.example/live.flv",
            "title": "直播",
            "anchor_name": "主播",
            "quality": "原画",
        }
        manager = DouyinInteractionManager()

        audio = manager.audio_source("https://live.douyin.com/123,主播: 测试主播")

        self.assertEqual("anonymous", audio["access_mode"])
        self.assertEqual("mp3", audio["format"])
        self.assertEqual("https://live.douyin.com/123", stream_data.call_args.args[0])
        self.assertIn("msToken=", stream_data.call_args.kwargs["cookies"])

    @patch("src.stream.get_douyin_stream_url", new_callable=AsyncMock)
    @patch("src.spider.get_douyin_web_stream_data", new_callable=AsyncMock)
    @patch("desktop_douyin.fetch_live_room_info")
    def test_audio_source_prewarms_public_cookies_and_retries(self, fetch_room, stream_data, stream_url):
        def warm_session(auth, _room_url):
            auth.update_cookies({"ttwid": "public-token"})
            return LiveRoomInfo("123", "456", "789", "直播", "2")

        fetch_room.side_effect = warm_session
        stream_data.side_effect = [{"status": 4}, {"status": 2}]
        stream_url.side_effect = [
            {"is_live": False},
            {
                "is_live": True,
                "flv_url": "https://pull.example/live.flv",
                "title": "直播",
                "anchor_name": "主播",
                "quality": "原画",
            },
        ]
        manager = DouyinInteractionManager()

        audio = manager.audio_source("https://live.douyin.com/123")

        self.assertEqual("flv", audio["source_format"])
        self.assertEqual(2, stream_data.await_count)
        self.assertIn("ttwid=public-token", stream_data.call_args.kwargs["cookies"])

    def test_sending_chat_still_requires_login(self):
        manager = DouyinInteractionManager()
        manager._room_url = "https://live.douyin.com/123"

        with self.assertRaisesRegex(RuntimeError, "账号操作"):
            manager.send_chat("你好")

    @patch("desktop_douyin.resolve_live_room", return_value={"room_url": "https://live.douyin.com/123"})
    def test_room_resolution_is_available_anonymously(self, resolver):
        manager = DouyinInteractionManager()

        result = manager.resolve_live_room("https://live.douyin.com/123")

        self.assertEqual("anonymous", result["access_mode"])
        resolver.assert_called_once()

    @patch("desktop_douyin.resolve_live_room", return_value={"room_url": "https://live.douyin.com/123"})
    def test_room_resolution_still_uses_logged_in_account(self, resolver):
        manager = DouyinInteractionManager()
        manager.set_auth("sessionid_ss=login-token", anonymous_live_access=True)

        result = manager.resolve_live_room("https://www.douyin.com/user/example")

        self.assertEqual("authenticated", result["access_mode"])
        self.assertTrue(resolver.call_args.args[0].connected)

    @patch("desktop_douyin.fetch_gift_rank", return_value={"ranks": []})
    def test_gift_rank_is_available_anonymously(self, fetch_rank):
        manager = DouyinInteractionManager()

        result = manager.gift_rank("https://live.douyin.com/123")

        self.assertEqual("anonymous", result["access_mode"])
        fetch_rank.assert_called_once()


class DouyinLiveResponseDecoderTest(unittest.TestCase):
    @staticmethod
    def live_response_payload() -> bytes:
        response = Live_pb2.LiveResponse()
        response.cursor = "next-cursor"
        item = response.messagesList.add()
        item.method = "WebcastChatMessage"
        return response.SerializeToString()

    def test_decodes_gzip_payload(self):
        frame = Live_pb2.PushFrame()
        frame.payloadEncoding = "gzip"
        frame.payload = gzip.compress(self.live_response_payload())

        response = _decode_live_response(frame)

        self.assertEqual("next-cursor", response.cursor)
        self.assertEqual("WebcastChatMessage", response.messagesList[0].method)

    def test_decodes_uncompressed_payload(self):
        frame = Live_pb2.PushFrame()
        frame.payload = self.live_response_payload()

        response = _decode_live_response(frame)

        self.assertEqual("next-cursor", response.cursor)

    def test_tolerates_stale_gzip_metadata_on_plain_payload(self):
        frame = Live_pb2.PushFrame()
        frame.payloadEncoding = "gzip"
        frame.payload = self.live_response_payload()

        response = _decode_live_response(frame)

        self.assertEqual("next-cursor", response.cursor)


class DouyinLiveSessionTest(unittest.TestCase):
    @patch("desktop_douyin.WebSocketApp")
    @patch("desktop_douyin._live_signature", return_value="signature")
    @patch("desktop_douyin.fetch_initial_live_response", side_effect=ValueError("corrupt protobuf"))
    @patch("desktop_douyin.fetch_live_room_info")
    def test_bootstrap_parse_failure_falls_back_to_websocket(
        self,
        fetch_room_info,
        _fetch_initial,
        _signature,
        websocket_app,
    ):
        fetch_room_info.return_value = LiveRoomInfo(
            web_rid="123",
            room_id="456",
            user_id="789",
            title="test",
            status="2",
        )
        events = []
        session = DouyinLiveSession(
            "https://live.douyin.com/123",
            DouyinAuthState.from_cookie("ttwid=value"),
            events.append,
        )

        session.start()

        websocket_app.assert_called_once()
        websocket_app.return_value.run_forever.assert_called_once()
        self.assertIn("正在直接连接弹幕服务", events[0]["message"])


class DouyinAudioRelayTest(unittest.TestCase):
    def test_ffmpeg_relay_transcodes_to_browser_playable_mp3(self):
        command = _audio_relay_command("/runtime/bin/ffmpeg", "https://pull.example/live.m3u8")

        self.assertEqual("/runtime/bin/ffmpeg", command[0])
        self.assertIn("https://pull.example/live.m3u8", command)
        self.assertEqual("libmp3lame", command[command.index("-c:a") + 1])
        self.assertEqual("mp3", command[command.index("-f") + 1])
        self.assertEqual("pipe:1", command[-1])

    @patch("desktop_douyin.subprocess.Popen")
    @patch("desktop_douyin.shutil.which", return_value="/runtime/bin/ffmpeg")
    def test_audio_stream_rejects_stale_id_and_starts_current_relay(self, _which, popen):
        manager = DouyinInteractionManager()
        manager._audio_source_url = "https://pull.example/live.m3u8"
        manager._audio_stream_id = "current"
        process = popen.return_value
        process.poll.return_value = 0

        with self.assertRaisesRegex(ValueError, "播放凭证已失效"):
            manager.start_audio_stream("stale")
        started = manager.start_audio_stream("current")

        self.assertIs(process, started)
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
