import json
import tempfile
import unittest
from pathlib import Path

from desktop_douyin import _gift_wire_metadata
from desktop_gifts import GiftLedger


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
    def test_gift_wire_metadata_reads_repeat_and_value(self):
        gift = _field(5, 88) + _field(12, 10) + _field(16, "小心心".encode())
        payload = _field(2, b"88") + _field(5, 3) + _field(6, 3) + _field(9, 1) + _field(15, gift)
        self.assertEqual(_gift_wire_metadata(payload), {
            "gift_id": "88", "gift_name": "小心心", "repeat_count": 3,
            "combo_count": 3, "repeat_end": True, "diamond_count": 10,
        })

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
