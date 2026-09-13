#!/usr/bin/env python3
"""Test parser ticket + ingest Telegram (senza rete)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


def _msg(
    text: str | None = None,
    caption: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> dict:
    if chat_id is None:
        chat_id = int(watch.DEFAULT_CHAT_ID)
    out: dict = {"chat": {"id": chat_id}}
    if text is not None:
        out["text"] = text
    if caption is not None:
        out["caption"] = caption
    if message_id is not None:
        out["message_id"] = message_id
    return out


class SymbolFilterTests(unittest.TestCase):
    def test_classify_none_without_yf(self) -> None:
        with patch.object(watch, "yf", None):
            self.assertIsNone(watch.classify_ticker("AMD"))

    def test_classify_quote_type_and_errors(self) -> None:
        class FakeTicker:
            def __init__(self, info: dict) -> None:
                self.info = info

        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker({"quoteType": "equity"})
            self.assertEqual(watch.classify_ticker("amd"), "EQUITY")
        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.side_effect = RuntimeError("down")
            self.assertIsNone(watch.classify_ticker("AMD"))
        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker({})
            self.assertIsNone(watch.classify_ticker("AMD"))

    def test_is_valid_symbol_rules(self) -> None:
        with patch.object(watch, "classify_ticker", return_value="EQUITY"):
            self.assertTrue(watch.is_valid_symbol("AMD"))
        with patch.object(watch, "classify_ticker", return_value="ETF"):
            self.assertTrue(watch.is_valid_symbol("SPY"))
        with patch.object(watch, "classify_ticker", return_value=None):
            self.assertTrue(watch.is_valid_symbol("AMD"))
        with patch.object(watch, "classify_ticker", return_value="INDEX"):
            self.assertFalse(watch.is_valid_symbol("KOSPI"))
        with patch.object(watch, "classify_ticker", return_value="CRYPTOCURRENCY"):
            self.assertFalse(watch.is_valid_symbol("BTC"))


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
                patch.object(watch, "is_valid_symbol", return_value=True),
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

    def test_ingest_rejects_non_equity_ticket(self) -> None:
        index_ticket = TICKET.replace("$AMD", "$KOSPI")
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            updates = [{"update_id": 80, "message": _msg(text=index_ticket)}]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "classify_ticker", return_value="INDEX"),
                patch.object(watch, "send_telegram") as send,
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 1)
            self.assertEqual(watch.load_watchlist(wpath), [])
            body = send.call_args[0][0]
            self.assertIn("❌ KOSPI scartato (non è un'azione/ETF)", body)
            self.assertNotIn("rimosso", body)
            self.assertNotIn("✅ KOSPI", body)

    def test_set_ignores_symbol_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            with patch.object(watch, "classify_ticker", return_value="INDEX"):
                self.assertEqual(watch.apply_telegram_set("/set KOSPI 100 90 120", wpath), "KOSPI")
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["ticker"], "KOSPI")

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

    def test_scan_sends_to_screener_chat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(
                wpath,
                [{"ticker": "AMD", "tf": "daily"}, {"ticker": "NVDA", "tf": "weekly"}],
            )
            with (
                patch.object(watch, "run_screener", return_value="📊 Screener tecnico\n✅ AMD") as run,
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_scan("/scan", wpath))
                self.assertTrue(watch.apply_telegram_scan("/SCAN", wpath))
                self.assertFalse(watch.apply_telegram_scan("/list", wpath))
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0][0][0], wpath)
            send.assert_called_with(
                "📊 Screener tecnico\n✅ AMD",
                chat_id_override=watch.SCREENER_CHAT_ID,
            )

    def test_ingest_scan_deletes_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            updates = [
                {"update_id": 70, "message": _msg(text="/scan", message_id=701)},
            ]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "run_screener", return_value="📊 ok"),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 0)
            send.assert_called_once_with("📊 ok", chat_id_override=watch.SCREENER_CHAT_ID)
            delete.assert_called_once_with(701)

    def test_screener_daily_only_first_hour_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            rome = ZoneInfo("Europe/Rome")
            at_open = datetime(2026, 9, 12, 15, 10, tzinfo=rome)
            later = datetime(2026, 9, 12, 16, 10, tzinfo=rome)
            items = [{"ticker": "AMD", "tf": "daily"}]
            wpath = Path(tmp) / "watchlist.json"
            with (
                patch.object(watch, "rome_now", return_value=at_open),
                patch.object(watch, "run_screener", return_value="📊 Screener tecnico\n✅ AMD") as run,
                patch.object(watch, "send_telegram") as send,
            ):
                watch.maybe_send_screener(items, spath, wpath)
                watch.maybe_send_screener(items, spath, wpath)
            run.assert_called_once_with(wpath)
            send.assert_called_once_with(
                "📊 Screener tecnico\n✅ AMD",
                chat_id_override=watch.SCREENER_CHAT_ID,
            )
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["last_screener_run"], "2026-09-12")
            with (
                patch.object(watch, "rome_now", return_value=later),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.maybe_send_screener(items, spath, wpath)
            send.assert_not_called()

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

    def test_set_field_updates_only_that_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "daily",
                        "ingresso_low": 130.0,
                        "ingresso_high": 134.0,
                        "stop": 124.0,
                        "target": 148.0,
                        "motivo": "keep",
                    }
                ],
            )
            self.assertEqual(watch.apply_telegram_set_field("/setbuy AMD 132.5", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["ingresso_low"], 132.5)
            self.assertEqual(amd["ingresso_high"], 132.5)
            self.assertEqual(amd["stop"], 124.0)
            self.assertEqual(amd["target"], 148.0)
            self.assertEqual(amd["motivo"], "keep")
            self.assertEqual(watch.apply_telegram_set_field("/settarget $amd 160", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["target"], 160.0)
            self.assertEqual(amd["ingresso_low"], 132.5)
            self.assertEqual(watch.apply_telegram_set_field("/SETSTOP AMD 120", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["stop"], 120.0)
            self.assertEqual(watch.apply_telegram_set_field("/setbuy HOOD 75", wpath), "HOOD")
            hood = next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "HOOD")
            self.assertEqual(hood["ingresso_low"], 75.0)
            self.assertEqual(hood["ingresso_high"], 75.0)
            self.assertIsNone(hood["stop"])
            self.assertIsNone(hood["target"])
            self.assertIsNone(watch.apply_telegram_set_field("/set AMD", wpath))
            self.assertIsNone(watch.apply_telegram_set_field("ciao", wpath))

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
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram") as send:
                watch.send_watchlist_summary([], [], wpath, spath)
            send.assert_not_called()

    def test_summary_empty_watchlist_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram", return_value=88) as send:
                watch.send_watchlist_summary([], ["HOOD"], wpath, spath)
            body = send.call_args[0][0]
            self.assertIn("❌ HOOD rimosso", body)
            self.assertIn("Watchlist vuota.", body)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 88)

    def test_summary_replaces_previous_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            watch.save_state(spath, {"summary_message_id": 11, "telegram_offset": 3})
            with (
                patch.object(watch, "delete_telegram_message") as delete,
                patch.object(watch, "send_telegram", return_value=22) as send,
            ):
                watch.send_watchlist_summary(["AMD"], [], wpath, spath)
            delete.assert_called_once_with(11)
            send.assert_called_once()
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 22)
            self.assertEqual(state["telegram_offset"], 3)

    def test_ingest_deletes_human_messages_and_set_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            updates = [
                {
                    "update_id": 50,
                    "message": _msg(text="/setbuy NVDA 180", message_id=501),
                },
                {
                    "update_id": 51,
                    "message": _msg(text="ALERT NVDA ingresso 180", message_id=502),
                },
            ]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "send_telegram", return_value=900),
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                watch.ingest_telegram(wpath, spath)
            delete.assert_called_once_with(501)
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "NVDA")
            self.assertEqual(items[0]["ingresso_low"], 180.0)
            self.assertEqual(items[0]["ingresso_high"], 180.0)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 900)

    def test_expire_sent_alerts_deletes_only_old_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            now = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
            watch.save_state(
                spath,
                {
                    "summary_message_id": 7,
                    "sent_alerts": [
                        {
                            "message_id": 1,
                            "sent_at": (now - timedelta(hours=49)).isoformat(),
                        },
                        {
                            "message_id": 2,
                            "sent_at": (now - timedelta(hours=10)).isoformat(),
                        },
                    ],
                },
            )
            with patch.object(watch, "delete_telegram_message") as delete:
                watch.expire_sent_alerts(spath, now=now)
            delete.assert_called_once_with(1)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 7)
            self.assertEqual(len(state["sent_alerts"]), 1)
            self.assertEqual(state["sent_alerts"][0]["message_id"], 2)

    def test_maybe_alert_records_sent_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            item = {"ticker": "AMD", "tf": "daily"}
            fired: dict[tuple[str, str, str], bool] = {}
            with patch.object(watch, "send_telegram", return_value=321):
                watch.maybe_alert(
                    item,
                    "ingresso",
                    "ALERT AMD ingresso 130.00 (130)",
                    True,
                    fired,
                    spath,
                )
            self.assertTrue(fired[("AMD", "daily", "ingresso")])
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["sent_alerts"][0]["message_id"], 321)
            self.assertIn("T", state["sent_alerts"][0]["sent_at"])

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
                    patch.object(watch, "is_valid_symbol", return_value=True),
                    patch.object(watch, "send_telegram"),
                    patch.object(watch, "delete_telegram_message") as delete,
                ):
                    n = watch.ingest_telegram_userbot(wpath, spath)
                    self.assertEqual(delete.call_args_list[0][0][0], 10)
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


class DayRangeTests(unittest.TestCase):
    def test_in_ingresso_spot_unchanged_without_day_range(self) -> None:
        self.assertTrue(watch.in_ingresso(132.0, 130.0, 134.0))
        self.assertFalse(watch.in_ingresso(140.0, 130.0, 134.0))
        self.assertTrue(watch.in_ingresso(100.0, 100.0, 100.0))
        self.assertFalse(watch.in_ingresso(101.0, 100.0, 100.0))

    def test_in_ingresso_day_range_overlaps_band(self) -> None:
        self.assertTrue(watch.in_ingresso(140.0, 130.0, 134.0, 120.0, 131.0))
        self.assertTrue(watch.in_ingresso(140.0, 130.0, 134.0, 134.0, 150.0))
        self.assertFalse(watch.in_ingresso(140.0, 130.0, 134.0, 135.0, 150.0))
        self.assertFalse(watch.in_ingresso(140.0, 130.0, 134.0, 100.0, 129.0))

    def test_in_ingresso_day_range_touches_single_level(self) -> None:
        # 100 ± max(0.01, 0.15) = 0.15
        self.assertTrue(watch.in_ingresso(110.0, 100.0, 100.0, 99.9, 105.0))
        self.assertFalse(watch.in_ingresso(110.0, 100.0, 100.0, 90.0, 99.8))

    def test_fetch_day_range_empty_or_error_is_none(self) -> None:
        class EmptyHist:
            empty = True

        class FakeTicker:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def history(self, **kwargs: object) -> EmptyHist:
                return EmptyHist()

        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker()
            self.assertIsNone(watch.fetch_day_range("AMD"))
        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.side_effect = RuntimeError("down")
            self.assertIsNone(watch.fetch_day_range("AMD"))

    def test_fetch_day_range_returns_low_high(self) -> None:
        class Col:
            def __init__(self, values: list[float]) -> None:
                self._values = values

            def min(self) -> float:
                return min(self._values)

            def max(self) -> float:
                return max(self._values)

        class Hist:
            empty = False

            def __getitem__(self, key: str) -> Col:
                return {"Low": Col([10.5, 11.0]), "High": Col([12.0, 13.25])}[key]

        class FakeTicker:
            def history(self, **kwargs: object) -> Hist:
                return Hist()

        with patch.object(watch, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker()
            self.assertEqual(watch.fetch_day_range("AMD"), (10.5, 13.25))
            self.assertEqual(
                watch.fetch_day_ranges(["AMD", "NVDA"]),
                {"AMD": (10.5, 13.25), "NVDA": (10.5, 13.25)},
            )

    def test_cycle_uses_day_range_and_notes_intraday_touch(self) -> None:
        item = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": 130.0,
            "ingresso_high": 134.0,
            "stop": 124.0,
            "target": 148.0,
            "motivo": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            fired: dict[tuple[str, str, str], bool] = {}
            with (
                patch.object(watch, "fetch_prices", return_value={"AMD": 140.0}),
                patch.object(watch, "fetch_day_ranges", return_value={"AMD": (120.0, 135.0)}),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "expire_sent_alerts"),
            ):
                watch.cycle([item], fired, spath)
            texts = [call[0][0] for call in send.call_args_list]
            self.assertTrue(any("ingresso" in t and "toccato in giornata, ora 140.00" in t for t in texts))
            self.assertTrue(any("stop" in t and "toccato in giornata, ora 140.00" in t for t in texts))
            self.assertFalse(any("target" in t for t in texts))

    def test_cycle_falls_back_to_spot_when_range_missing(self) -> None:
        item = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": 130.0,
            "ingresso_high": 134.0,
            "stop": 124.0,
            "target": 148.0,
            "motivo": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            fired: dict[tuple[str, str, str], bool] = {}
            with (
                patch.object(watch, "fetch_prices", return_value={"AMD": 132.0}),
                patch.object(watch, "fetch_day_ranges", return_value={"AMD": None}),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "expire_sent_alerts"),
            ):
                watch.cycle([item], fired, spath)
            texts = [call[0][0] for call in send.call_args_list]
            self.assertEqual(len(texts), 1)
            self.assertIn("ingresso 132.00", texts[0])
            self.assertNotIn("toccato in giornata", texts[0])


if __name__ == "__main__":
    unittest.main()
