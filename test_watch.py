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
                patch.object(watch, "send_telegram") as send,
            ):
                n = watch.ingest_telegram(wpath, spath)
            send.assert_called_once()
            body = send.call_args[0][0]
            self.assertIn("✅ AMD aggiunto/aggiornato", body)
            self.assertIn("AMD", body)
            self.assertIn("ing 130-134", body)
            self.assertEqual(n, 1)
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "AMD")
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["telegram_offset"], 43)

    def test_list_sends_and_returns_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.apply_telegram_list("/list", wpath))
                self.assertTrue(watch.apply_telegram_list("/WATCHLIST", wpath))
                self.assertFalse(watch.apply_telegram_list("/rm AMD", wpath))
            self.assertEqual(send.call_count, 2)
            self.assertIn("AMD", send.call_args_list[0][0][0])
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram") as send:
                watch.apply_telegram_list("/list", wpath)
            send.assert_called_with("Watchlist vuota.")

    def test_daily_summary_only_first_hour_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            rome = ZoneInfo("Europe/Rome")
            at_open = datetime(2026, 9, 12, 15, 10, tzinfo=rome)
            later = datetime(2026, 9, 12, 16, 10, tzinfo=rome)
            items = [{"ticker": "AMD", "tf": "daily", "ingresso_low": 1, "ingresso_high": 2, "stop": 0, "target": 3}]
            with (
                patch.object(watch, "rome_now", return_value=at_open),
                patch.object(watch, "fetch_prices", return_value={"AMD": 1.5}),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.maybe_send_daily_summary(items, spath)
                watch.maybe_send_daily_summary(items, spath)
            send.assert_called_once()
            self.assertIn("Riepilogo giornaliero", send.call_args[0][0])
            with (
                patch.object(watch, "rome_now", return_value=later),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.maybe_send_daily_summary(items, spath)
            send.assert_not_called()

    def test_clear_returns_tickers_or_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(
                wpath,
                [{"ticker": "AMD", "tf": "daily"}, {"ticker": "HOOD", "tf": "weekly"}],
            )
            self.assertEqual(watch.apply_telegram_clear("/clear", wpath), ["AMD", "HOOD"])
            self.assertEqual(watch.load_watchlist(wpath), [])
            self.assertEqual(watch.apply_telegram_clear("/RESET", wpath), [])
            self.assertIsNone(watch.apply_telegram_clear("/rm AMD", wpath))

    def test_set_range_and_single_ingresso(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(
                wpath,
                [{"ticker": "CRCL", "tf": "daily", "motivo": "keep", "ingresso_low": 1}],
            )
            self.assertEqual(
                watch.apply_telegram_set("/set CRCL 75-90 70 103", wpath),
                "CRCL",
            )
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["tf"], "daily")
            self.assertEqual(item["motivo"], "keep")
            self.assertEqual(item["ingresso_low"], 75.0)
            self.assertEqual(item["ingresso_high"], 90.0)
            self.assertEqual(item["stop"], 70.0)
            self.assertEqual(item["target"], 103.0)
            self.assertEqual(watch.apply_telegram_set("/set $hood 75 70 103", wpath), "HOOD")
            hood = next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "HOOD")
            self.assertEqual(hood["ingresso_low"], 75.0)
            self.assertEqual(hood["ingresso_high"], 75.0)
            self.assertEqual(hood["tf"], "")
            self.assertIsNone(watch.apply_telegram_set("ciao", wpath))

    def test_remove_returns_ticker_or_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            with patch.object(watch, "send_telegram") as send:
                self.assertEqual(watch.apply_telegram_remove("/rm AMD", wpath), "AMD")
                self.assertIsNone(watch.apply_telegram_remove("/rm AMD", wpath))
                self.assertIsNone(watch.apply_telegram_remove("ciao", wpath))
            send.assert_not_called()

    def test_summary_silent_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram") as send:
                watch.send_watchlist_summary([], [], wpath)
            send.assert_not_called()

    def test_summary_empty_watchlist_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram") as send:
                watch.send_watchlist_summary([], ["HOOD"], wpath)
            body = send.call_args[0][0]
            self.assertIn("❌ HOOD rimosso", body)
            self.assertIn("Watchlist vuota.", body)

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
                    patch.object(watch, "send_telegram"),
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
