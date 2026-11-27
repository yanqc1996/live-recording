import unittest
import json
from unittest.mock import AsyncMock, patch

from src.stream import get_douyin_stream_url
from src.spider import _extract_douyin_room_from_live_page, get_douyin_web_stream_data


class DouyinStreamUrlTest(unittest.IsolatedAsyncioTestCase):
    @patch('src.stream.get_response_status', new_callable=AsyncMock, return_value=True)
    async def test_sdk_only_room_exposes_both_fallback_sources(self, _status):
        result = await get_douyin_stream_url({
            'status': 2, 'anchor_name': '主播',
            'stream_url': {'live_core_sdk_data': {'pull_data': {'stream_data': json.dumps({
                'data': {'origin': {'main': {'flv': 'https://example.com/a.flv', 'hls': 'https://example.com/a.m3u8'}}}
            })}}}
        }, 'OD', None)
        self.assertTrue(result['is_live'])
        self.assertEqual(result['source_candidates'], ['https://example.com/a.flv', 'https://example.com/a.m3u8'])

    def test_live_page_room_fallback_extracts_escaped_stream_data(self):
        room = {
            "id_str": "7698961051978894106", "status": 2,
            "owner": {"nickname": "主播"},
            "stream_url": {"flv_pull_url": {"FULL_HD1": "https://example.com/live.flv"}},
        }
        serialized = json.dumps({"roomStore": {"roomInfo": {"room": room}}}, ensure_ascii=False)
        html = f'<script>self.__pace_f.push([1,{json.dumps(serialized)}]);</script>'

        result = _extract_douyin_room_from_live_page(html)

        self.assertEqual(2, result["status"])
        self.assertEqual("主播", result["anchor_name"])
        self.assertEqual("https://example.com/live.flv", result["stream_url"]["flv_pull_url"]["FULL_HD1"])

    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_live_page_is_used_when_reflow_and_pc_entry_are_blocked(self, async_req):
        room = {
            "id_str": "7698961051978894106", "status": 2,
            "owner": {"nickname": "主播"},
            "stream_url": {"flv_pull_url": {"FULL_HD1": "https://example.com/live.flv"}},
        }
        serialized = json.dumps({"roomStore": {"roomInfo": {"room": room}}}, ensure_ascii=False)
        html = f'<script>self.__pace_f.push([1,{json.dumps(serialized)}]);</script>'
        async_req.side_effect = [
            json.dumps({"status_code": 0, "data": {}}),
            json.dumps({"status_code": 0, "data": {}}),
            json.dumps({"status_code": 0, "data": {}}),
            json.dumps({"data": {"data": [], "enter_room_id": "", "user": {}}}),
            html,
        ]

        result = await get_douyin_web_stream_data(
            "https://live.douyin.com/930899399141?lr_room_id=7698961051978894106&lr_sec_user_id=sec-live"
        )

        self.assertEqual(2, result["status"])
        self.assertEqual("https://example.com/live.flv", result["stream_url"]["flv_pull_url"]["FULL_HD1"])
        self.assertEqual(5, async_req.await_count)

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
    async def test_radio_room_uses_stored_reflow_identity_after_pc_entry_fails(self, async_req):
        async_req.side_effect = [
            json.dumps({"data": {"data": [], "enter_room_id": "", "user": {}}}),
            json.dumps({"status_code": 0, "data": {"room": {
            "status": 2, "owner": {"nickname": "电台主播"},
            "stream_url": {
                "flv_pull_url": {"FULL_HD1": "https://example.com/radio.flv"},
                "hls_pull_url_map": {},
            },
        }}}),
        ]

        result = await get_douyin_web_stream_data(
            "https://live.douyin.com/404-room?lr_room_id=7697&lr_sec_user_id=sec-radio"
        )

        self.assertEqual(2, result["status"])
        self.assertEqual("电台主播", result["anchor_name"])
        self.assertEqual(2, async_req.await_count)
        self.assertIn("room_id=7697", async_req.await_args_list[1].kwargs["url"])
        self.assertIn("sec_user_id=sec-radio", async_req.await_args_list[1].kwargs["url"])

    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_traditional_room_keeps_pc_entry_as_primary_source(self, async_req):
        async_req.return_value = json.dumps({"data": {"data": [{
            "status": 2,
            "stream_url": {"flv_pull_url": {"FULL_HD1": "https://example.com/video.flv"}},
        }], "user": {"nickname": "视频主播"}}})

        result = await get_douyin_web_stream_data(
            "https://live.douyin.com/123?lr_room_id=stale-session&lr_sec_user_id=sec-video"
        )

        self.assertEqual(2, result["status"])
        self.assertEqual("视频主播", result["anchor_name"])
        self.assertEqual(1, async_req.await_count)
        self.assertIn("webcast/room/web/enter", async_req.await_args.kwargs["url"])

    @patch("src.spider.async_req", new_callable=AsyncMock)
    async def test_reflow_empty_response_is_retried(self, async_req):
        async_req.side_effect = [
            json.dumps({"data": {"data": [], "enter_room_id": "", "user": {}}}),
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
        self.assertEqual(3, async_req.await_count)

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
