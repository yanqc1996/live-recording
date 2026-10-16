import unittest
import json
from unittest.mock import AsyncMock, patch

from src.stream import get_douyin_stream_url
from src.spider import get_douyin_web_stream_data


class DouyinStreamUrlTest(unittest.IsolatedAsyncioTestCase):
    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_pc_entry_without_room_list_falls_back_to_reflow(self, async_req):
        async_req.side_effect = [
            json.dumps({"data": {"data": [], "enter_room_id": "", "user": {"id_str": "789", "sec_uid": "sec-1", "nickname": "主播"}}}),
            json.dumps({"status_code": 0, "data": {"room": {
                "status": 2, "owner": {"nickname": "主播"},
                "stream_url": {
                    "flv_pull_url": {"FULL_HD1": "https://example.com/live.flv"},
                    "hls_pull_url_map": {"FULL_HD1": "https://example.com/live.m3u8"},
                },
            }}}),
        ]

        result = await get_douyin_web_stream_data("https://live.douyin.com/123")

        self.assertEqual(2, result["status"])
        self.assertEqual("主播", result["anchor_name"])
        self.assertIn("FULL_HD1", result["stream_url"]["flv_pull_url"])
        self.assertEqual(2, async_req.await_count)
        self.assertIn("room_id=789", async_req.await_args_list[1].kwargs["url"])

    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_radio_room_uses_stored_reflow_identity_before_pc_entry(self, async_req):
        async_req.return_value = json.dumps({"status_code": 0, "data": {"room": {
            "status": 2, "owner": {"nickname": "电台主播"},
            "stream_url": {
                "flv_pull_url": {"FULL_HD1": "https://example.com/radio.flv"},
                "hls_pull_url_map": {},
            },
        }}})

        result = await get_douyin_web_stream_data(
            "https://live.douyin.com/404-room?lr_room_id=7697&lr_sec_user_id=sec-radio"
        )

        self.assertEqual(2, result["status"])
        self.assertEqual("电台主播", result["anchor_name"])
        self.assertEqual(1, async_req.await_count)
        self.assertIn("room_id=7697", async_req.await_args.kwargs["url"])
        self.assertIn("sec_user_id=sec-radio", async_req.await_args.kwargs["url"])

    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_reflow_empty_response_is_retried(self, async_req):
        async_req.side_effect = [
            json.dumps({"status_code": 0, "data": {}}),
            json.dumps({"status_code": 0, "data": {"room": {
                "status": 2, "owner": {"nickname": "电台主播"},
                "stream_url": {"flv_pull_url": {"FULL_HD1": "https://example.com/radio.flv"}},
            }}}),
        ]

        result = await get_douyin_web_stream_data(
            "https://live.douyin.com/404-room?lr_room_id=7697&lr_sec_user_id=sec-radio"
        )

        self.assertEqual(2, result["status"])
        self.assertEqual(2, async_req.await_count)

    async def test_radio_room_can_use_flv_without_hls(self):
        data = {
            "anchor_name": "电台主播",
            "status": 2,
            "title": "电台直播",
            "stream_url": {
                "flv_pull_url": {"FULL_HD1": "https://example.com/radio.flv?only_audio=1"},
                "hls_pull_url_map": {},
            },
        }

        result = await get_douyin_stream_url(data, "原画", "")

        self.assertTrue(result["is_live"])
        self.assertEqual(result["flv_url"], "https://example.com/radio.flv?only_audio=1")
        self.assertEqual(result["m3u8_url"], "")
        self.assertEqual(result["record_url"], result["flv_url"])

    @patch("src.stream.get_response_status", new_callable=AsyncMock, return_value=True)
    async def test_video_room_can_use_hls_without_flv(self, response_status):
        data = {
            "anchor_name": "主播",
            "status": 2,
            "title": "直播",
            "stream_url": {
                "flv_pull_url": {},
                "hls_pull_url_map": {"FULL_HD1": "https://example.com/live.m3u8"},
            },
        }

        result = await get_douyin_stream_url(data, "原画", "")

        self.assertTrue(result["is_live"])
        self.assertEqual(result["record_url"], "https://example.com/live.m3u8")
        response_status.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
