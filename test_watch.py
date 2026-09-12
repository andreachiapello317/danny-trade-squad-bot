#!/usr/bin/env python3
"""Test parser ticket + ingest Telegram (senza rete)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import watch


TICKET = """$AMD · daily

Danny: Red candle on daily chart, panel 1

P1: bordo
Hole: 120–140, close in mezzo
CHIP: supporto a 132

Livelli: ingresso 130–134 · stop 124 · target 148
rossa daily sul bordo
"""


def _msg(text: str | None = None, caption: str | None = None, chat_id: int | None = None) -> dict:
    if chat_id is None:
        chat_id = int(watch.DEFAULT_CHAT_ID)
    out: dict = {"chat": {"id": chat_id}}
    if text is not None:
        out["text"] = text
    if caption is not None:
        out["caption"] = caption
    return out


class WatchWindowTests(unittest.TestCase):
    def test_inside_and_outside_rome(self) -> None:
        rome = ZoneInfo("Europe/Rome")
        self.assertTrue(watch.in_watch_window(datetime(2026, 9, 9, 15, 0, tzinfo=rome)))
        self.assertTrue(watch.in_watch_window(datetime(2026, 9, 9, 22, 30, tzinfo=rome)))
        self.assertFalse(watch.in_watch_window(datetime(2026, 9, 9, 14, 59, tzinfo=rome)))
        self.assertFalse(watch.in_watch_window(datetime(2026, 9, 9, 23, 0, tzinfo=rome)))

    def test_dst_winter_utc(self) -> None:
        # 14:00 UTC in gennaio = 15:00 CET
        self.assertTrue(
            watch.in_watch_window(datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc))
        )
        # 13:00 UTC in gennaio = 14:00 CET
        self.assertFalse(
            watch.in_watch_window(datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc))
        )


class ParseTicketTests(unittest.TestCase):
    def test_trader_card(self) -> None:
        item = watch.parse_ticket(TICKET)
        assert item is not None
        self.assertEqual(item["ticker"], "AMD")
        self.assertEqual(item["tf"], "daily")
        self.assertEqual(item["ingresso_low"], 130.0)
        self.assertEqual(item["ingresso_high"], 134.0)
        self.assertEqual(item["stop"], 124.0)
        self.assertEqual(item["target"], 148.0)
        self.assertIn("Red candle", item["motivo"])


class TelegramExtractTests(unittest.TestCase):
    def test_caption_beats_empty_text(self) -> None:
        msg = _msg(caption=TICKET)
        self.assertIn("$AMD", watch.payload_text(msg))

    def test_text_message(self) -> None:
        msg = _msg(text=TICKET)
        self.assertIn("$AMD", watch.payload_text(msg))

    def test_media_without_caption_is_empty(self) -> None:
        self.assertEqual(watch.payload_text({"photo": [{}], "chat": {"id": 1}}), "")

    def test_ingest_caption_and_skip_alert_and_other_chat(self) -> None:
        updates = [
            {"update_id": 10, "message": _msg(caption=TICKET)},
            {"update_id": 11, "message": _msg(text="ALERT AMD ingresso 131")},
            {"update_id": 12, "channel_post": _msg(text=TICKET.replace("AMD", "NVDA"), chat_id=1)},
            {"update_id": 13, "message": _msg(text="/start")},
        ]
        tickets, max_id = watch.tickets_from_updates(updates, watch.DEFAULT_CHAT_ID)
        self.assertEqual(max_id, 13)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["ticker"], "AMD")

    def test_offset_persisted_and_watchlist_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            updates = [{"update_id": 42, "message": _msg(caption=TICKET)}]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 1)
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "AMD")
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["telegram_offset"], 43)

    def test_fired_roundtrip(self) -> None:
        fired = {("AMD", "daily", "ingresso"): True, ("NVDA", "weekly", "stop"): False}
        dumped = watch.dump_fired(fired)
        self.assertEqual(dumped, {"AMD|daily|ingresso": True})
        loaded = watch.load_fired({"fired": dumped})
        self.assertTrue(loaded[("AMD", "daily", "ingresso")])
        self.assertNotIn(("NVDA", "weekly", "stop"), loaded)

    def test_persist_fired_keeps_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"telegram_offset": 9})
            watch.persist_fired(spath, {("AMD", "daily", "target"): True})
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["telegram_offset"], 9)
            self.assertEqual(state["fired"]["AMD|daily|target"], True)

    def test_remove_missing_does_not_telegram(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            wpath.write_text("[]\n", encoding="utf-8")
            with patch.object(watch, "send_telegram") as send:
                handled = watch.apply_telegram_remove("/rm AMD", wpath, [])
            self.assertTrue(handled)
            send.assert_not_called()

    def test_remove_existing_records_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            removed: list[str] = []
            with patch.object(watch, "send_telegram") as send:
                watch.apply_telegram_remove("/rm $amd", wpath, removed)
            send.assert_not_called()
            self.assertEqual(removed, ["AMD"])
            self.assertEqual(watch.load_watchlist(wpath), [])

    def test_upsert_insert_only_first_time(self) -> None:
        t = {"ticker": "AMD", "tf": "daily", "ingresso_low": 1, "ingresso_high": 2}
        items, inserted = watch.upsert_insert([], t)
        self.assertTrue(inserted)
        items, inserted = watch.upsert_insert(items, t)
        self.assertFalse(inserted)

    def test_digest_only_when_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            with patch.object(watch, "send_telegram") as send:
                watch.notify_watchlist_changes([], [], wpath)
            send.assert_not_called()
            with patch.object(watch, "send_telegram") as send:
                watch.notify_watchlist_changes(["AMD daily"], [], wpath)
            send.assert_called_once()
            body = send.call_args[0][0]
            self.assertIn("+ AMD daily", body)
            self.assertIn("Watchlist:", body)

    def test_userbot_skips_without_creds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_USER_SESSION"):
                os.environ.pop(key, None)
            self.assertEqual(watch.ingest_telegram_userbot(wpath, spath), 0)

    def test_userbot_ingests_and_persists_last_id(self) -> None:
        class FakeMsg:
            def __init__(self, mid: int, text: str) -> None:
                self.id = mid
                self.text = text

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def start(self) -> None:
                return None

            def iter_messages(self, *args: object, **kwargs: object):
                return [
                    FakeMsg(10, TICKET),
                    FakeMsg(11, "ALERT AMD ingresso 131"),
                ]

            def disconnect(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            os.environ["TELEGRAM_API_ID"] = "12345"
            os.environ["TELEGRAM_API_HASH"] = "hash"
            os.environ["TELEGRAM_USER_SESSION"] = "session"
            try:
                with (
                    patch.object(watch, "TelegramClient", FakeClient),
                    patch.object(watch, "StringSession", lambda s: s),
                ):
                    n = watch.ingest_telegram_userbot(wpath, spath)
            finally:
                os.environ.pop("TELEGRAM_API_ID", None)
                os.environ.pop("TELEGRAM_API_HASH", None)
                os.environ.pop("TELEGRAM_USER_SESSION", None)
            self.assertEqual(n, 1)
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "AMD")
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["userbot_last_id"], 11)

    def test_dotenv_does_not_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("TELEGRAM_CHAT_ID=1\nTELEGRAM_BOT_TOKEN=fromfile\n", encoding="utf-8")
            os.environ["TELEGRAM_CHAT_ID"] = "keep-me"
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            try:
                watch.load_dotenv(env_path)
                self.assertEqual(os.environ["TELEGRAM_CHAT_ID"], "keep-me")
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "fromfile")
            finally:
                os.environ.pop("TELEGRAM_BOT_TOKEN", None)
                os.environ.pop("TELEGRAM_CHAT_ID", None)


if __name__ == "__main__":
    unittest.main()
