import json
import tempfile
import unittest
from pathlib import Path

from desktop_douyin import DouyinAuthState, DouyinLiveSession, _gift_combo_count, _gift_wire_metadata, _light_gift_wire_metadata, _protobuf_wire_shape
from desktop_gifts import GiftLedger
from douyin_static import Live_pb2


def _varint(value: int) -> bytes:
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    return _varint((number << 3) | 2) + _varint(len(value)) + value


class GiftLedgerTest(unittest.TestCase):
    def test_implausible_combo_identifier_is_rejected(self):
        self.assertIsNone(_gift_combo_count(2974623777696105, 2974623777696105))
        self.assertEqual(3, _gift_combo_count(2974623777696105, 3))

    def test_wire_shape_does_not_store_values(self):
        shape = _protobuf_wire_shape(_field(2, b"secret") + _field(6, 2974623777696105))
        self.assertEqual("bytes", shape["fields"]["2"][0]["kind"])
        self.assertEqual(6, shape["fields"]["2"][0]["length"])
        self.assertEqual("large", shape["fields"]["6"][0]["range"])
        self.assertNotIn("secret", json.dumps(shape))

    def test_session_does_not_emit_gift_for_implausible_combo(self):
        events = []
        session = DouyinLiveSession("https://live.douyin.com/1", DouyinAuthState.from_cookie(""), events.append)
        gift = Live_pb2.GiftMessage()
        gift.giftId = "1"
        gift.comboCount = 2974623777696105
        item = Live_pb2.Message(
            method="WebcastGiftMessageV2", payload=gift.SerializeToString()
        )

        session._handle_message(item)

        self.assertFalse(any(event.get("type") == "gift" for event in events))

    def test_ledger_discards_historical_impossible_quantities(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gift_ledger.json"
            path.write_text(json.dumps({"events": [{
                "gift_id": "1", "gift_name": "未知礼物", "quantity": 2974623777696105,
                "combo_count": 2974623777696105, "user": {"id": "685"},
            }], "prices": {}}, ensure_ascii=False))
            ledger = GiftLedger(path)

            self.assertEqual(0, ledger.stats()["gift_count"])
            self.assertEqual([], json.loads(path.read_text())["events"])

    def test_ledger_keeps_bounded_deduplicated_schema_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            context = ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            event = {"type": "gift_schema", "source_method": "WebcastGiftMessageV2", "schema_fingerprint": "abc", "schema": {"bytes": 12}, "accepted": False}
            ledger.record(event, context)
            ledger.record(event, context)

            samples = ledger.stats()["schema_samples"]
            self.assertEqual(1, len(samples))
            self.assertEqual(2, samples[0]["count"])
            self.assertNotIn("message_id", samples[0])

    def test_gift_wire_metadata_reads_repeat_and_value(self):
        gift = _field(5, 88) + _field(12, 10) + _field(16, "小心心".encode())
        payload = _field(2, b"88") + _field(5, 3) + _field(6, 3) + _field(9, 1) + _field(15, gift)
        self.assertEqual(_gift_wire_metadata(payload), {
            "gift_id": "88", "gift_name": "小心心", "repeat_count": 3,
            "combo_count": 3, "repeat_end": True, "diamond_count": 10,
        })

    def test_light_gift_uses_its_own_count_sender_and_price_layout(self):
        gift_info = _field(1, 909) + _field(3, 10)
        payload = _field(2, 1) + _field(3, 1) + _field(5, 2974623777696105) + _field(7, gift_info) + _field(10, 2)

        self.assertEqual(_light_gift_wire_metadata(payload), {
            "gift_id": "909", "diamond_count": 10, "count": 2,
            "user_id": "2974623777696105",
        })

    def test_session_counts_light_gift_instead_of_rejecting_sender_as_combo(self):
        events = []
        session = DouyinLiveSession("https://live.douyin.com/1", DouyinAuthState.from_cookie(""), events.append)
        gift_info = _field(1, 909) + _field(3, 10)
        payload = _field(2, 1) + _field(3, 1) + _field(5, 2974623777696105) + _field(7, gift_info) + _field(10, 2)
        item = Live_pb2.Message(method="WebcastLightGiftMessage", msgId=123, payload=payload)

        session._handle_message(item)

        gift = next(event for event in events if event.get("type") == "gift")
        self.assertEqual("909", gift["gift_id"])
        self.assertEqual(2, gift["combo_count"])
        self.assertEqual(10, gift["diamond_count"])
        self.assertEqual("2974623777696105", gift["user"]["id"])

    def test_ledger_deduplicates_messages_and_counts_combo_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gift_ledger.json"
            ledger = GiftLedger(path)
            ledger.begin({"id": "anchor-1", "name": "主播"}, "https://live.douyin.com/1")
            base = {"type": "gift", "gift_id": "g1", "gift_name": "玫瑰", "diamond_count": 1, "user": {"id": "u1", "nickname": "观众"}}
            ledger.record({**base, "message_id": "m1", "combo_count": 1, "time": 10})
            ledger.record({**base, "message_id": "m2", "combo_count": 2, "time": 11})
            ledger.record({**base, "message_id": "m2", "combo_count": 2, "time": 11})
            stats = ledger.stats()
            self.assertEqual(stats["gift_count"], 2)
            self.assertEqual(stats["sound_wave"], 2)
            self.assertEqual(stats["donor_count"], 1)
            self.assertEqual(len(json.loads(path.read_text())["events"]), 2)

    def test_manual_price_recalculates_unknown_gifts(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            ledger.record({"type": "gift", "gift_id": "g2", "gift_name": "神秘礼物", "combo_count": 2, "user": {"id": "u2"}})
            self.assertEqual(ledger.stats()["unknown_count"], 2)
            stats = ledger.set_price("g2", "神秘礼物", 5)
            self.assertEqual(stats["unknown_count"], 0)
            self.assertEqual(stats["sound_wave"], 10)

    def test_stats_report_value_sources_and_filter_recording_window(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            context = ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            base = {"type": "gift", "gift_id": "g1", "gift_name": "玫瑰", "user": {"id": "u1", "nickname": "观众"}}
            ledger.record({**base, "message_id": "m1", "combo_count": 1, "diamond_count": 2, "time": 100}, context)
            ledger.record({**base, "message_id": "m2", "gift_id": "g2", "combo_count": 1, "time": 200}, context)
            stats = ledger.stats(anchor_name="主播", started_at=90, ended_at=150)
            self.assertEqual(stats["gift_count"], 1)
            self.assertEqual(stats["platform_count"], 1)
            self.assertEqual(stats["coverage_percent"], 100)

    def test_remap_anchor_keeps_gift_history_after_identity_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            ledger.begin({"id": "duplicate", "name": "旧名字"}, "room")
            ledger.record({"type": "gift", "gift_id": "g1", "gift_name": "玫瑰", "combo_count": 2, "diamond_count": 1})

            self.assertEqual(1, ledger.remap_anchor(["duplicate"], "primary", "新名字"))
            self.assertEqual(2, ledger.stats(anchor_id="primary")["gift_count"])
            self.assertEqual(0, ledger.stats(anchor_id="duplicate")["gift_count"])

    def test_rank_snapshot_supplies_sound_wave_when_websocket_has_no_gifts(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            context = ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            first = {"type": "gift_rank_snapshot", "ranks": [{"user": {"id": "u1", "nickname": "观众"}, "contribution": 30}]}
            second = {"type": "gift_rank_snapshot", "ranks": [{"user": {"id": "u1", "nickname": "观众"}, "contribution": 45}]}

            ledger.record(first, context)
            ledger.record(second, context)
            stats = ledger.stats(anchor_id="anchor-1")

            self.assertEqual(45, stats["sound_wave"])
            self.assertEqual(45, stats["rank_sound_wave"])
            self.assertEqual(0, stats["gift_count"])
            self.assertEqual(1, stats["donor_count"])

    def test_rank_snapshot_reconciles_with_real_gifts_without_double_counting(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            context = ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            ledger.record({"type": "gift_rank_snapshot", "ranks": [{"user": {"id": "u1"}, "contribution": 10}]}, context)
            ledger.record({"type": "gift", "user": {"id": "u1"}, "gift_id": "g1", "gift_name": "玫瑰", "diamond_count": 1, "combo_count": 1}, context)
            ledger.record({"type": "gift_rank_snapshot", "ranks": [{"user": {"id": "u1"}, "contribution": 30}]}, context)

            stats = ledger.stats(anchor_id="anchor-1")
            self.assertEqual(30, stats["sound_wave"])
            self.assertEqual(29, stats["rank_sound_wave"])

    def test_rank_snapshot_fills_large_gift_missing_from_websocket(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = GiftLedger(Path(directory) / "gift_ledger.json")
            context = ledger.begin({"id": "anchor-1", "name": "主播"}, "room")
            ledger.record({
                "type": "gift", "user": {"id": "u1"}, "gift_id": "small",
                "gift_name": "小礼物", "diamond_count": 1, "combo_count": 3,
            }, context)
            ledger.record({
                "type": "gift_rank_snapshot",
                "ranks": [{"user": {"id": "u1", "nickname": "观众"}, "contribution": 3003}],
            }, context)

            stats = ledger.stats(anchor_id="anchor-1")
            self.assertEqual(3003, stats["sound_wave"])
            self.assertEqual(3000, stats["rank_sound_wave"])
            self.assertEqual(3, stats["gift_count"])
