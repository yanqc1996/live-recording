import unittest
from unittest.mock import patch

from desktop_douyin import DouyinAuthState, fetch_live_room_info, resolve_live_room


PROFILE_URL = (
    "https://www.douyin.com/user/"
    "MS4wLjABAAAAgbRE2r0x59BHXG05lLRtBJ66RE3eiJ_xXqnIFhQGg8rUOYXgTuU6OO6u4Ry6gKYU"
)


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload or {}
        self.text = text
        self.cookies = type("Cookies", (), {"get_dict": lambda self: {}})()

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DouyinProfileResolverTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
