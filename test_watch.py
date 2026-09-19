#!/usr/bin/env python3
"""Test parser ticket + ingest Telegram (senza rete)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import watch


def sent_text(mock) -> str:
    return mock.call_args[0][0]


def with_nav(rows: list) -> list:
    return list(rows) + list(watch.MENU_NAV_BUTTONS)


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


class MergeTicketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": 134.26,
            "ingresso_high": 142.3,
            "stop": 122.78,
            "target": 162.96,
            "motivo": "Screener automatico (4/4 ✅)",
        }

    def test_keeps_levels_and_motivo_when_incoming_empty(self) -> None:
        incoming = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": None,
            "ingresso_high": None,
            "stop": None,
            "target": None,
            "motivo": "",
        }
        merged = watch.merge_ticket(self.existing, incoming)
        self.assertEqual(merged["ingresso_low"], 134.26)
        self.assertEqual(merged["ingresso_high"], 142.3)
        self.assertEqual(merged["stop"], 122.78)
        self.assertEqual(merged["target"], 162.96)
        self.assertEqual(merged["motivo"], "Screener automatico (4/4 ✅)")
        self.assertEqual(merged["ticker"], "AMD")
        self.assertEqual(merged["tf"], "daily")
        self.assertEqual(self.existing["ingresso_low"], 134.26)

    def test_overwrites_only_provided_fields(self) -> None:
        incoming = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": None,
            "ingresso_high": None,
            "stop": 120.0,
            "target": None,
            "motivo": "Danny: nuovo motivo",
        }
        merged = watch.merge_ticket(self.existing, incoming)
        self.assertEqual(merged["ingresso_low"], 134.26)
        self.assertEqual(merged["stop"], 120.0)
        self.assertEqual(merged["target"], 162.96)
        self.assertEqual(merged["motivo"], "Danny: nuovo motivo")


class ShouldDeleteChatMessageTests(unittest.TestCase):
    def test_keeps_bot_digests(self) -> None:
        self.assertFalse(watch.should_delete_chat_message("📋 AMD  ing 130-134"))
        self.assertFalse(watch.should_delete_chat_message("📊 Posizioni aperte:"))
        self.assertFalse(watch.should_delete_chat_message("ALERT AMD ingresso 131"))
        self.assertFalse(watch.should_delete_chat_message("Watchlist vuota."))
        self.assertFalse(watch.should_delete_chat_message("💰 Conto U123"))
        self.assertFalse(watch.should_delete_chat_message("📈 AMD (IBKR): 148.20"))
        self.assertFalse(watch.should_delete_chat_message("⚠️ Prezzo IBKR non disponibile per NVDA."))
        self.assertFalse(watch.should_delete_chat_message("🚫 Ordine per AMD annullato."))
        self.assertFalse(watch.should_delete_chat_message("📭 Nessuna posizione aperta."))
        self.assertFalse(watch.should_delete_chat_message("📜 Ordini eseguiti (ultimi 7 giorni):"))
        self.assertFalse(watch.should_delete_chat_message("📢 IBKR: Margin warning"))
        self.assertTrue(watch.should_delete_chat_message("/scan"))


class FmtTicketLineTests(unittest.TestCase):
    def test_compact_line_with_emoji_and_missing(self) -> None:
        self.assertEqual(
            watch.fmt_ticket_line(
                {
                    "ticker": "AMD",
                    "ingresso_low": 485.34,
                    "ingresso_high": 499.34,
                    "stop": 465.33,
                    "target": 535.35,
                    "motivo": "⚠️",
                }
            ),
            "AMD i 485.34-499.34 s 465.33 t 535.35 ⚠️",
        )
        self.assertEqual(
            watch.fmt_ticket_line({"ticker": "HOOD"}),
            "HOOD i — s — t —",
        )


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
            self.assertIn("i 130-134", body)
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

    def test_ingest_keeps_existing_levels_on_ticker_only_ticket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "daily",
                        "ingresso_low": 134.26,
                        "ingresso_high": 142.3,
                        "stop": 122.78,
                        "target": 162.96,
                        "motivo": "Screener automatico (4/4 ✅)",
                    }
                ],
            )
            updates = [{"update_id": 90, "message": _msg(text="$AMD · daily")}]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 1)
            send.assert_not_called()
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["ingresso_low"], 134.26)
            self.assertEqual(item["ingresso_high"], 142.3)
            self.assertEqual(item["stop"], 122.78)
            self.assertEqual(item["target"], 162.96)
            self.assertEqual(item["motivo"], "Screener automatico (4/4 ✅)")

    def test_ingest_merges_only_incoming_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "daily",
                        "ingresso_low": 134.26,
                        "ingresso_high": 142.3,
                        "stop": 122.78,
                        "target": 162.96,
                        "motivo": "Screener automatico (4/4 ✅)",
                    }
                ],
            )
            updates = [{"update_id": 91, "message": _msg(text="$AMD · daily\nstop 120")}]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 1)
            send.assert_called_once()
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["ingresso_low"], 134.26)
            self.assertEqual(item["stop"], 120.0)
            self.assertEqual(item["target"], 162.96)
            self.assertEqual(item["motivo"], "Screener automatico (4/4 ✅)")

    def test_ingest_empty_ticket_does_not_fill_levels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            updates = [{"update_id": 92, "message": _msg(text="$NVDA")}]
            with (
                patch.object(watch, "telegram_token", return_value="123:abc"),
                patch.object(watch, "telegram_get_updates", return_value=updates),
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram", return_value=1) as send,
            ):
                n = watch.ingest_telegram(wpath, spath)
            self.assertEqual(n, 1)
            send.assert_called()
            body = send.call_args[0][0]
            self.assertIn("✅ NVDA aggiunto/aggiornato", body)
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["ticker"], "NVDA")
            self.assertIsNone(item["ingresso_low"])

    def test_process_single_message_upserts_ticket_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(TICKET, 77, wpath, spath)
            self.assertEqual(added, ["AMD"])
            self.assertEqual(removed, [])
            delete.assert_called_once_with(77)
            self.assertEqual(watch.load_watchlist(wpath)[0]["ticker"], "AMD")

    def test_process_single_message_rejects_non_equity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "classify_ticker", return_value="INDEX"),
                patch.object(watch, "delete_telegram_message"),
            ):
                added, removed = watch.process_single_message(
                    TICKET.replace("$AMD", "$KOSPI"), 8, wpath, spath
                )
            self.assertEqual(added, [])
            self.assertEqual(removed, ["KOSPI scartato (non è un'azione/ETF)"])
            self.assertEqual(watch.load_watchlist(wpath), [])

    def test_apply_telegram_balance_sends_ledger(self) -> None:
        def fake_get(path: str):
            if path.endswith("/accounts"):
                return [{"accountId": "U123"}]
            return {
                "BASE": {
                    "cashbalance": 1000.5,
                    "netliquidationvalue": 5000.25,
                    "currency": "USD",
                }
            }

        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get", side_effect=fake_get),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
                self.assertTrue(watch.apply_telegram_balance("/SALDO", spath))
                self.assertFalse(watch.apply_telegram_balance("/list", spath))
            self.assertEqual(send.call_count, 2)
            body = send.call_args_list[0][0][0]
            self.assertIn("💰 Conto U123", body)
            self.assertIn("Contanti: 1000.5 USD", body)
            self.assertIn("Valore netto: 5000.25 USD", body)

    def test_apply_telegram_balance_uses_first_currency_without_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch,
                    "ibkr_get",
                    side_effect=[
                        [{"accountId": "U9"}],
                        {
                            "EUR": {
                                "cashbalance": 10,
                                "netliquidationvalue": 20,
                                "currency": "EUR",
                            }
                        },
                    ],
                ),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            self.assertEqual(sent_text(send), "💰 Conto U9\nContanti: 10 EUR\nValore netto: 20 EUR")

    def test_apply_telegram_balance_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile leggere il conto IBKR al momento.")
            with (
                patch.object(
                    watch, "ibkr_get", side_effect=[[{"accountId": "U1"}], None]
                ),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile leggere il saldo al momento.")

    def test_apply_telegram_balance_replaces_previous_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"balance_message_id": 99})
            with (
                patch.object(
                    watch,
                    "ibkr_get",
                    side_effect=[
                        [{"accountId": "U123"}],
                        {
                            "BASE": {
                                "cashbalance": 1,
                                "netliquidationvalue": 2,
                                "currency": "USD",
                            }
                        },
                    ],
                ),
                patch.object(watch, "send_telegram", return_value=101) as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            delete.assert_called_once_with(99)
            send.assert_called_once()
            self.assertEqual(watch.load_state(spath)["balance_message_id"], 101)

    def test_process_single_message_runs_saldo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_balance", return_value=True) as bal,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message("/saldo", 12, wpath, spath)
            self.assertEqual(added, [])
            self.assertEqual(removed, [])
            bal.assert_called_once_with("/saldo", spath)
            delete.assert_called_once_with(12)

    def test_ibkr_lookup_conid_caches(self) -> None:
        watch._CONID_CACHE.clear()
        payload = {"AMD": [{"contracts": [{"conid": 4391}]}]}
        with patch.object(watch, "ibkr_get", return_value=payload) as get:
            self.assertEqual(watch.ibkr_lookup_conid("amd"), "4391")
            self.assertEqual(watch.ibkr_lookup_conid("AMD"), "4391")
        get.assert_called_once_with("/v1/api/trsrv/stocks?symbols=AMD")

    def test_ibkr_lookup_conid_prefers_us_contract(self) -> None:
        watch._CONID_CACHE.clear()
        payload = {
            "BE": [
                {
                    "name": "BELEAVE INC",
                    "contracts": [{"conid": 111, "isUS": False}],
                },
                {
                    "name": "BLOOM ENERGY CORP",
                    "contracts": [{"conid": 222, "isUS": True}],
                },
            ]
        }
        with patch.object(watch, "ibkr_get", return_value=payload):
            self.assertEqual(watch.ibkr_lookup_conid("BE"), "222")

    def test_ibkr_lookup_conid_falls_back_without_us(self) -> None:
        watch._CONID_CACHE.clear()
        payload = {
            "XYZ": [
                {"contracts": [{"conid": 10, "isUS": False}]},
                {"contracts": [{"conid": 20, "isUS": False}]},
            ]
        }
        with patch.object(watch, "ibkr_get", return_value=payload):
            self.assertEqual(watch.ibkr_lookup_conid("XYZ"), "10")

    def test_ibkr_get_price_parses_prefixed_field(self) -> None:
        watch._CONID_CACHE["AMD"] = "4391"
        with (
            patch.object(watch, "ibkr_get", return_value=[{"31": "C148.25"}]),
            patch.object(watch, "time") as time_mod,
        ):
            time_mod.sleep.return_value = None
            self.assertEqual(watch.ibkr_get_price("AMD"), 148.25)
            time_mod.sleep.assert_called_once_with(1)

    def test_fetch_price_uses_ibkr_then_yahoo(self) -> None:
        with (
            patch.object(watch, "ibkr_get_price", return_value=11.5),
            patch.object(watch, "_fetch_price_yahoo") as yahoo,
        ):
            self.assertEqual(watch.fetch_price("AMD"), 11.5)
            yahoo.assert_not_called()
        with (
            patch.object(watch, "ibkr_get_price", return_value=None),
            patch.object(watch, "_fetch_price_yahoo", return_value=10.0) as yahoo,
        ):
            self.assertEqual(watch.fetch_price("AMD"), 10.0)
            yahoo.assert_called_once_with("AMD")

    def test_apply_telegram_price_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get_price", return_value=148.2),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_price("/prezzo $amd", spath))
                self.assertFalse(watch.apply_telegram_price("/saldo", spath))
            self.assertEqual(sent_text(send), "📈 AMD (IBKR): 148.20")
            with (
                patch.object(watch, "ibkr_get_price", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_price("/prezzo NVDA", spath))
            self.assertEqual(sent_text(send), "⚠️ Prezzo IBKR non disponibile per NVDA.")

    def test_apply_telegram_price_replaces_previous_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"price_message_id": 44})
            with (
                patch.object(watch, "ibkr_get_price", return_value=10.5),
                patch.object(watch, "send_telegram", return_value=55) as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                self.assertTrue(watch.apply_telegram_price("/prezzo AMD", spath))
            delete.assert_called_once_with(44)
            self.assertEqual(sent_text(send), "📈 AMD (IBKR): 10.50")
            self.assertEqual(watch.load_state(spath)["price_message_id"], 55)

    def test_process_single_message_runs_prezzo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_price", return_value=True) as price,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/prezzo AMD", 13, wpath, spath
                )
            self.assertEqual(added, [])
            self.assertEqual(removed, [])
            price.assert_called_once_with("/prezzo AMD", spath)
            delete.assert_called_once_with(13)

    def test_ibkr_get_account_id_caches(self) -> None:
        watch._ACCOUNT_ID_CACHE = None
        with patch.object(
            watch, "ibkr_get", return_value=[{"accountId": "U123"}]
        ) as get:
            self.assertEqual(watch.ibkr_get_account_id(), "U123")
            self.assertEqual(watch.ibkr_get_account_id(), "U123")
        get.assert_called_once_with("/v1/api/portfolio/accounts")
        watch._ACCOUNT_ID_CACHE = None

    def test_ibkr_place_order_auto_limit_and_manual(self) -> None:
        watch._ACCOUNT_ID_CACHE = None
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_get_price", return_value=100.0),
            patch.object(
                watch, "ibkr_post", return_value=[{"order_id": 77}]
            ) as post,
        ):
            self.assertEqual(
                watch.ibkr_place_order("AMD", 2, "BUY", None),
                "✅ Ordine BUY 2 AMD @ 100.50 (auto, ~mercato) inviato.",
            )
            self.assertEqual(
                watch.ibkr_place_order("AMD", 3, "SELL", 10.5),
                "✅ Ordine SELL 3 AMD @ 10.5 inviato.",
            )
            self.assertEqual(
                watch.ibkr_place_order("AMD", 1, "SELL", None),
                "✅ Ordine SELL 1 AMD @ 99.50 (auto, ~mercato) inviato.",
            )
        self.assertEqual(
            post.call_args_list[0][0],
            (
                "/v1/api/iserver/account/U123/orders",
                {
                    "orders": [
                        {
                            "conid": 4391,
                            "orderType": "LMT",
                            "side": "BUY",
                            "quantity": 2,
                            "price": 100.5,
                            "tif": "DAY",
                            "outsideRTH": True,
                        }
                    ]
                },
            ),
        )
        self.assertEqual(
            post.call_args_list[1][0][1],
            {
                "orders": [
                    {
                        "conid": 4391,
                        "orderType": "LMT",
                        "side": "SELL",
                        "quantity": 3,
                        "price": 10.5,
                        "tif": "DAY",
                        "outsideRTH": True,
                    }
                ]
            },
        )

    def test_ibkr_place_order_confirms_questions(self) -> None:
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_get_price", return_value=20.0),
            patch.object(
                watch,
                "ibkr_post",
                side_effect=[
                    [{"id": "q1", "message": ["Confirm?"]}],
                    [{"orderId": 88}],
                ],
            ) as post,
        ):
            msg = watch.ibkr_place_order("BE", 1, "BUY", None)
        self.assertEqual(
            msg, "✅ Ordine BUY 1 BE @ 20.10 (auto, ~mercato) inviato."
        )
        self.assertEqual(
            post.call_args_list[1][0],
            ("/v1/api/iserver/reply/q1", {"confirmed": True}),
        )

    def test_ensure_reply_suppression_is_best_effort(self) -> None:
        with patch.object(watch, "ibkr_post") as post:
            watch.ensure_reply_suppression()
        post.assert_called_once_with(
            "/v1/api/iserver/questions/suppress",
            {
                "messageIds": [
                    "o163",
                    "o354",
                    "o382",
                    "o383",
                    "o403",
                    "o451",
                    "o10151",
                    "o10152",
                    "o10153",
                    "o10164",
                    "o10223",
                    "o10331",
                    "o10336",
                    "p12",
                ]
            },
        )
        with patch.object(watch, "ibkr_post", side_effect=RuntimeError("down")):
            watch.ensure_reply_suppression()

    def test_ibkr_place_cash_order_uses_cashqty(self) -> None:
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(
                watch,
                "ibkr_post",
                side_effect=[
                    [{"id": "q1", "message": ["Confirm?"]}],
                    [{"order_id": 91}],
                ],
            ) as post,
        ):
            msg = watch.ibkr_place_cash_order("amd", "BUY", 3.0)
        self.assertEqual(
            msg, "✅ Ordine BUY AMD $3.00 (MKT, cashQty) inviato."
        )
        self.assertEqual(
            post.call_args_list[0][0],
            (
                "/v1/api/iserver/account/U123/orders",
                {
                    "orders": [
                        {
                            "conid": 4391,
                            "orderType": "MKT",
                            "side": "BUY",
                            "cashQty": 3.0,
                            "tif": "DAY",
                        }
                    ]
                },
            ),
        )
        self.assertEqual(
            post.call_args_list[1][0],
            ("/v1/api/iserver/reply/q1", {"confirmed": True}),
        )
        with patch.object(watch, "ibkr_lookup_conid", return_value=None):
            self.assertEqual(
                watch.ibkr_place_cash_order("ZZZ", "BUY", 3.0),
                "⚠️ Impossibile trovare ZZZ su IBKR.",
            )

    def test_ibkr_place_order_errors(self) -> None:
        with patch.object(watch, "ibkr_lookup_conid", return_value=None):
            self.assertEqual(
                watch.ibkr_place_order("ZZZ", 1, "BUY", None),
                "⚠️ Impossibile trovare ZZZ su IBKR.",
            )
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value=None),
        ):
            self.assertEqual(
                watch.ibkr_place_order("AMD", 1, "BUY", None),
                "⚠️ Impossibile leggere l'account IBKR.",
            )
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(watch, "ibkr_get_price", return_value=None),
        ):
            self.assertEqual(
                watch.ibkr_place_order("AMD", 1, "BUY", None),
                "⚠️ Impossibile determinare un prezzo per AMD.",
            )
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(watch, "ibkr_get_price", return_value=10.0),
            patch.object(watch, "ibkr_post", return_value=None),
        ):
            self.assertEqual(
                watch.ibkr_place_order("AMD", 1, "BUY", None),
                "⚠️ Errore nell'invio dell'ordine.",
            )
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(
                watch, "ibkr_post", return_value=[{"id": "q", "message": "x"}]
            ),
        ):
            self.assertEqual(
                watch.ibkr_place_order("AMD", 1, "SELL", 9),
                "⚠️ IBKR ha chiesto troppe conferme.",
            )

    def test_ibkr_place_order_confirms_message_ids_only(self) -> None:
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(
                watch,
                "ibkr_post",
                side_effect=[
                    [{"id": "q1", "messageIds": ["o163"]}],
                    [{"order_id": 44, "order_status": "Submitted"}],
                ],
            ) as post,
        ):
            self.assertEqual(
                watch.ibkr_place_order("SLNH", 1, "BUY", 1.01),
                "✅ Ordine BUY 1 SLNH @ 1.01 inviato.",
            )
        self.assertEqual(
            post.call_args_list[1][0],
            ("/v1/api/iserver/reply/q1", {"confirmed": True}),
        )

    def test_ibkr_place_order_reads_order_id_not_first(self) -> None:
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(
                watch,
                "ibkr_post",
                return_value=[
                    {"encrypt_message": "1"},
                    {"order_id": 55, "order_status": "Submitted"},
                ],
            ),
        ):
            self.assertEqual(
                watch.ibkr_place_order("SLNH", 1, "BUY", 1.01),
                "✅ Ordine BUY 1 SLNH @ 1.01 inviato.",
            )

    def test_ibkr_place_order_shows_ibkr_error(self) -> None:
        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="1"),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(
                watch,
                "ibkr_post",
                return_value={
                    "error": (
                        "We cannot accept an order at the limit price you "
                        "selected. Please submit your order using a limit "
                        "price that is closer to the current market price "
                        "of 2.00."
                    )
                },
            ),
        ):
            msg = watch.ibkr_place_order("SLNH", 1, "BUY", 1.01)
        self.assertTrue(msg.startswith("⚠️ We cannot accept an order"))
        self.assertIn("closer to the current market price", msg)

    def test_apply_telegram_buy_and_sell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "ibkr_place_order", return_value="✅ ok"
                ) as place,
                patch.object(watch, "send_telegram", return_value=50) as send,
            ):
                self.assertTrue(watch.apply_telegram_buy("/compra $amd 2", spath))
                self.assertTrue(watch.apply_telegram_buy("/compra NVDA 1 148.2", spath))
                self.assertFalse(watch.apply_telegram_buy("/vendi AMD 1", spath))
                self.assertTrue(watch.apply_telegram_sell("/vendi AMD 3", spath))
                self.assertTrue(watch.apply_telegram_sell("/vendi $be 2 22.5", spath))
                self.assertFalse(watch.apply_telegram_sell("/compra AMD 1", spath))
            self.assertEqual(
                [c.args for c in place.call_args_list],
                [
                    ("AMD", 2, "BUY", None),
                    ("NVDA", 1, "BUY", 148.2),
                    ("AMD", 3, "SELL", None),
                    ("BE", 2, "SELL", 22.5),
                ],
            )
            self.assertEqual(send.call_count, 4)
            self.assertEqual(len(watch.load_state(spath)["order_messages"]), 4)

    def test_process_single_message_runs_compra_vendi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_buy", return_value=True) as buy,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/compra AMD 1", 21, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            buy.assert_called_once_with("/compra AMD 1", spath)
            delete.assert_called_once_with(21)
            with (
                patch.object(watch, "apply_telegram_sell", return_value=True) as sell,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/vendi AMD 1 10", 22, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            sell.assert_called_once_with("/vendi AMD 1 10", spath)
            delete.assert_called_once_with(22)

    def test_apply_telegram_trail_places_sell(self) -> None:
        self.assertTrue(watch.TRAIL_RE.match("/trail AMD 2 1.5"))
        self.assertTrue(watch.TRAIL_RE.match("/TRAIL $hood 1 0.75"))
        self.assertIsNone(watch.TRAIL_RE.match("/trail AMD 2"))
        self.assertIsNone(watch.TRAIL_RE.match("/testtrail AMD 2 1.5"))
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_lookup_conid", return_value=None),
                patch.object(watch, "send_telegram", return_value=1) as send,
            ):
                self.assertTrue(watch.apply_telegram_trail("/trail AMD 2 1.5", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile trovare AMD su IBKR.")
            with (
                patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
                patch.object(watch, "ibkr_get_account_id", return_value=None),
                patch.object(watch, "send_telegram", return_value=2) as send,
            ):
                self.assertTrue(watch.apply_telegram_trail("/trail AMD 2 1.5", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile leggere l'account IBKR.")
            with (
                patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
                patch.object(watch, "ibkr_get_account_id", return_value="U123"),
                patch.object(watch, "ibkr_get_price", return_value=None),
                patch.object(watch, "send_telegram", return_value=3) as send,
            ):
                self.assertTrue(watch.apply_telegram_trail("/trail AMD 2 1.5", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile determinare un prezzo per AMD.")
            with (
                patch.object(watch, "ibkr_lookup_conid", return_value="4391"),
                patch.object(watch, "ibkr_get_account_id", return_value="U123"),
                patch.object(watch, "ibkr_get_price", return_value=148.2),
                patch.object(
                    watch, "ibkr_post", return_value=[{"order_id": 99}]
                ) as post,
                patch.object(watch, "send_telegram", return_value=4) as send,
            ):
                self.assertTrue(
                    watch.apply_telegram_trail("/trail $amd 3 2.25", spath)
                )
                self.assertFalse(watch.apply_telegram_trail("/vendi AMD 1", spath))
            post.assert_called_once_with(
                "/v1/api/iserver/account/U123/orders",
                {
                    "orders": [
                        {
                            "conid": 4391,
                            "orderType": "TRAIL",
                            "side": "SELL",
                            "quantity": 3,
                            "price": 148.2,
                            "trailingAmt": 2.25,
                            "trailingType": "amt",
                            "tif": "DAY",
                        }
                    ]
                },
            )
            self.assertEqual(sent_text(send), "✅ Ordine SELL 3 AMD TRAIL 2.25 inviato.")
            self.assertEqual(len(watch.load_state(spath)["order_messages"]), 4)
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "apply_telegram_trail", return_value=True
                ) as trail,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/trail AMD 2 1.5", 23, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            trail.assert_called_once_with("/trail AMD 2 1.5", spath)
            delete.assert_called_once_with(23)

    def test_ibkr_cancel_order_one_and_many(self) -> None:
        payload = {
            "orders": [
                {"ticker": "amd", "status": "Submitted", "orderId": 11},
                {"ticker": "AMD", "status": "Filled", "orderId": 12},
                {"ticker": "NVDA", "status": "Submitted", "orderId": 13},
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_delete", return_value={"ok": True}) as delete,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "🚫 Ordine per AMD annullato.",
            )
        delete.assert_called_once_with("/v1/api/iserver/account/U123/order/11")

        payload["orders"].append(
            {"ticker": "AMD", "status": "PreSubmitted", "orderId": 14}
        )
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_delete", return_value={"ok": True}) as delete,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("amd"),
                "🚫 2 ordini per AMD annullati.",
            )
        self.assertEqual(
            [c.args[0] for c in delete.call_args_list],
            [
                "/v1/api/iserver/account/U123/order/11",
                "/v1/api/iserver/account/U123/order/14",
            ],
        )

    def test_ibkr_cancel_order_errors(self) -> None:
        with patch.object(watch, "ibkr_get", return_value=None), patch.object(
            watch.time, "sleep"
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Impossibile leggere gli ordini aperti.",
            )
        with patch.object(watch, "ibkr_get", return_value={"orders": []}), patch.object(
            watch.time, "sleep"
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Nessun ordine aperto trovato per AMD.",
            )
        with (
            patch.object(
                watch,
                "ibkr_get",
                return_value={
                    "orders": [
                        {"ticker": "AMD", "status": "Submitted", "orderId": 9}
                    ]
                },
            ),
            patch.object(watch, "ibkr_get_account_id", return_value="U1"),
            patch.object(watch, "ibkr_delete", return_value=None),
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Errore nell'annullamento dell'ordine per AMD.",
            )

    def test_apply_telegram_cancel_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch,
                    "ibkr_cancel_order",
                    return_value="🚫 Ordine per AMD annullato.",
                ) as cancel,
                patch.object(watch, "send_telegram", return_value=41) as send,
            ):
                self.assertTrue(
                    watch.apply_telegram_cancel_order("/annulla $amd", spath)
                )
                self.assertTrue(
                    watch.apply_telegram_cancel_order("/ANNULLA NVDA", spath)
                )
                self.assertFalse(
                    watch.apply_telegram_cancel_order("/vendi AMD 1", spath)
                )
            self.assertEqual(
                [c.args[0] for c in cancel.call_args_list], ["AMD", "NVDA"]
            )
            self.assertEqual(send.call_count, 2)
            self.assertEqual(len(watch.load_state(spath)["order_messages"]), 2)

    def test_process_single_message_runs_annulla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "apply_telegram_cancel_order", return_value=True
                ) as cancel,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/annulla AMD", 23, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            cancel.assert_called_once_with("/annulla AMD", spath)
            delete.assert_called_once_with(23)

    def test_ibkr_modify_order_updates_limit_price(self) -> None:
        payload = {
            "orders": [
                {
                    "ticker": "amd",
                    "status": "Submitted",
                    "orderId": 11,
                    "conid": 4391,
                    "side": "SELL",
                    "remainingQuantity": 2,
                    "orderType": "Limit",
                },
                {
                    "ticker": "AMD",
                    "status": "Filled",
                    "orderId": 12,
                    "conid": 4391,
                    "side": "SELL",
                    "remainingQuantity": 1,
                    "orderType": "LMT",
                },
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(
                watch, "ibkr_post", return_value=[{"order_id": 11}]
            ) as post,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_modify_order("AMD", 148.5),
                "✅ Ordine AMD modificato a 148.50.",
            )
        post.assert_called_once_with(
            "/v1/api/iserver/account/U123/order/11",
            {
                "conid": 4391,
                "orderType": "LMT",
                "side": "SELL",
                "quantity": 2,
                "price": 148.5,
                "tif": "DAY",
            },
        )
        trail = {
            "orders": [
                {
                    "ticker": "AMD",
                    "status": "Submitted",
                    "orderId": 20,
                    "conid": 4391,
                    "side": "SELL",
                    "totalSize": 3,
                    "orderType": "TRAIL",
                }
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=trail),
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_modify_order("AMD", 10.0),
                "⚠️ Impossibile modificare un ordine di tipo TRAIL, solo ordini a limite.",
            )
        with (
            patch.object(watch, "ibkr_get", return_value={"orders": []}),
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_modify_order("NVDA", 100.0),
                "⚠️ Nessun ordine aperto trovato per NVDA.",
            )

    def test_ibkr_modify_order_skips_trail_and_updates_limits(self) -> None:
        payload = {
            "orders": [
                {
                    "ticker": "SLNH",
                    "status": "Inactive",
                    "orderId": 1,
                    "conid": 55,
                    "side": "SELL",
                    "remainingQuantity": 1,
                    "orderType": "TRAILING_STOP",
                },
                {
                    "ticker": "SLNH",
                    "status": "Submitted",
                    "orderId": 9,
                    "conid": 55,
                    "side": "SELL",
                    "remainingQuantity": 1,
                    "orderType": "TRAILING_STOP",
                },
                {
                    "ticker": "SLNH",
                    "status": "PendingSubmit",
                    "orderId": 2,
                    "conid": 55,
                    "side": "BUY",
                    "remainingQuantity": 1,
                    "price": 2.0,
                    "orderType": "LMT",
                },
                {
                    "ticker": "SLNH",
                    "status": "Submitted",
                    "orderId": 3,
                    "conid": 55,
                    "side": "BUY",
                    "remainingQuantity": 1,
                    "price": 1.01,
                    "orderType": "LMT",
                },
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(
                watch, "ibkr_post", return_value=[{"order_id": 3}]
            ) as post,
            patch.object(watch, "ibkr_delete", return_value={"ok": True}) as delete,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_modify_order("SLNH", 0.9),
                "✅ Ordine SLNH modificato a 0.90.",
            )
        post.assert_called_once_with(
            "/v1/api/iserver/account/U123/order/3",
            {
                "conid": 55,
                "orderType": "LMT",
                "side": "BUY",
                "quantity": 1,
                "price": 0.9,
                "tif": "DAY",
            },
        )
        delete.assert_called_once_with("/v1/api/iserver/account/U123/order/2")

    def test_ibkr_modify_order_updates_pending_when_no_submitted(self) -> None:
        payload = {
            "orders": [
                {
                    "ticker": "SLNH",
                    "status": "PendingSubmit",
                    "orderId": 2,
                    "conid": 55,
                    "side": "BUY",
                    "remainingQuantity": 1,
                    "price": 2.0,
                    "orderType": "LMT",
                }
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(
                watch, "ibkr_post", return_value=[{"order_id": 2}]
            ) as post,
            patch.object(watch, "ibkr_delete") as delete,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_modify_order("SLNH", 1.05),
                "✅ Ordine SLNH modificato a 1.05.",
            )
        post.assert_called_once_with(
            "/v1/api/iserver/account/U123/order/2",
            {
                "conid": 55,
                "orderType": "LMT",
                "side": "BUY",
                "quantity": 1,
                "price": 1.05,
                "tif": "DAY",
            },
        )
        delete.assert_not_called()

    def test_ibkr_cancel_order_skips_inactive(self) -> None:
        payload = {
            "orders": [
                {
                    "ticker": "SLNH",
                    "status": "Inactive",
                    "orderId": 1,
                    "orderType": "TRAILING_STOP",
                },
                {
                    "ticker": "SLNH",
                    "status": "PendingSubmit",
                    "orderId": 2,
                    "orderType": "LMT",
                },
                {
                    "ticker": "SLNH",
                    "status": "Submitted",
                    "orderId": 3,
                    "orderType": "LMT",
                },
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload),
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_delete", return_value={"ok": True}) as delete,
            patch.object(watch.time, "sleep"),
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("SLNH"),
                "🚫 2 ordini per SLNH annullati.",
            )
        self.assertEqual(
            [c.args[0] for c in delete.call_args_list],
            [
                "/v1/api/iserver/account/U123/order/2",
                "/v1/api/iserver/account/U123/order/3",
            ],
        )

    def test_apply_telegram_modify_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch,
                    "ibkr_modify_order",
                    return_value="✅ Ordine AMD modificato a 150.00.",
                ) as modify,
                patch.object(watch, "send_telegram", return_value=42) as send,
            ):
                self.assertTrue(
                    watch.apply_telegram_modify_order("/modifica $amd 150", spath)
                )
                self.assertTrue(
                    watch.apply_telegram_modify_order("/MODIFICA NVDA 99.5", spath)
                )
                self.assertFalse(
                    watch.apply_telegram_modify_order("/annulla AMD", spath)
                )
            self.assertEqual(
                [c.args for c in modify.call_args_list],
                [("AMD", 150.0), ("NVDA", 99.5)],
            )
            self.assertEqual(send.call_count, 2)
            self.assertEqual(len(watch.load_state(spath)["order_messages"]), 2)
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "apply_telegram_modify_order", return_value=True
                ) as apply_mod,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/modifica AMD 150", 24, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            apply_mod.assert_called_once_with("/modifica AMD 150", spath)
            delete.assert_called_once_with(24)

    def test_ibkr_get_positions_retries_when_empty(self) -> None:
        with (
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(watch, "ibkr_get", side_effect=[[], [{"ticker": "AMD"}]]) as get,
            patch.object(watch, "time") as time_mod,
        ):
            time_mod.sleep.return_value = None
            self.assertEqual(
                watch.ibkr_get_positions(),
                [{"ticker": "AMD"}],
            )
        time_mod.sleep.assert_called_once_with(1)
        self.assertEqual(get.call_count, 2)
        get.assert_called_with("/v1/api/portfolio/U123/positions/0")

    def test_ibkr_get_positions_retries_when_first_lacks_ticker(self) -> None:
        with (
            patch.object(watch, "ibkr_get_account_id", return_value="U123"),
            patch.object(
                watch,
                "ibkr_get",
                side_effect=[[{"conid": 1}], [{"ticker": "AMD", "position": 2}]],
            ) as get,
            patch.object(watch, "time") as time_mod,
        ):
            time_mod.sleep.return_value = None
            self.assertEqual(
                watch.ibkr_get_positions(),
                [{"ticker": "AMD", "position": 2}],
            )
        time_mod.sleep.assert_called_once_with(1)
        self.assertEqual(get.call_count, 2)

    def test_apply_telegram_positions(self) -> None:
        rows = [
            {
                "ticker": "AMD",
                "position": 10,
                "avgCost": 100.5,
                "mktValue": 1100.25,
                "currency": "USD",
                "unrealizedPnl": 95.0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get_positions", return_value=rows),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
                self.assertTrue(watch.apply_telegram_positions("/POSIZIONI", spath))
                self.assertFalse(watch.apply_telegram_positions("/saldo", spath))
            body = send.call_args_list[0][0][0]
            self.assertIn("📊 Posizioni aperte:", body)
            self.assertIn("AMD: 10 @ 100.50", body)
            self.assertIn("valore: 1100.25 USD", body)
            self.assertIn("P&L: +95.00", body)
            with (
                patch.object(watch, "ibkr_get_positions", return_value=[]),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
            self.assertEqual(sent_text(send), "📭 Nessuna posizione aperta.")
            with (
                patch.object(watch, "ibkr_get_positions", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
            self.assertEqual(sent_text(send), "⚠️ Impossibile leggere le posizioni al momento.")
            with (
                patch.object(
                    watch,
                    "ibkr_get_positions",
                    return_value=[
                        {"ticker": "AMD", "position": 0, "avgCost": 1, "mktValue": 0},
                        {"ticker": "NVDA", "position": None},
                    ],
                ),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
            self.assertEqual(sent_text(send), "📭 Nessuna posizione aperta.")
            mixed = [
                {"ticker": "CASH", "position": 0, "avgCost": 0, "mktValue": 0, "currency": "USD", "unrealizedPnl": 0},
                {
                    "ticker": "AMD",
                    "position": 10,
                    "avgCost": 100.5,
                    "mktValue": 1100.25,
                    "currency": "USD",
                    "unrealizedPnl": 95.0,
                },
            ]
            with (
                patch.object(watch, "ibkr_get_positions", return_value=mixed),
                patch.object(watch, "send_telegram", return_value=88) as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
            body = send.call_args[0][0]
            self.assertIn("AMD: 10 @ 100.50", body)
            self.assertNotIn("CASH", body)
            self.assertEqual(watch.load_state(spath)["positions_message_id"], 88)

    def test_process_single_message_runs_posizioni(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "apply_telegram_positions", return_value=True
                ) as pos,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/posizioni", 24, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            pos.assert_called_once_with("/posizioni", spath)
            delete.assert_called_once_with(24)

    def test_ibkr_get_active_orders_filters_closed(self) -> None:
        payload = {
            "orders": [
                {"ticker": "AMD", "status": "Submitted", "orderId": 1},
                {"ticker": "NVDA", "status": "Filled", "orderId": 2},
                {"ticker": "BE", "status": "cancelled", "orderId": 3},
                {"ticker": "HOOD", "status": "PreSubmitted", "orderId": 4},
                {
                    "ticker": "SLNH",
                    "status": "Inactive",
                    "orderId": 5,
                    "orderType": "TRAILING_STOP",
                },
                {"ticker": "CRCL", "status": "PendingSubmit", "orderId": 6},
                {"ticker": "TSLA", "status": "PendingCancel", "orderId": 7},
                {
                    "ticker": "GHOST",
                    "status": "PendingSubmit",
                    "price": 2.0,
                    "orderId": 0,
                },
            ]
        }
        with (
            patch.object(watch, "ibkr_get", return_value=payload) as get,
            patch.object(watch.time, "sleep") as sleep,
        ):
            active = watch.ibkr_get_active_orders()
        self.assertEqual(
            [o["ticker"] for o in active], ["AMD", "HOOD", "CRCL"]
        )
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)
        get.assert_called_with("/v1/api/iserver/account/orders")
        with (
            patch.object(watch, "ibkr_get", return_value=None),
            patch.object(watch.time, "sleep"),
        ):
            self.assertIsNone(watch.ibkr_get_active_orders())

    def test_ibkr_get_active_orders_uses_second_snapshot(self) -> None:
        stale = {
            "orders": [
                {"ticker": "AMD", "status": "Submitted", "orderId": 1},
            ]
        }
        fresh = {
            "orders": [
                {"ticker": "AMD", "status": "Filled", "orderId": 1},
            ]
        }
        with (
            patch.object(watch, "ibkr_get", side_effect=[stale, fresh]) as get,
            patch.object(watch.time, "sleep") as sleep,
        ):
            active = watch.ibkr_get_active_orders()
        self.assertEqual(active, [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

        with (
            patch.object(watch, "ibkr_get", side_effect=[stale, fresh]),
            patch.object(watch.time, "sleep"),
            patch.object(watch, "ibkr_delete") as delete,
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Nessun ordine aperto trovato per AMD.",
            )
        delete.assert_not_called()

        with (
            patch.object(watch, "ibkr_get", side_effect=[stale, fresh]),
            patch.object(watch.time, "sleep"),
            patch.object(watch, "ibkr_post") as post,
        ):
            self.assertEqual(
                watch.ibkr_modify_order("AMD", 148.5),
                "⚠️ Nessun ordine aperto trovato per AMD.",
            )
        post.assert_not_called()

    def test_apply_telegram_orders_replaces_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"orders_message_id": 11})
            orders = [
                {
                    "ticker": "AMD",
                    "side": "BUY",
                    "remainingQuantity": 2,
                    "price": 100.5,
                    "status": "Submitted",
                }
            ]
            with (
                patch.object(watch, "ibkr_get_active_orders", return_value=orders),
                patch.object(watch, "send_telegram", return_value=22) as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                self.assertTrue(watch.apply_telegram_orders("/ordini", spath))
                self.assertFalse(watch.apply_telegram_orders("/posizioni", spath))
            delete.assert_called_once_with(11)
            body = send.call_args[0][0]
            self.assertIn("📋 Ordini attivi:", body)
            self.assertIn("AMD BUY 2 @ 100.5 · Submitted", body)
            self.assertEqual(watch.load_state(spath)["orders_message_id"], 22)
            self.assertEqual(
                watch.load_state(spath)["order_messages"][0]["message_id"], 22
            )
            self.assertEqual(
                watch.load_state(spath)["order_messages"][0]["ttl_seconds"], 60
            )
            with (
                patch.object(watch, "ibkr_get_active_orders", return_value=[]),
                patch.object(watch, "send_telegram", return_value=23) as send,
            ):
                self.assertTrue(watch.apply_telegram_orders("/ORDINI", spath))
            self.assertEqual(sent_text(send), "📭 Nessun ordine attivo.")
            state = watch.load_state(spath)
            self.assertEqual(state["orders_message_id"], 23)
            self.assertEqual(
                [m["message_id"] for m in state["order_messages"]], [23]
            )

    def test_fmt_order_line_shows_trail_not_mkt(self) -> None:
        self.assertEqual(
            watch._fmt_order_line(
                {
                    "ticker": "SLNH",
                    "side": "SELL",
                    "remainingQuantity": 1.0,
                    "orderType": "TRAILING_STOP",
                    "trailingAmt": 0.05,
                    "status": "Submitted",
                }
            ),
            "SLNH SELL 1.0 @ TRAIL 0.05 · Submitted",
        )

    def test_process_single_message_runs_ordini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_orders", return_value=True) as orders,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/ordini", 26, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            orders.assert_called_once_with("/ordini", spath)
            delete.assert_called_once_with(26)

    def test_ibkr_get_trades_parses_shapes(self) -> None:
        with patch.object(watch, "ibkr_get", return_value=None):
            self.assertIsNone(watch.ibkr_get_trades())
        rows = [{"symbol": "AMD", "side": "BUY"}]
        with patch.object(watch, "ibkr_get", return_value=rows):
            self.assertEqual(watch.ibkr_get_trades(), rows)
        with patch.object(watch, "ibkr_get", return_value={"trades": rows}):
            self.assertEqual(watch.ibkr_get_trades(), rows)
        with patch.object(watch, "ibkr_get", return_value={"trades": []}):
            self.assertEqual(watch.ibkr_get_trades(), [])
        single = {"ticker": "NVDA", "side": "SELL", "price": 120}
        with patch.object(watch, "ibkr_get", return_value=single):
            self.assertEqual(watch.ibkr_get_trades(), [single])
        with patch.object(watch, "ibkr_get", return_value={"status": "ok"}):
            self.assertIsNone(watch.ibkr_get_trades())

    def test_trade_timestamp_ms_and_string(self) -> None:
        ms = 1_725_000_000_000
        self.assertEqual(watch._trade_timestamp({"trade_time_r": ms}), ms / 1000)
        secs = 1_725_000_000
        self.assertEqual(watch._trade_timestamp({"trade_time_r": secs}), float(secs))
        ts = watch._trade_timestamp({"trade_time": "20240901-15:30:00"})
        self.assertGreater(ts, 0)
        self.assertEqual(watch._trade_timestamp({}), 0.0)
        self.assertEqual(watch._trade_timestamp({"trade_time_r": "nope"}), 0.0)
        self.assertEqual(watch._trade_timestamp({"trade_time": "not-a-date"}), 0.0)

    def test_apply_telegram_history_filters_and_sums_fees(self) -> None:
        now = 1_800_000_000.0
        older_ms = (now - 7200) * 1000
        recent_ms = (now - 3600) * 1000
        old_ms = (now - 10 * 86400) * 1000
        trades = [
            {
                "side": "SELL",
                "quantity": 1,
                "ticker": "NVDA",
                "price": 120,
                "commission": "n/d",
                "trade_time_r": recent_ms,
            },
            {
                "side": "BUY",
                "size": 2,
                "symbol": "AMD",
                "price": 148.2,
                "commission": 1.05,
                "trade_time_r": older_ms,
            },
            {
                "side": "BUY",
                "size": 5,
                "symbol": "HOOD",
                "price": 20,
                "commission": 0.5,
                "trade_time_r": old_ms,
            },
            {
                "side": "BUY",
                "symbol": "NO_TS",
                "price": 1,
                "commission": 9,
            },
            {
                "side": "BUY",
                "symbol": "EUR",
                "size": 200,
                "price": 1.17,
                "commission": 0.0,
                "trade_time_r": recent_ms,
            },
            {
                "side": "SELL",
                "ticker": "USD",
                "secType": "CASH",
                "size": 234,
                "price": 0.85,
                "commission": 0.0,
                "trade_time_r": older_ms,
            },
        ]
        with (
            patch.object(watch, "ibkr_get_trades", return_value=trades),
            patch.object(watch, "send_telegram") as send,
            patch.object(watch.time, "time", return_value=now),
        ):
            self.assertTrue(watch.apply_telegram_history("/storico 7"))
            self.assertFalse(watch.apply_telegram_history("/ordini"))
        body = send.call_args[0][0]
        self.assertIn("📜 Ordini eseguiti (ultimi 7 giorni):", body)
        self.assertIn("BUY 2 AMD @ 148.2 · fee: 1.05", body)
        self.assertIn("SELL 1 NVDA @ 120 · fee: n/d", body)
        self.assertLess(body.index("AMD"), body.index("NVDA"))
        self.assertNotIn("HOOD", body)
        self.assertNotIn("NO_TS", body)
        self.assertNotIn("EUR", body)
        self.assertNotIn("CASH", body)
        self.assertNotIn("USD", body)
        self.assertNotIn("PNL", body)
        self.assertIn("Totale fee: 1.05", body)
        self.assertNotIn("Totale PNL", body)

    def test_apply_telegram_history_sell_pnl_uses_average_cost(self) -> None:
        now = 1_800_000_000.0
        old_buy = (now - 10 * 86400) * 1000
        buy_ms = (now - 3600) * 1000
        sell_ms = (now - 1800) * 1000
        later_ms = (now - 600) * 1000
        trades = [
            {
                "side": "B",
                "symbol": "AMD",
                "size": "2",
                "price": "100",
                "commission": "1.00",
                "trade_time_r": old_buy,
            },
            {
                "side": "BUY",
                "symbol": "AMD",
                "size": 2,
                "price": 120,
                "commission": 1.0,
                "trade_time_r": buy_ms,
            },
            {
                "side": "S",
                "symbol": "AMD",
                "size": 1,
                "price": 150,
                "commission": 0.5,
                "trade_time_r": sell_ms,
                "execution_id": "ex-1",
            },
            {
                "side": "SELL",
                "ticker": "NVDA",
                "quantity": 1,
                "price": 200,
                "commission": "n/d",
                "trade_time_r": later_ms,
            },
        ]
        with (
            patch.object(watch, "ibkr_get_trades", return_value=trades),
            patch.object(watch, "send_telegram") as send,
            patch.object(watch.time, "time", return_value=now),
        ):
            self.assertTrue(watch.apply_telegram_history("/storico 7"))
        body = send.call_args[0][0]
        self.assertIn("BUY 2 AMD @ 120 · fee: 1.0", body)
        self.assertIn("S 1 AMD @ 150 · fee: 0.5 · PNL: +39.00", body)
        self.assertIn("SELL 1 NVDA @ 200 · fee: n/d", body)
        self.assertNotIn("B 2 AMD @ 100", body)
        self.assertLess(body.index("BUY 2 AMD"), body.index("S 1 AMD"))
        self.assertIn("Totale fee: 1.50", body)
        self.assertIn("Totale PNL: +39.00", body)

    def test_apply_telegram_history_skips_only_eur_fx(self) -> None:
        now = 1_800_000_000.0
        trades = [
            {
                "side": "BUY",
                "symbol": "EUR",
                "secType": "CASH",
                "size": 100,
                "price": 1.1,
                "commission": 0.0,
                "trade_time_r": (now - 60) * 1000,
            }
        ]
        with (
            patch.object(watch, "ibkr_get_trades", return_value=trades),
            patch.object(watch, "send_telegram") as send,
            patch.object(watch.time, "time", return_value=now),
        ):
            self.assertTrue(watch.apply_telegram_history("/storico 1"))
        self.assertEqual(sent_text(send), "📭 Nessun ordine eseguito negli ultimi 1 giorni.")

    def test_apply_telegram_history_empty_and_unavailable(self) -> None:
        with (
            patch.object(watch, "ibkr_get_trades", return_value=None),
            patch.object(watch, "send_telegram") as send,
        ):
            self.assertTrue(watch.apply_telegram_history("/storico 3"))
        self.assertEqual(sent_text(send), "⚠️ Impossibile leggere lo storico ordini al momento.")
        with (
            patch.object(watch, "ibkr_get_trades", return_value=[]),
            patch.object(watch, "send_telegram") as send,
        ):
            self.assertTrue(watch.apply_telegram_history("/STORICO 3"))
        self.assertEqual(sent_text(send), "📭 Nessun ordine eseguito negli ultimi 3 giorni.")

    def test_process_single_message_runs_storico(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_history", return_value=True) as hist,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/storico 7", 27, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            hist.assert_called_once_with("/storico 7", spath)
            delete.assert_called_once_with(27)

    def test_check_order_fills_notifies_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            payload = {
                "orders": [
                    {
                        "orderId": 77,
                        "status": "Filled",
                        "side": "BUY",
                        "filledQuantity": 2,
                        "ticker": "AMD",
                        "avgPrice": 148.2,
                        "conid": 4391,
                    }
                ]
            }
            trades = [{"order_id": "77", "commission": 1.05}]
            with (
                patch.object(
                    watch, "ibkr_get", side_effect=[payload, trades, payload, trades]
                ),
                patch.object(watch, "send_telegram", return_value=66) as send,
                patch.object(watch, "commit_state_to_git") as sync,
            ):
                watch.check_order_fills(spath)
                watch.check_order_fills(spath)
            self.assertEqual(sent_text(send), "✅ ESEGUITO: BUY 2 AMD @ 148.2 · fee: 1.05")
            sync.assert_called_once_with()
            state = watch.load_state(spath)
            self.assertEqual(state["known_order_status"]["77"], "Filled")
            self.assertEqual(state["order_messages"][0]["message_id"], 66)

    def test_check_order_fills_commits_each_new_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            payload = {
                "orders": [
                    {
                        "orderId": 10,
                        "status": "Filled",
                        "side": "BUY",
                        "filledQuantity": 1,
                        "ticker": "AMD",
                        "avgPrice": 100,
                    },
                    {
                        "orderId": 11,
                        "status": "Submitted",
                        "side": "SELL",
                        "filledQuantity": 0,
                        "ticker": "TSLA",
                    },
                    {
                        "orderId": 12,
                        "status": "Filled",
                        "side": "SELL",
                        "filledQuantity": 2,
                        "ticker": "NVDA",
                        "avgPrice": 120,
                    },
                ]
            }
            with (
                patch.object(watch, "ibkr_get", return_value=payload),
                patch.object(watch, "_commission_from_trades", return_value="n/d"),
                patch.object(watch, "send_telegram", return_value=1),
                patch.object(watch, "commit_state_to_git") as sync,
            ):
                watch.check_order_fills(spath)
            self.assertEqual(sync.call_count, 2)
            state = watch.load_state(spath)
            self.assertEqual(state["known_order_status"]["10"], "Filled")
            self.assertEqual(state["known_order_status"]["11"], "Submitted")
            self.assertEqual(state["known_order_status"]["12"], "Filled")
            with (
                patch.object(watch, "ibkr_get", return_value=payload),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "commit_state_to_git") as sync,
            ):
                watch.check_order_fills(spath)
            send.assert_not_called()
            sync.assert_not_called()

    def test_ibkr_ws_url_and_orders_from_message(self) -> None:
        self.assertEqual(
            watch.ibkr_ws_url(), "wss://danny-ibeam:5000/v1/api/ws"
        )
        with patch.object(watch, "IBKR_BASE_URL", "http://localhost:5001"):
            self.assertEqual(watch.ibkr_ws_url(), "ws://localhost:5001/v1/api/ws")
        filled = {
            "orderId": 77,
            "status": "Filled",
            "side": "BUY",
            "filledQuantity": 2,
            "ticker": "AMD",
            "avgPrice": 148.2,
        }
        self.assertEqual(
            watch.orders_from_ws_message(
                json.dumps({"topic": "sor", "args": [filled]})
            ),
            [filled],
        )
        self.assertEqual(
            watch.orders_from_ws_message({"topic": "sor", "args": filled}),
            [filled],
        )
        self.assertEqual(watch.orders_from_ws_message({"topic": "sts"}), [])
        self.assertEqual(watch.orders_from_ws_message("tic"), [])

    def test_handle_ibkr_ws_message_notifies_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            payload = {
                "topic": "sor",
                "args": [
                    {
                        "orderId": 88,
                        "status": "Filled",
                        "side": "SELL",
                        "filledQuantity": 1,
                        "ticker": "NVDA",
                        "avgPrice": 120,
                    }
                ],
            }
            with (
                patch.object(watch, "_commission_from_trades", return_value="n/d"),
                patch.object(watch, "send_telegram", return_value=9) as send,
                patch.object(watch, "commit_state_to_git") as sync,
            ):
                watch.handle_ibkr_ws_message(json.dumps(payload), spath)
                watch.handle_ibkr_ws_message(json.dumps(payload), spath)
            self.assertEqual(
                sent_text(send), "✅ ESEGUITO: SELL 1 NVDA @ 120 · fee: n/d"
            )
            sync.assert_called_once_with()
            self.assertEqual(watch.load_state(spath)["known_order_status"]["88"], "Filled")

    def test_ws_then_poll_same_fill_notifies_once(self) -> None:
        filled = {
            "orderId": 42,
            "status": "Filled",
            "side": "BUY",
            "filledQuantity": 3,
            "ticker": "AMD",
            "avgPrice": 150,
        }
        rest = {"orders": [filled]}
        ws = json.dumps({"topic": "sor", "args": [filled]})
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get", side_effect=[rest, []]),
                patch.object(watch, "_commission_from_trades", return_value="0.5"),
                patch.object(watch, "send_telegram", return_value=7) as send,
                patch.object(watch, "commit_state_to_git"),
            ):
                watch.handle_ibkr_ws_message(ws, spath)
                watch.check_order_fills(spath)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(
                sent_text(send), "✅ ESEGUITO: BUY 3 AMD @ 150 · fee: 0.5"
            )

    def test_poll_then_ws_same_fill_notifies_once(self) -> None:
        filled = {
            "orderId": 43,
            "status": "Filled",
            "side": "SELL",
            "filledQuantity": 1,
            "ticker": "NVDA",
            "avgPrice": 120,
        }
        rest = {"orders": [filled]}
        ws = json.dumps({"topic": "sor", "args": [filled]})
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get", side_effect=[rest, []]),
                patch.object(watch, "_commission_from_trades", return_value="n/d"),
                patch.object(watch, "send_telegram", return_value=8) as send,
                patch.object(watch, "commit_state_to_git"),
            ):
                watch.check_order_fills(spath)
                watch.handle_ibkr_ws_message(ws, spath)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(
                sent_text(send), "✅ ESEGUITO: SELL 1 NVDA @ 120 · fee: n/d"
            )

    def test_run_ibkr_order_socket_subscribes_and_handles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            stop = threading.Event()
            sent: list[str] = []

            class FakeSock:
                def send(self, msg: str) -> None:
                    sent.append(msg)

                def recv(self) -> str:
                    stop.set()
                    return json.dumps(
                        {
                            "topic": "sor",
                            "args": [
                                {
                                    "orderId": 5,
                                    "status": "Submitted",
                                    "ticker": "AMD",
                                }
                            ],
                        }
                    )

                def close(self) -> None:
                    return None

            with (
                patch.object(watch, "ibkr_tickle", return_value=True) as tickle,
                patch.object(watch, "ibkr_get", return_value={"orders": []}),
            ):
                watch.run_ibkr_order_socket(
                    spath, opener=FakeSock, stop=stop, pause=0
                )
            self.assertEqual(sent[0], "sor+{}")
            tickle.assert_called()
            self.assertEqual(
                watch.load_state(spath)["known_order_status"]["5"], "Submitted"
            )

    def test_ibkr_get_fyi_notifications_shapes(self) -> None:
        with patch.object(watch, "ibkr_get", return_value=None):
            self.assertIsNone(watch.ibkr_get_fyi_notifications())
        rows = [{"id": "1", "text": "hello"}]
        with patch.object(watch, "ibkr_get", return_value=rows):
            self.assertEqual(watch.ibkr_get_fyi_notifications(), rows)
        with patch.object(
            watch, "ibkr_get", return_value={"notifications": rows}
        ):
            self.assertEqual(watch.ibkr_get_fyi_notifications(), rows)
        single = {"ID": "9", "MS": "margin"}
        with patch.object(watch, "ibkr_get", return_value=single):
            self.assertEqual(watch.ibkr_get_fyi_notifications(), [single])
        with patch.object(watch, "ibkr_get", return_value={"ok": True}):
            self.assertIsNone(watch.ibkr_get_fyi_notifications())

    def test_check_fyi_notifications_sends_new_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            notes = [
                {
                    "ID": "a1",
                    "MS": "Deposito ricevuto",
                    "MD": "<div>Soldi arrivati<br /><a href=\"sso://x\">Dettagli</a></div>",
                },
                {
                    "ID": "fx1",
                    "MS": "Currency Conversion Notification",
                    "MD": "<div>EUR to USD</div>",
                },
                {
                    "MS": "Avviso margine",
                    "MD": "Controlla il conto",
                },
                "skip-me",
            ]
            with (
                patch.object(watch, "ibkr_get_fyi_notifications", return_value=notes),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.check_fyi_notifications(spath)
                watch.check_fyi_notifications(spath)
            self.assertEqual(
                [c.args[0] for c in send.call_args_list],
                [
                    "📢 Deposito ricevuto\n\nSoldi arrivati\nDettagli",
                    "📢 Avviso margine\n\nControlla il conto",
                ],
            )
            ids = set(watch.load_state(spath)["known_fyi_ids"])
            self.assertIn("a1", ids)
            self.assertIn("fx1", ids)
            hashed = watch._fyi_notification_id(
                {"MS": "Avviso margine", "MD": "Controlla il conto"}
            )
            self.assertIn(hashed, ids)
            self.assertTrue(hashed.startswith("h:"))

    def test_check_fyi_skips_currency_conversion_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            notes = [
                {
                    "ID": "fx2",
                    "MS": "CURRENCY CONVERSION notice",
                    "MD": "ignore me",
                }
            ]
            with (
                patch.object(watch, "ibkr_get_fyi_notifications", return_value=notes),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.check_fyi_notifications(spath)
            send.assert_not_called()
            self.assertEqual(watch.load_state(spath)["known_fyi_ids"], ["fx2"])

    def test_check_fyi_notifications_skips_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get_fyi_notifications", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.check_fyi_notifications(spath)
            send.assert_not_called()
            self.assertNotIn("known_fyi_ids", watch.load_state(spath))
            with (
                patch.object(watch, "ibkr_get_fyi_notifications", return_value=[]),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.check_fyi_notifications(spath)
            send.assert_not_called()

    def test_ibkr_sell_all_uses_limit_under_spot(self) -> None:
        with (
            patch.object(
                watch,
                "ibkr_get_positions",
                return_value=[{"ticker": "amd", "position": 10.8}],
            ),
            patch.object(watch, "ibkr_get_price", return_value=100.0),
            patch.object(watch, "ibkr_place_order", return_value="✅ ok") as place,
        ):
            self.assertEqual(watch.ibkr_sell_all("AMD", None), "✅ ok")
        place.assert_called_once_with("AMD", 10, "SELL", 99.5)
        with (
            patch.object(
                watch,
                "ibkr_get_positions",
                return_value=[{"ticker": "AMD", "position": 3}],
            ),
            patch.object(watch, "ibkr_place_order", return_value="✅ ok") as place,
        ):
            watch.ibkr_sell_all("AMD", 22.5)
        place.assert_called_once_with("AMD", 3, "SELL", 22.5)
        with patch.object(watch, "ibkr_get_positions", return_value=[]):
            self.assertEqual(
                watch.ibkr_sell_all("NVDA", None),
                "⚠️ Nessuna posizione aperta per NVDA.",
            )

    def test_venditutto_command_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_sell_all") as sell_all,
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/venditutto AMD", 25, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            sell_all.assert_not_called()
            send.assert_not_called()
            delete.assert_called_once_with(25)
            self.assertFalse(hasattr(watch, "apply_telegram_sell_all"))

    def test_expire_order_messages_deletes_only_old(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            now = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
            watch.save_state(
                spath,
                {
                    "sent_alerts": [{"message_id": 9, "sent_at": now.isoformat()}],
                    "order_messages": [
                        {
                            "message_id": 1,
                            "sent_at": (now - timedelta(seconds=61)).isoformat(),
                        },
                        {
                            "message_id": 2,
                            "sent_at": (now - timedelta(seconds=10)).isoformat(),
                        },
                    ],
                },
            )
            with patch.object(watch, "delete_telegram_message") as delete:
                watch.expire_order_messages(spath, now=now)
            delete.assert_called_once_with(1)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(len(state["order_messages"]), 1)
            self.assertEqual(state["order_messages"][0]["message_id"], 2)
            self.assertEqual(state["sent_alerts"][0]["message_id"], 9)

    def test_expire_order_messages_clears_orders_digest_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            now = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
            watch.save_state(
                spath,
                {
                    "orders_message_id": 1,
                    "order_messages": [
                        {
                            "message_id": 1,
                            "sent_at": (now - timedelta(seconds=61)).isoformat(),
                            "ttl_seconds": 60,
                        }
                    ],
                },
            )
            with patch.object(watch, "delete_telegram_message") as delete:
                watch.expire_order_messages(spath, now=now)
            delete.assert_not_called()
            self.assertEqual(watch.load_state(spath)["orders_message_id"], 1)

    def test_expire_flow_messages_uses_120s_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            now = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
            watch.save_state(
                spath,
                {
                    "order_messages": [
                        {
                            "message_id": 1,
                            "sent_at": (now - timedelta(seconds=90)).isoformat(),
                            "ttl_seconds": 120,
                        },
                        {
                            "message_id": 2,
                            "sent_at": (now - timedelta(seconds=121)).isoformat(),
                            "ttl_seconds": 120,
                        },
                        {
                            "message_id": 3,
                            "sent_at": (now - timedelta(seconds=61)).isoformat(),
                        },
                    ]
                },
            )
            with patch.object(watch, "delete_telegram_message") as delete:
                watch.expire_order_messages(spath, now=now)
            self.assertEqual(
                [c.args[0] for c in delete.call_args_list], [2, 3]
            )
            kept = [m["message_id"] for m in watch.load_state(spath)["order_messages"]]
            self.assertEqual(kept, [1])

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
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "daily",
                        "ingresso_low": 130,
                        "ingresso_high": 134,
                        "stop": 124,
                        "target": 148,
                        "motivo": "⚠️",
                    }
                ],
            )
            watch.save_state(spath, {"summary_message_id": 11})
            with (
                patch.object(watch, "delete_telegram_message") as delete,
                patch.object(watch, "send_telegram", return_value=22) as send,
            ):
                self.assertTrue(watch.apply_telegram_list("/list", wpath, spath))
                self.assertTrue(watch.apply_telegram_list("/WATCHLIST", wpath, spath))
                self.assertFalse(watch.apply_telegram_list("/rm AMD", wpath, spath))
            self.assertEqual(send.call_count, 2)
            self.assertEqual(delete.call_count, 2)
            body = send.call_args_list[0][0][0]
            self.assertEqual(body, "AMD i 130-134 s 124 t 148 ⚠️")
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 22)
            watch.save_watchlist(wpath, [])
            with patch.object(watch, "send_telegram", return_value=33) as send:
                watch.apply_telegram_list("/list", wpath, spath)
            self.assertEqual(sent_text(send), "Watchlist vuota.")

    def test_refresh_watchlist_summary_replaces_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "daily",
                        "ingresso_low": 130,
                        "ingresso_high": 134,
                        "stop": 124,
                        "target": 148,
                        "motivo": "✅",
                    }
                ],
            )
            watch.save_state(spath, {"summary_message_id": 11, "telegram_offset": 4})
            with (
                patch.object(watch, "delete_telegram_message") as delete,
                patch.object(watch, "send_telegram", return_value=22) as send,
            ):
                watch.refresh_watchlist_summary(wpath, spath)
            delete.assert_called_once_with(11)
            body = send.call_args[0][0]
            self.assertIn("AMD", body)
            self.assertIn("i 130-134", body)
            self.assertIn("s 124", body)
            self.assertIn("t 148", body)
            self.assertTrue(body.rstrip().endswith("✅"))
            self.assertNotIn(" ing ", body)
            self.assertNotIn("stop ", body)
            self.assertNotIn("tgt ", body)
            self.assertNotIn("Screener automatico", body)
            self.assertNotIn("ATR", body)
            self.assertNotIn("RSI", body)
            self.assertNotIn("📊 Screener tecnico", body)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["summary_message_id"], 22)
            self.assertEqual(state["telegram_offset"], 4)

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
            self.assertEqual(
                item["locked_fields"],
                ["ingresso_low", "ingresso_high", "stop", "target"],
            )
            self.assertEqual(watch.apply_telegram_set("/set $hood 75 70 103", wpath), "HOOD")
            hood = next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "HOOD")
            self.assertEqual(hood["ingresso_low"], 75.0)
            self.assertEqual(hood["ingresso_high"], 75.0)
            self.assertEqual(hood["tf"], "")
            self.assertEqual(
                hood["locked_fields"],
                ["ingresso_low", "ingresso_high", "stop", "target"],
            )
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
            self.assertEqual(amd["locked_fields"], ["ingresso_low", "ingresso_high"])
            self.assertEqual(watch.apply_telegram_set_field("/settarget $amd 160", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["target"], 160.0)
            self.assertEqual(amd["ingresso_low"], 132.5)
            self.assertEqual(amd["locked_fields"], ["ingresso_low", "ingresso_high", "target"])
            self.assertEqual(watch.apply_telegram_set_field("/SETSTOP AMD 120", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["stop"], 120.0)
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(
                amd["locked_fields"],
                ["ingresso_low", "ingresso_high", "target", "stop"],
            )
            self.assertEqual(watch.apply_telegram_set_field("/setbuy AMD 132.5", wpath), "AMD")
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(
                amd["locked_fields"],
                ["ingresso_low", "ingresso_high", "target", "stop"],
            )
            self.assertEqual(watch.apply_telegram_set_field("/setbuy HOOD 75", wpath), "HOOD")
            hood = next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "HOOD")
            self.assertEqual(hood["ingresso_low"], 75.0)
            self.assertEqual(hood["ingresso_high"], 75.0)
            self.assertEqual(hood["locked_fields"], ["ingresso_low", "ingresso_high"])
            self.assertIsNone(hood["stop"])
            self.assertIsNone(hood["target"])
            self.assertIsNone(watch.apply_telegram_set_field("/set AMD", wpath))
            self.assertIsNone(watch.apply_telegram_set_field("ciao", wpath))

    def test_set_multi_applies_each_valid_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            text = "/set\nAMD 500 480 550\nTSLA 350 330 380\n"
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertEqual(
                    watch.apply_telegram_set(text, wpath),
                    ["AMD", "TSLA"],
                )
            self.assertEqual(sent_text(send), "✅ Impostati: AMD, TSLA")
            items = {it["ticker"]: it for it in watch.load_watchlist(wpath)}
            self.assertEqual(items["AMD"]["ingresso_low"], 500.0)
            self.assertEqual(items["AMD"]["ingresso_high"], 500.0)
            self.assertEqual(items["AMD"]["stop"], 480.0)
            self.assertEqual(items["AMD"]["target"], 550.0)
            self.assertEqual(
                items["AMD"]["locked_fields"],
                ["ingresso_low", "ingresso_high", "stop", "target"],
            )
            self.assertEqual(items["TSLA"]["ingresso_low"], 350.0)
            self.assertEqual(items["TSLA"]["stop"], 330.0)
            self.assertEqual(items["TSLA"]["target"], 380.0)

    def test_set_multi_skips_bad_rows_and_keeps_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            text = "/set\nAMD 500 480 550\nNOT A TICKER\nTSLA 350 330 380\nBAD\n"
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertEqual(
                    watch.apply_telegram_set(text, wpath),
                    ["AMD", "TSLA"],
                )
            self.assertEqual(sent_text(send), "✅ Impostati: AMD, TSLA\n⚠️ Errori: NOT, BAD")
            tickers = [it["ticker"] for it in watch.load_watchlist(wpath)]
            self.assertEqual(tickers, ["AMD", "TSLA"])
            self.assertEqual(
                watch.apply_telegram_set("/set CRCL 75-90 70 103", wpath),
                "CRCL",
            )
            crcl = next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "CRCL")
            self.assertEqual(crcl["ingresso_low"], 75.0)
            self.assertEqual(crcl["ingresso_high"], 90.0)

    def test_setbuy_multi_and_other_fields_stay_single(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            text = "/setbuy\nAMD 500\nTSLA 350\nFOO\n"
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertEqual(
                    watch.apply_telegram_set_field(text, wpath),
                    ["AMD", "TSLA"],
                )
            self.assertEqual(sent_text(send), "✅ Impostati: AMD, TSLA\n⚠️ Errori: FOO")
            items = {it["ticker"]: it for it in watch.load_watchlist(wpath)}
            self.assertEqual(items["AMD"]["ingresso_low"], 500.0)
            self.assertEqual(items["AMD"]["ingresso_high"], 500.0)
            self.assertEqual(items["AMD"]["locked_fields"], ["ingresso_low", "ingresso_high"])
            self.assertEqual(items["TSLA"]["ingresso_low"], 350.0)
            with patch.object(watch, "send_telegram") as send:
                self.assertEqual(
                    watch.apply_telegram_set_field("/settarget\nAMD 160\nTSLA 400\n", wpath),
                    "AMD",
                )
                self.assertEqual(
                    watch.apply_telegram_set_field("/setstop\nAMD 120\nTSLA 300\n", wpath),
                    "AMD",
                )
                send.assert_not_called()
            amd = watch.load_watchlist(wpath)[0]
            self.assertEqual(amd["target"], 160.0)
            self.assertEqual(amd["stop"], 120.0)
            self.assertEqual(len(watch.load_watchlist(wpath)), 2)
            self.assertIsNone(
                next(it for it in watch.load_watchlist(wpath) if it["ticker"] == "TSLA").get("target")
            )
            self.assertEqual(
                watch.apply_telegram_set_field("/settarget AMD 160", wpath),
                "AMD",
            )
            self.assertEqual(watch.load_watchlist(wpath)[0]["target"], 160.0)

    def test_process_single_message_handles_set_multi_without_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            text = "/set\nAMD 500 480 550\nTSLA 350 330 380\n"
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "delete_telegram_message"),
            ):
                added, removed = watch.process_single_message(text, 9, wpath, spath)
            self.assertEqual(added, [])
            self.assertEqual(removed, [])
            self.assertEqual(sent_text(send), "✅ Impostati: AMD, TSLA")
            self.assertEqual(
                [it["ticker"] for it in watch.load_watchlist(wpath)],
                ["AMD", "TSLA"],
            )

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
                            "sent_at": (now - timedelta(hours=9)).isoformat(),
                        },
                        {
                            "message_id": 2,
                            "sent_at": (now - timedelta(hours=4)).isoformat(),
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
            fired: dict[tuple[str, str, str], str | None] = {}
            today = watch.alert_day()
            with patch.object(watch, "send_telegram", return_value=321):
                watch.maybe_alert(
                    item,
                    "ingresso",
                    "ALERT AMD ingresso 130.00 (130)",
                    True,
                    fired,
                    spath,
                )
            self.assertEqual(fired[("AMD", "daily", "ingresso")], today)
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["sent_alerts"][0]["message_id"], 321)
            self.assertIn("T", state["sent_alerts"][0]["sent_at"])

    def test_maybe_alert_once_per_calendar_day(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            item = {"ticker": "AMD", "tf": "daily"}
            fired: dict[tuple[str, str, str], str | None] = {}
            rome = ZoneInfo("Europe/Rome")
            day1 = datetime(2026, 9, 16, 16, 0, tzinfo=rome)
            day2 = datetime(2026, 9, 17, 16, 0, tzinfo=rome)
            with (
                patch.object(watch, "rome_now", return_value=day1),
                patch.object(watch, "send_telegram", return_value=1) as send,
            ):
                watch.maybe_alert(item, "stop", "ALERT AMD stop", True, fired, spath)
                watch.maybe_alert(item, "stop", "ALERT AMD stop", False, fired, spath)
                watch.maybe_alert(item, "stop", "ALERT AMD stop", True, fired, spath)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(fired[("AMD", "daily", "stop")], "2026-09-16")
            with (
                patch.object(watch, "rome_now", return_value=day2),
                patch.object(watch, "send_telegram", return_value=2) as send,
            ):
                watch.maybe_alert(item, "stop", "ALERT AMD stop", True, fired, spath)
            send.assert_called_once()
            self.assertEqual(fired[("AMD", "daily", "stop")], "2026-09-17")

    def test_maybe_alert_sends_new_message_not_the_bot_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "bot_message_id": 70,
                    "pending_flow": {"type": "BUY", "step": "ticker"},
                },
            )
            item = {"ticker": "AMD", "tf": "daily"}
            fired: dict[tuple[str, str, str], str | None] = {}
            with (
                patch.object(watch, "send_telegram", return_value=321) as send,
                patch.object(watch, "deliver_text") as deliver,
            ):
                watch.maybe_alert(
                    item, "ingresso", "ALERT AMD ingresso 130", True, fired, spath
                )
            send.assert_called_once_with("ALERT AMD ingresso 130")
            deliver.assert_not_called()
            self.assertEqual(watch.load_state(spath)["bot_message_id"], 70)

    def test_fired_roundtrip(self) -> None:
        fired = {
            ("AMD", "daily", "ingresso"): "2026-09-16",
            ("NVDA", "weekly", "stop"): None,
        }
        dumped = watch.dump_fired(fired)
        self.assertEqual(dumped, {"AMD|daily|ingresso": "2026-09-16"})
        loaded = watch.load_fired({"fired": dumped})
        self.assertEqual(loaded[("AMD", "daily", "ingresso")], "2026-09-16")
        self.assertNotIn(("NVDA", "weekly", "stop"), loaded)

    def test_load_fired_migrates_legacy_bool(self) -> None:
        with patch.object(watch, "alert_day", return_value="2026-09-16"):
            loaded = watch.load_fired(
                {"fired": {"AMD|daily|stop": True, "NVDA|weekly|target": False}}
            )
        self.assertEqual(loaded[("AMD", "daily", "stop")], "2026-09-16")
        self.assertNotIn(("NVDA", "weekly", "target"), loaded)

    def test_persist_fired_keeps_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"telegram_offset": 9})
            watch.persist_fired(spath, {("AMD", "daily", "target"): "2026-09-16"})
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["telegram_offset"], 9)
            self.assertEqual(state["fired"]["AMD|daily|target"], "2026-09-16")

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

    def test_cycle_fetches_without_holding_lock(self) -> None:
        item = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": 130.0,
            "ingresso_high": 134.0,
            "stop": 124.0,
            "target": 148.0,
            "motivo": "",
        }
        lock = threading.Lock()
        held_during_fetch: list[bool] = []
        held_during_send: list[bool] = []

        def fake_prices(tickers: list[str]) -> dict[str, float | None]:
            held_during_fetch.append(lock.locked())
            return {"AMD": 132.0}

        def fake_ranges(tickers: list[str]) -> dict[str, tuple[float, float] | None]:
            held_during_fetch.append(lock.locked())
            return {"AMD": None}

        def fake_send(
            text: str,
            chat_id_override: str | None = None,
            reply_markup: dict | None = None,
        ) -> int | None:
            held_during_send.append(lock.locked())
            return 1

        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            fired: dict[tuple[str, str, str], bool] = {}
            with (
                patch.object(watch, "fetch_prices", side_effect=fake_prices),
                patch.object(watch, "fetch_day_ranges", side_effect=fake_ranges),
                patch.object(watch, "send_telegram", side_effect=fake_send),
                patch.object(watch, "expire_sent_alerts"),
            ):
                watch.cycle([item], fired, spath, lock=lock)
        self.assertEqual(held_during_fetch, [False, False])
        self.assertTrue(held_during_send)
        self.assertTrue(all(held_during_send))

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


class BuySellFlowTests(unittest.TestCase):
    def _flow(self, **overrides: object) -> dict:
        data: dict = {
            "type": "BUY",
            "step": "ticker",
            "ticker": None,
            "size_type": None,
            "quantity": None,
            "price_type": None,
        }
        data.update(overrides)
        return data

    def test_flow_start_regex_only_without_args(self) -> None:
        self.assertTrue(watch.BUY_FLOW_START_RE.match("/compra"))
        self.assertTrue(watch.BUY_FLOW_START_RE.match("/COMPRA"))
        self.assertFalse(watch.BUY_FLOW_START_RE.match("/compra AMD 1"))
        self.assertTrue(watch.SELL_FLOW_START_RE.match("/vendi"))
        self.assertFalse(watch.SELL_FLOW_START_RE.match("/vendi AMD 1"))
        self.assertIsNone(watch.BUY_RE.match("/compra"))
        self.assertIsNone(watch.SELL_RE.match("/vendi"))

    def test_apply_telegram_buy_flow_start_sets_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.apply_telegram_buy_flow_start("/compra", spath))
                self.assertFalse(
                    watch.apply_telegram_buy_flow_start("/compra AMD 1", spath)
                )
            self.assertEqual(send.call_args[0][0], "Quale ticker vuoi comprare?")
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["type"], "BUY")
            self.assertEqual(flow["step"], "ticker")
            self.assertIsNone(flow["ticker"])

    def test_apply_telegram_sell_flow_start_sets_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": self._flow()})
            positions = [
                {"ticker": "amd", "position": 10},
                {"ticker": "CASH", "position": 0},
                {"ticker": "TSLA", "position": -2},
                {"ticker": "AMD", "position": 3},
                {"position": 5},
            ]
            with (
                patch.object(watch, "ibkr_get_positions", return_value=positions),
                patch.object(watch, "send_telegram_buttons") as buttons,
            ):
                self.assertTrue(watch.apply_telegram_sell_flow_start("/vendi", spath))
                self.assertFalse(
                    watch.apply_telegram_sell_flow_start("/vendi AMD 1", spath)
                )
            buttons.assert_called_once_with(
                "Quale ticker vuoi vendere?",
                [
                    ("AMD", "sellticker:AMD"),
                    ("TSLA", "sellticker:TSLA"),
                    *watch.MENU_NAV_BUTTONS,
                ],
            )
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["type"], "SELL")
            self.assertEqual(flow["step"], "size_type")
            self.assertIsNone(flow["ticker"])

    def test_apply_telegram_sell_flow_start_empty_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": self._flow()})
            with (
                patch.object(watch, "ibkr_get_positions", return_value=[]),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_sell_flow_start("/vendi", spath))
            self.assertEqual(
                send.call_args[0][0], "📭 Nessuna posizione aperta da vendere."
            )
            self.assertIsNone(watch.load_state(spath)["pending_flow"])
            with (
                patch.object(watch, "ibkr_get_positions", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_sell_flow_start("/VENDI", spath))
            self.assertEqual(
                send.call_args[0][0], "📭 Nessuna posizione aperta da vendere."
            )
            self.assertIsNone(watch.load_state(spath)["pending_flow"])

    def test_process_pending_flow_text_ticker_and_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": self._flow()})
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram_buttons") as buttons,
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.process_pending_flow_text("$amd", spath))
            buttons.assert_called_once_with(
                "Azioni o Dollari?",
                with_nav([("Azioni", "size:shares"), ("Dollari", "size:dollars")]),
            )
            send.assert_not_called()
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["ticker"], "AMD")
            self.assertEqual(flow["step"], "size_type")
            watch.save_state(spath, {"pending_flow": self._flow()})
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.process_pending_flow_text("too-long-name", spath))
            self.assertEqual(sent_text(send), "⚠️ Ticker non valido, riprova.")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "ticker")

    def test_sell_flow_text_ticker_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath, {"pending_flow": self._flow(type="SELL", step="ticker")}
            )
            with (
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "send_telegram_buttons") as buttons,
            ):
                self.assertFalse(watch.process_pending_flow_text("AMD", spath))
            send.assert_not_called()
            buttons.assert_not_called()
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["step"], "ticker")
            self.assertIsNone(flow["ticker"])
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": self._flow()})
            with (
                patch.object(watch, "is_valid_symbol", return_value=False),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.process_pending_flow_text("BTC", spath))
            self.assertEqual(sent_text(send), "⚠️ Ticker non valido, riprova.")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "ticker")

    def test_process_pending_flow_text_quantity_and_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="quantity", ticker="AMD", size_type="shares"
                    )
                },
            )
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.process_pending_flow_text("nope", spath))
            self.assertEqual(sent_text(send), "⚠️ Numero non valido, riprova.")
            self.assertEqual(
                watch.load_state(spath)["pending_flow"]["step"], "quantity"
            )
            with patch.object(watch, "send_telegram_buttons") as buttons:
                self.assertTrue(watch.process_pending_flow_text("2", spath))
            buttons.assert_called_once_with(
                "A mercato o a limite?",
                with_nav([("A mercato", "price:market"), ("A limite", "price:limit")]),
            )
            self.assertEqual(watch.load_state(spath)["pending_flow"]["quantity"], 2.0)
            self.assertEqual(
                watch.load_state(spath)["pending_flow"]["step"], "price_type"
            )
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="price",
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                        price_type="limit",
                    )
                },
            )
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.process_pending_flow_text("0", spath))
            self.assertEqual(sent_text(send), "⚠️ Prezzo non valido, riprova.")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "price")
            with patch.object(
                watch, "_execute_flow_order", return_value="✅ ok"
            ) as exe:
                self.assertTrue(watch.process_pending_flow_text("148.2", spath))
            exe.assert_called_once()
            self.assertEqual(exe.call_args[0][0]["price"], 148.2)
            self.assertIsNone(watch.load_state(spath)["pending_flow"])

    def test_process_pending_flow_text_ignores_button_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath, {"pending_flow": self._flow(step="size_type", ticker="AMD")}
            )
            self.assertFalse(watch.process_pending_flow_text("AMD", spath))
            watch.save_state(
                spath, {"pending_flow": self._flow(step="price_type", ticker="AMD")}
            )
            self.assertFalse(watch.process_pending_flow_text("10", spath))
            self.assertFalse(watch.process_pending_flow_text("AMD", Path(tmp) / "empty.json"))

    def test_process_callback_query_size_and_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath, {"pending_flow": self._flow(step="size_type", ticker="AMD")}
            )
            with (
                patch.object(watch, "answer_callback_query") as ack,
                patch.object(watch, "send_telegram") as send,
            ):
                watch.process_callback_query("size:shares", 1, "cb1", spath)
            ack.assert_called_once_with("cb1")
            self.assertEqual(sent_text(send), "Quante azioni?")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["size_type"], "shares")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "quantity")
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="size_type", ticker="NVDA", type="SELL"
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.process_callback_query("size:dollars", 1, "cb2", spath)
            self.assertEqual(sent_text(send), "Quanti dollari?")
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="price_type",
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(
                    watch, "_execute_flow_order", return_value="✅ ok"
                ) as exe,
                patch.object(watch, "send_telegram") as send,
            ):
                action = watch.process_callback_query(
                    "price:market", 1, "cb3", spath
                )
            exe.assert_not_called()
            send.assert_not_called()
            self.assertEqual(action["action"], "execute_order")
            self.assertEqual(action["flow"]["price_type"], "market")
            self.assertEqual(action["flow"]["ticker"], "AMD")
            self.assertEqual(action["flow"]["quantity"], 2.0)
            self.assertIsNone(watch.load_state(spath)["pending_flow"])
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="price_type",
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.process_callback_query("price:limit", 1, "cb4", spath)
            self.assertEqual(sent_text(send), "A che prezzo?")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "price")
            self.assertEqual(
                watch.load_state(spath)["pending_flow"]["price_type"], "limit"
            )

    def test_process_callback_query_sellticker_shows_size_buttons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        type="SELL", step="size_type", ticker=None
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query") as ack,
                patch.object(watch, "send_telegram_buttons") as buttons,
            ):
                action = watch.process_callback_query(
                    "sellticker:amd", 1, "cb6", spath
                )
            ack.assert_called_once_with("cb6")
            self.assertIsNone(action)
            buttons.assert_called_once_with(
                "Azioni o Dollari?",
                with_nav(
                    [
                        ("Azioni", "size:shares"),
                        ("Dollari", "size:dollars"),
                        ("Vendi tutto", "size:all"),
                    ]
                ),
            )
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["ticker"], "AMD")
            self.assertEqual(flow["step"], "size_type")
            self.assertEqual(flow["type"], "SELL")
            watch.save_state(spath, {"pending_flow": self._flow(type="BUY")})
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram_buttons") as buttons,
            ):
                watch.process_callback_query("sellticker:AMD", 1, "cb7", spath)
            buttons.assert_not_called()
            self.assertEqual(watch.load_state(spath)["pending_flow"]["type"], "BUY")
            self.assertIsNone(watch.load_state(spath)["pending_flow"]["ticker"])

    def test_process_callback_query_sell_all_returns_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        type="SELL", step="size_type", ticker="AMD"
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "ibkr_sell_all") as sell_all,
            ):
                action = watch.process_callback_query("size:all", 1, "cb5", spath)
            sell_all.assert_not_called()
            self.assertEqual(
                action, {"action": "sell_all", "ticker": "AMD", "price": None}
            )
            self.assertIsNone(watch.load_state(spath)["pending_flow"])

    def test_process_callback_query_without_flow_still_acks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "answer_callback_query") as ack,
                patch.object(watch, "send_telegram") as send,
            ):
                watch.process_callback_query("size:shares", 1, "cb0", spath)
            ack.assert_called_once_with("cb0")
            send.assert_not_called()

    def test_execute_flow_order_shares_and_dollars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "ibkr_place_order", return_value="✅ shares"
                ) as place,
                patch.object(watch, "ibkr_place_cash_order") as cash,
                patch.object(watch, "send_telegram", return_value=81) as send,
            ):
                msg = watch._execute_flow_order(
                    self._flow(
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                        price_type="market",
                    ),
                    spath,
                )
            self.assertEqual(msg, "✅ shares")
            place.assert_called_once_with("AMD", 2, "BUY", None)
            cash.assert_not_called()
            self.assertEqual(sent_text(send), "✅ shares")
            self.assertEqual(
                watch.load_state(spath)["order_messages"][-1]["ttl_seconds"], 120
            )
            with (
                patch.object(watch, "ibkr_get_price", return_value=10.0),
                patch.object(
                    watch, "ibkr_place_order", return_value="✅ cash"
                ) as place,
                patch.object(watch, "ibkr_place_cash_order") as cash,
                patch.object(watch, "send_telegram", return_value=82) as send,
            ):
                msg = watch._execute_flow_order(
                    self._flow(
                        type="SELL",
                        ticker="NVDA",
                        size_type="dollars",
                        quantity=25.0,
                        price_type="market",
                    ),
                    spath,
                )
            self.assertEqual(msg, "✅ cash")
            place.assert_called_once_with("NVDA", 2, "SELL", None)
            cash.assert_not_called()
            self.assertEqual(sent_text(send), "✅ cash")
            with (
                patch.object(watch, "ibkr_get_price", return_value=10.0),
                patch.object(
                    watch, "ibkr_place_order", return_value="✅ lmt"
                ) as place,
                patch.object(watch, "send_telegram", return_value=83) as send,
            ):
                msg = watch._execute_flow_order(
                    self._flow(
                        ticker="AMD",
                        size_type="dollars",
                        quantity=25.0,
                        price_type="limit",
                        price=9.5,
                    ),
                    spath,
                )
            self.assertEqual(msg, "✅ lmt")
            place.assert_called_once_with("AMD", 2, "BUY", 9.5)
            self.assertEqual(sent_text(send), "✅ lmt")
            with (
                patch.object(watch, "ibkr_get_price", return_value=80.0),
                patch.object(watch, "ibkr_place_order") as place,
                patch.object(watch, "send_telegram", return_value=84) as send,
            ):
                msg = watch._execute_flow_order(
                    self._flow(
                        ticker="CRCL",
                        size_type="dollars",
                        quantity=3.0,
                        price_type="limit",
                        price=70.0,
                    ),
                    spath,
                )
            place.assert_not_called()
            self.assertEqual(sent_text(send), "⚠️ 3.0$ non bastano per comprare nemmeno 1 azione di CRCL (costa 80.00$).")
            self.assertIn("non bastano", msg)

    def test_guided_flow_sends_are_recorded_with_120s_ttl(self) -> None:
        def _last_ttl(path: Path) -> int:
            return watch.load_state(path)["order_messages"][-1]["ttl_seconds"]

        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "send_telegram", return_value=101):
                watch.apply_telegram_buy_flow_start("/compra", spath)
            self.assertEqual(_last_ttl(spath), 120)

            with (
                patch.object(
                    watch,
                    "ibkr_get_positions",
                    return_value=[{"ticker": "AMD", "position": 2}],
                ),
                patch.object(watch, "send_telegram_buttons", return_value=102),
            ):
                watch.apply_telegram_sell_flow_start("/vendi", spath)
            self.assertEqual(_last_ttl(spath), 120)

            with (
                patch.object(watch, "ibkr_get_positions", return_value=[]),
                patch.object(watch, "send_telegram", return_value=103),
            ):
                watch.apply_telegram_sell_flow_start("/vendi", spath)
            self.assertEqual(_last_ttl(spath), 120)

            watch.save_state(spath, {"pending_flow": self._flow(), "order_messages": []})
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram_buttons", return_value=104),
            ):
                watch.process_pending_flow_text("AMD", spath)
            self.assertEqual(_last_ttl(spath), 120)

            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="quantity", ticker="AMD", size_type="shares"
                    )
                },
            )
            with patch.object(watch, "send_telegram_buttons", return_value=105):
                watch.process_pending_flow_text("2", spath)
            self.assertEqual(_last_ttl(spath), 120)

            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        type="SELL", step="size_type", ticker=None
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram_buttons", return_value=106),
            ):
                watch.process_callback_query("sellticker:AMD", 1, "cb", spath)
            self.assertEqual(_last_ttl(spath), 120)

            watch.save_state(
                spath,
                {"pending_flow": self._flow(step="size_type", ticker="AMD")},
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram", return_value=107),
            ):
                watch.process_callback_query("size:shares", 1, "cb", spath)
            self.assertEqual(_last_ttl(spath), 120)

            watch.save_state(
                spath,
                {
                    "pending_flow": self._flow(
                        step="price_type",
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                    )
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram", return_value=108),
            ):
                watch.process_callback_query("price:limit", 1, "cb", spath)
            self.assertEqual(_last_ttl(spath), 120)

            with (
                patch.object(watch, "ibkr_place_order", return_value="✅ ok"),
                patch.object(watch, "send_telegram", return_value=109),
            ):
                watch._execute_flow_order(
                    self._flow(
                        ticker="AMD",
                        size_type="shares",
                        quantity=2.0,
                        price_type="market",
                    ),
                    spath,
                )
            self.assertEqual(_last_ttl(spath), 120)

    def test_send_flow_message_records_120s_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "send_telegram", return_value=55):
                watch._send_flow_message(spath, "Quale ticker vuoi comprare?")
            entry = watch.load_state(spath)["order_messages"][0]
            self.assertEqual(entry["message_id"], 55)
            self.assertEqual(entry["ttl_seconds"], 120)

    def test_send_telegram_buttons_stacks_vertically(self) -> None:
        with (
            patch.object(watch, "telegram_token", return_value="tok"),
            patch.object(watch, "telegram_chat_id", return_value="-100"),
            patch.object(
                watch, "telegram_api", return_value={"message_id": 9}
            ) as api,
        ):
            mid = watch.send_telegram_buttons(
                "Azioni o Dollari?",
                [("Azioni", "size:shares"), ("Dollari", "size:dollars")],
            )
        self.assertEqual(mid, 9)
        api.assert_called_once_with(
            "sendMessage",
            {
                "chat_id": "-100",
                "text": "Azioni o Dollari?",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Azioni", "callback_data": "size:shares"}],
                        [{"text": "Dollari", "callback_data": "size:dollars"}],
                    ]
                },
            },
            timeout=12,
        )

    def test_answer_callback_query_ignores_errors(self) -> None:
        with patch.object(watch, "telegram_api", side_effect=RuntimeError("down")):
            watch.answer_callback_query("cb1")
        with patch.object(watch, "telegram_api") as api:
            watch.answer_callback_query("cb2")
        api.assert_called_once_with(
            "answerCallbackQuery",
            {"callback_query_id": "cb2"},
            timeout=12,
        )

    def test_apply_telegram_start_sends_category_buttons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "edit_telegram_message", return_value=False),
                patch.object(
                    watch, "send_telegram_buttons", return_value=77
                ) as buttons,
            ):
                self.assertTrue(watch.apply_telegram_start("/start", spath))
                self.assertTrue(watch.apply_telegram_start("/MENU", spath))
                self.assertFalse(watch.apply_telegram_start("/list", spath))
            self.assertEqual(buttons.call_count, 2)
            text, rows = buttons.call_args[0]
            self.assertIn("Danny Trade Squad Bot", text)
            self.assertIn("Conto:", text)
            self.assertIn("Contanti:", text)
            self.assertIn("Valore netto:", text)
            self.assertEqual(
                [label for label, _ in rows],
                [
                    "📋 Watchlist",
                    "💰 Trading",
                    "🤖 Trading automatico",
                    "📊 Conto",
                    "ℹ️ Info",
                ],
            )
            self.assertEqual(
                [data for _, data in rows],
                [
                    "menu:watchlist",
                    "menu:trading",
                    "menu:automatico",
                    "menu:conto",
                    "menu:info",
                ],
            )
            self.assertEqual(watch.load_state(spath)["menu_message_id"], 77)

    def test_apply_telegram_start_edits_existing_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"menu_message_id": 88})
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
                patch.object(watch, "send_telegram_buttons") as send,
            ):
                self.assertTrue(watch.apply_telegram_start("/start", spath))
            edit.assert_called_once()
            self.assertEqual(edit.call_args[0][:2], ("-100", 88))
            self.assertEqual(edit.call_args[0][2], watch.format_home_text(None))
            send.assert_not_called()
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=False),
                patch.object(
                    watch, "send_telegram_buttons", return_value=99
                ) as send,
            ):
                self.assertTrue(watch.apply_telegram_start("/start", spath))
            send.assert_called_once()
            self.assertEqual(watch.load_state(spath)["menu_message_id"], 99)

    def test_process_single_message_runs_start_before_pending_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": {"type": "BUY", "step": "ticker"}})
            with (
                patch.object(watch, "apply_telegram_start", return_value=True) as start,
                patch.object(watch, "process_pending_flow_text") as pending,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/start", 50, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            start.assert_called_once_with("/start", spath)
            pending.assert_not_called()
            delete.assert_called_once_with(50)

    def test_process_callback_query_menu_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "answer_callback_query") as ack,
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
                patch.object(watch, "send_telegram_buttons") as send_btns,
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertIsNone(
                    watch.process_callback_query(
                        "menu:watchlist", 1, "cbm1", spath, 70
                    )
                )
                self.assertIsNone(
                    watch.process_callback_query(
                        "menu:trading", 1, "cbm2", spath, 70
                    )
                )
                self.assertIsNone(
                    watch.process_callback_query(
                        "menu:conto", 1, "cbm3", spath, 70
                    )
                )
                self.assertIsNone(
                    watch.process_callback_query(
                        "menu:info", 1, "cbm4", spath, 70
                    )
                )
                self.assertIsNone(
                    watch.process_callback_query(
                        "menu:main", 1, "cbm5", spath, 70
                    )
                )
            self.assertEqual(ack.call_count, 5)
            send_btns.assert_not_called()
            send.assert_not_called()
            self.assertEqual(edit.call_count, 5)
            watchlist_buttons = edit.call_args_list[0][0][3]
            self.assertEqual(
                [data for _, data in watchlist_buttons[:7]],
                [
                    "action:list",
                    "action:set",
                    "action:setbuy",
                    "action:settarget",
                    "action:setstop",
                    "action:rm",
                    "action:clear",
                ],
            )
            self.assertEqual(
                watchlist_buttons[-2:],
                [
                    ("◀️ Indietro", "menu:back"),
                    ("🏠 Home", "menu:main"),
                ],
            )
            self.assertIn("Scegli un'azione", edit.call_args_list[0][0][2])
            self.assertEqual(
                [data for _, data in edit.call_args_list[1][0][3][:4]],
                [
                    "action:buyflow",
                    "action:sellflow",
                    "action:cancel",
                    "action:modify",
                ],
            )
            self.assertEqual(
                [data for _, data in edit.call_args_list[2][0][3][:4]],
                [
                    "action:saldo",
                    "action:posizioni",
                    "action:ordini",
                    "action:history",
                ],
            )
            info_buttons = edit.call_args_list[3][0][3]
            self.assertEqual(
                [data for _, data in info_buttons[:7]],
                [
                    "quotefield:price",
                    "quotefield:book",
                    "quotefield:volume",
                    "quotefield:range",
                    "quotefield:change",
                    "quotefield:session",
                    "quote:go",
                ],
            )
            self.assertEqual(info_buttons[0][0], "✓ Prezzo")
            self.assertEqual(info_buttons[2][0], "✓ Volume")
            self.assertEqual(info_buttons[6], ("🔎 Mostra", "quote:go"))
            self.assertIn("campi che vuoi", edit.call_args_list[3][0][2])
            self.assertEqual(
                edit.call_args_list[3][0][3][-2:],
                [
                    ("◀️ Indietro", "menu:back"),
                    ("🏠 Home", "menu:main"),
                ],
            )
            self.assertEqual(edit.call_args_list[4][0][2], watch.format_home_text(None))
            self.assertEqual(edit.call_args_list[4][0][3], watch.MENU_MAIN_BUTTONS)
            self.assertEqual(watch.load_state(spath)["menu_message_id"], 70)

    def test_trading_automatico_is_home_category_with_trail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
            ):
                watch.process_callback_query("menu:automatico", 1, "cba", spath, 70)
                watch.process_callback_query("menu:back", 1, "cbb", spath, 70)
            self.assertIn("Trading automatico", edit.call_args_list[0][0][2])
            auto_buttons = edit.call_args_list[0][0][3]
            self.assertEqual(auto_buttons[0], ("📉 Trail", "action:trail"))
            self.assertEqual(
                auto_buttons[-2:],
                [
                    ("◀️ Indietro", "menu:back"),
                    ("🏠 Home", "menu:main"),
                ],
            )
            self.assertEqual(edit.call_args_list[1][0][2], watch.format_home_text(None))
            self.assertEqual(watch.load_state(spath)["menu_page"], "main")
            self.assertNotIn(
                "menu:automatico",
                [data for _, data in watch.MENU_TRADING_BUTTONS],
            )

    def test_process_callback_query_menu_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "answer_callback_query"):
                self.assertEqual(
                    watch.process_callback_query("action:list", 1, "cba1", spath),
                    {"action": "list"},
                )
                self.assertEqual(
                    watch.process_callback_query("action:buyflow", 1, "cba2", spath),
                    {"action": "buyflow"},
                )
                self.assertEqual(
                    watch.process_callback_query("action:sellflow", 1, "cba3", spath),
                    {"action": "sellflow"},
                )
                self.assertEqual(
                    watch.process_callback_query("action:set", 1, "cba5", spath),
                    {"action": "set"},
                )
                self.assertEqual(
                    watch.process_callback_query("action:history", 1, "cba6", spath),
                    {"action": "history"},
                )
                self.assertEqual(
                    watch.process_callback_query("action:price", 1, "cba7", spath),
                    {"action": "price"},
                )
                self.assertIsNone(
                    watch.process_callback_query("action:unknown", 1, "cba4", spath)
                )

    def test_edit_telegram_message_best_effort(self) -> None:
        with patch.object(watch, "telegram_api") as api:
            self.assertTrue(
                watch.edit_telegram_message(1, 9, "ciao", [("A", "a")])
            )
        api.assert_called_once_with(
            "editMessageText",
            {
                "chat_id": 1,
                "message_id": 9,
                "text": "ciao",
                "reply_markup": {
                    "inline_keyboard": [[{"text": "A", "callback_data": "a"}]]
                },
            },
            timeout=12,
        )
        with patch.object(watch, "telegram_api") as api_empty:
            self.assertTrue(watch.edit_telegram_message(1, 9, "ciao"))
        self.assertEqual(
            api_empty.call_args[0][1]["reply_markup"],
            {"inline_keyboard": []},
        )
        with patch.object(
            watch, "telegram_api", side_effect=RuntimeError("message is not modified")
        ):
            self.assertTrue(watch.edit_telegram_message(1, 9, "ciao"))
        with patch.object(watch, "telegram_api", side_effect=RuntimeError("old")):
            self.assertFalse(watch.edit_telegram_message(1, 9, "ciao"))

    def test_apply_menu_action_reuses_existing_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "apply_telegram_list") as lst,
                patch.object(watch, "apply_telegram_balance") as bal,
                patch.object(watch, "apply_telegram_positions") as pos,
                patch.object(watch, "apply_telegram_orders") as orders,
                patch.object(watch, "apply_telegram_buy_flow_start") as buy,
                patch.object(watch, "apply_telegram_sell_flow_start") as sell,
                patch.object(watch, "_start_guided_flow") as guided,
            ):
                watch.apply_menu_action("list", wpath, spath)
                watch.apply_menu_action("saldo", wpath, spath)
                watch.apply_menu_action("posizioni", wpath, spath)
                watch.apply_menu_action("ordini", wpath, spath)
                watch.apply_menu_action("buyflow", wpath, spath)
                watch.apply_menu_action("sellflow", wpath, spath)
                watch.apply_menu_action("set", wpath, spath)
                watch.apply_menu_action("history", wpath, spath)
            lst.assert_called_once_with("/list", wpath, spath)
            bal.assert_called_once_with("/saldo", spath)
            pos.assert_called_once_with("/posizioni", spath)
            orders.assert_called_once_with("/ordini", spath)
            buy.assert_called_once_with("/compra", spath)
            sell.assert_called_once_with("/vendi", spath)
            self.assertEqual(
                [call.args[0] for call in guided.call_args_list],
                ["SET", "HISTORY"],
            )

    def test_process_single_message_starts_flow_before_inline_buy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch, "apply_telegram_buy_flow_start", return_value=True
                ) as start,
                patch.object(watch, "apply_telegram_buy") as buy,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                added, removed = watch.process_single_message(
                    "/compra", 40, wpath, spath
                )
            self.assertEqual((added, removed), ([], []))
            start.assert_called_once_with("/compra", spath)
            buy.assert_not_called()
            delete.assert_called_once_with(40)
            with (
                patch.object(watch, "process_pending_flow_text", return_value=True) as pending,
                patch.object(watch, "apply_telegram_list") as lst,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                watch.process_single_message("AMD", 41, wpath, spath)
            pending.assert_called_once_with("AMD", spath, wpath)
            lst.assert_not_called()
            delete.assert_called_once_with(41)

    def test_deliver_text_keeps_one_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=False),
                patch.object(watch, "send_telegram_buttons", return_value=10),
                patch.object(watch, "send_telegram", return_value=10),
            ):
                watch.deliver_text(spath, watch.MENU_MAIN_TEXT, watch.MENU_MAIN_BUTTONS)
            self.assertEqual(watch.load_state(spath)["bot_message_id"], 10)
            self.assertEqual(watch.load_state(spath)["menu_message_id"], 10)
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
                patch.object(watch, "send_telegram") as send,
            ):
                watch.deliver_text(spath, "💰 Conto", with_nav=True)
            edit.assert_called_once()
            self.assertEqual(edit.call_args[0][1], 10)
            send.assert_not_called()
            self.assertEqual(watch.load_state(spath)["balance_message_id"], 10)

    def test_clip_text_ellipsis(self) -> None:
        self.assertEqual(watch.clip_text("ciao", 10), "ciao")
        self.assertEqual(watch.clip_text("abcdef", 4), "abc…")

    def test_start_and_home_clear_pending_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": {"type": "BUY", "step": "ticker"},
                    "menu_message_id": 70,
                    "menu_page": "trading",
                    "menu_nav_stack": ["main"],
                },
            )
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=True),
            ):
                self.assertTrue(watch.apply_telegram_start("/start", spath))
            state = watch.load_state(spath)
            self.assertIsNone(state["pending_flow"])
            self.assertEqual(state["menu_page"], "main")
            self.assertEqual(state["menu_nav_stack"], [])
            watch.save_state(
                spath,
                {
                    "pending_flow": {"type": "SELL", "step": "quantity"},
                    "menu_message_id": 70,
                    "menu_page": "conto",
                    "menu_nav_stack": ["main"],
                },
            )
            with patch.object(watch, "edit_telegram_message", return_value=True):
                watch.process_callback_query("menu:main", 1, "cbh", spath, 70)
            state = watch.load_state(spath)
            self.assertIsNone(state["pending_flow"])
            self.assertEqual(state["menu_page"], "main")

    def test_menu_back_pops_without_clearing_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": {"type": "BUY", "step": "ticker"},
                    "menu_message_id": 70,
                    "menu_page": "watchlist",
                    "menu_nav_stack": ["main"],
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
            ):
                self.assertIsNone(
                    watch.process_callback_query("menu:back", 1, "cbb", spath, 70)
                )
            state = watch.load_state(spath)
            self.assertEqual(state["pending_flow"]["type"], "BUY")
            self.assertEqual(state["menu_page"], "main")
            self.assertEqual(state["menu_nav_stack"], [])
            self.assertEqual(edit.call_args[0][2], watch.format_home_text(None))

    def test_replacing_message_edits_when_possible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"balance_message_id": 99})
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "delete_telegram_message") as delete,
            ):
                watch._send_replacing_message(spath, "balance_message_id", "💰 ok")
            edit.assert_called_once_with("-100", 99, "💰 ok", watch.MENU_NAV_BUTTONS)
            send.assert_not_called()
            delete.assert_not_called()
            self.assertEqual(watch.load_state(spath)["balance_message_id"], 99)

    def test_flow_message_edits_same_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"flow_message_id": 40})
            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", return_value=True) as edit,
                patch.object(watch, "send_telegram") as send,
            ):
                mid = watch._send_flow_message(spath, "A che prezzo?")
            self.assertEqual(mid, 40)
            edit.assert_called_once()
            send.assert_not_called()
            self.assertEqual(
                watch.load_state(spath)["order_messages"][0]["ttl_seconds"], 120
            )

    def test_apply_menu_action_shows_loading_then_restores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {"menu_message_id": 70, "menu_page": "conto", "menu_nav_stack": ["main"]},
            )
            edits: list[str] = []

            def fake_edit(chat_id, message_id, text, buttons=None) -> bool:
                edits.append(text)
                return True

            with (
                patch.object(watch, "telegram_chat_id", return_value="-100"),
                patch.object(watch, "edit_telegram_message", side_effect=fake_edit),
                patch.object(watch, "apply_telegram_balance") as bal,
            ):
                watch.apply_menu_action("saldo", wpath, spath)
            bal.assert_called_once_with("/saldo", spath)
            self.assertEqual(edits[0], watch.IBKR_LOADING_TEXT)
            self.assertNotIn(watch.MENU_CONTO_TEXT, edits)

    def test_format_home_text_includes_account_and_balance(self) -> None:
        empty = watch.format_home_text(None)
        self.assertIn("Conto: n/d", empty)
        self.assertIn("Contanti: n/d", empty)
        self.assertIn("Valore netto: n/d", empty)
        body = watch.format_home_text(
            {
                "account_id": "U123",
                "cashbalance": 1000.5,
                "netliquidationvalue": 5000.25,
                "currency": "USD",
            }
        )
        self.assertIn("Conto: U123", body)
        self.assertIn("Contanti: 1000.5 USD", body)
        self.assertIn("Valore netto: 5000.25 USD", body)

    def test_apply_telegram_start_fetches_live_saldo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(
                    watch,
                    "ibkr_account_snapshot",
                    return_value={
                        "account_id": "U777",
                        "cashbalance": 12,
                        "netliquidationvalue": 34,
                        "currency": "USD",
                    },
                ) as snap,
                patch.object(watch, "edit_telegram_message", return_value=False),
                patch.object(watch, "send_telegram_buttons", return_value=11) as buttons,
            ):
                self.assertTrue(watch.apply_telegram_start("/start", spath))
            snap.assert_called()
            self.assertIn("Conto: U777", buttons.call_args[0][0])
            self.assertIn("Contanti: 12 USD", buttons.call_args[0][0])

    def test_maybe_refresh_home_only_on_main_without_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "bot_message_id": 70,
                    "menu_page": "watchlist",
                    "pending_flow": None,
                },
            )
            with patch.object(watch, "deliver_text") as deliver:
                watch.maybe_refresh_home(spath)
            deliver.assert_not_called()
            watch.save_state(
                spath,
                {
                    "bot_message_id": 70,
                    "menu_page": "main",
                    "pending_flow": {"type": "SET", "step": "ticker"},
                },
            )
            with patch.object(watch, "deliver_text") as deliver:
                watch.maybe_refresh_home(spath)
            deliver.assert_not_called()
            watch.save_state(
                spath,
                {"bot_message_id": 70, "menu_page": "main", "pending_flow": None},
            )
            with (
                patch.object(
                    watch,
                    "ibkr_account_snapshot",
                    return_value={
                        "account_id": "U1",
                        "cashbalance": 1,
                        "netliquidationvalue": 2,
                        "currency": "USD",
                    },
                ),
                patch.object(watch, "deliver_text") as deliver,
            ):
                watch.maybe_refresh_home(spath)
            deliver.assert_called_once()
            self.assertIn("Conto: U1", deliver.call_args[0][1])
            self.assertEqual(deliver.call_args[0][2], watch.MENU_MAIN_BUTTONS)

    def test_set_workflow_asks_then_writes_watchlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "send_telegram") as send:
                watch.apply_menu_action("set", wpath, spath)
            self.assertEqual(sent_text(send), "Quale ticker vuoi impostare?")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["type"], "SET")
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(
                    watch.process_pending_flow_text("AMD", spath, wpath)
                )
            self.assertIn("ingresso?", sent_text(send))
            with patch.object(watch, "send_telegram") as send:
                watch.process_pending_flow_text("130-134", spath, wpath)
            self.assertIn("stop?", sent_text(send))
            with patch.object(watch, "send_telegram") as send:
                watch.process_pending_flow_text("124", spath, wpath)
            self.assertIn("target?", sent_text(send))
            with patch.object(watch, "send_telegram") as send:
                watch.process_pending_flow_text("148", spath, wpath)
            self.assertIn("✅ AMD impostato", sent_text(send))
            self.assertIsNone(watch.load_state(spath)["pending_flow"])
            item = watch.load_watchlist(wpath)[0]
            self.assertEqual(item["ticker"], "AMD")
            self.assertEqual(item["ingresso_low"], 130.0)
            self.assertEqual(item["ingresso_high"], 134.0)
            self.assertEqual(item["stop"], 124.0)
            self.assertEqual(item["target"], 148.0)

    def test_flowticker_and_history_and_clear_buttons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(
                wpath,
                [
                    {
                        "ticker": "AMD",
                        "tf": "",
                        "ingresso_low": 1,
                        "ingresso_high": 1,
                        "stop": 1,
                        "target": 2,
                    }
                ],
            )
            watch.save_state(
                spath,
                {
                    "pending_flow": {
                        "type": "SETBUY",
                        "step": "ticker",
                        "ticker": None,
                    }
                },
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertIsNone(
                    watch.process_callback_query(
                        "flowticker:AMD", 1, "cbt", spath, 70, wpath
                    )
                )
            self.assertIn("prezzo di ingresso?", sent_text(send))
            self.assertEqual(watch.load_state(spath)["pending_flow"]["ticker"], "AMD")
            watch.save_state(
                spath, {"pending_flow": {"type": "HISTORY", "step": "days"}}
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "apply_telegram_history") as hist,
            ):
                self.assertIsNone(
                    watch.process_callback_query("days:7", 1, "cbd", spath, 70)
                )
            hist.assert_called_once_with("/storico 7", spath)
            self.assertIsNone(watch.load_state(spath)["pending_flow"])
            watch.save_state(
                spath, {"pending_flow": {"type": "CLEAR", "step": "confirm"}}
            )
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertIsNone(
                    watch.process_callback_query(
                        "confirm:yes", 1, "cbc", spath, 70, wpath
                    )
                )
            self.assertIn("Watchlist svuotata", sent_text(send))
            self.assertEqual(watch.load_watchlist(wpath), [])

    def test_rm_workflow_uses_watchlist_buttons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "NVDA", "tf": ""}])
            with patch.object(watch, "send_telegram") as send:
                watch.apply_menu_action("rm", wpath, spath)
            self.assertEqual(sent_text(send), "Quale ticker vuoi togliere?")
            markup = send.call_args.kwargs.get("reply_markup") or {}
            self.assertIn(
                {"text": "NVDA", "callback_data": "flowticker:NVDA"},
                markup["inline_keyboard"][0],
            )

    def test_format_quote_card_compacts_selected_fields(self) -> None:
        row = {
            "31": "148.2",
            "58": "Advanced Micro Devices",
            "70": "149.8",
            "71": "146.1",
            "82": "+1.20",
            "83": "+0.82%",
            "84": "148.18",
            "85": "6",
            "86": "148.22",
            "87": "12400000",
            "88": "4",
            "7295": "147.00",
            "7296": "147.00",
        }
        body = watch.format_quote_card(
            "AMD", row, ["price", "book", "volume", "range", "change", "session"]
        )
        self.assertIn("📈 AMD", body)
        self.assertIn("Advanced Micro Devices", body)
        self.assertIn("Prezzo: 148.2", body)
        self.assertIn("Bid / Ask: 148.18 × 4  ·  148.22 × 6", body)
        self.assertIn("Volume: 12.40M", body)
        self.assertIn("Min / Max: 146.1 – 149.8", body)
        self.assertIn("Variazione: +1.20 (+0.82%)", body)
        self.assertIn("Open / Close: 147.00 / 147.00", body)
        self.assertEqual(
            watch.format_quote_card("AMD", None, ["price"]),
            "⚠️ Dati IBKR non disponibili per AMD.",
        )

    def test_quote_field_toggle_then_asks_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": ""}])
            with (
                patch.object(watch, "answer_callback_query"),
                patch.object(watch, "edit_telegram_message", return_value=False),
                patch.object(watch, "send_telegram") as send,
            ):
                watch.process_callback_query(
                    "menu:info", 1, "cbi", spath, 70, wpath
                )
                watch.process_callback_query(
                    "quotefield:book", 1, "cbt", spath, 70, wpath
                )
                watch.process_callback_query(
                    "quote:go", 1, "cbg", spath, 70, wpath
                )
            texts = [
                btn["text"]
                for call in send.call_args_list
                for row in (call.kwargs.get("reply_markup") or {}).get(
                    "inline_keyboard", []
                )
                for btn in row
            ]
            self.assertIn("✓ Bid / Ask", texts)
            self.assertEqual(sent_text(send), "Di quale ticker vuoi le info?")
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["type"], "QUOTE")
            self.assertEqual(flow["step"], "ticker")
            self.assertEqual(flow["quote_fields"], ["price", "book", "volume"])

    def test_quote_ticker_fetches_selected_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": {
                        "type": "QUOTE",
                        "step": "ticker",
                        "quote_fields": ["price", "volume"],
                    }
                },
            )
            row = {"31": "10.5", "58": "AMD", "87": "1500"}
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "ibkr_get_snapshot", return_value=row) as snap,
                patch.object(watch, "time"),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(
                    watch.process_pending_flow_text("AMD", spath, wpath)
                )
            snap.assert_called_once_with("AMD", ["55", "58", "31", "87"])
            body = sent_text(send)
            self.assertIn("📈 AMD", body)
            self.assertIn("Prezzo: 10.5", body)
            self.assertIn("Volume: 1.5K", body)
            self.assertIsNone(watch.load_state(spath)["pending_flow"])

    def test_ibkr_get_snapshot_wakes_then_reads(self) -> None:
        calls: list[str] = []

        def fake_get(path: str):
            calls.append(path)
            if len(calls) == 1:
                return []
            return [{"31": "C 12.3", "87": "100"}]

        with (
            patch.object(watch, "ibkr_lookup_conid", return_value="123"),
            patch.object(watch, "ibkr_get", side_effect=fake_get),
            patch.object(watch, "time") as time_mod,
        ):
            row = watch.ibkr_get_snapshot("AMD", ["31", "87"])
        self.assertEqual(row, {"31": "C 12.3", "87": "100"})
        self.assertEqual(len(calls), 2)
        self.assertIn("fields=31,87", calls[0])
        time_mod.sleep.assert_called_once_with(1)


class GitSyncTests(unittest.TestCase):
    def test_skips_without_token(self) -> None:
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": ""}, clear=False),
            patch.object(watch.subprocess, "run") as run,
        ):
            watch.commit_state_to_git()
        run.assert_not_called()

    def test_no_changes_skips_commit_and_push(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "tok123"}, clear=False),
            patch.object(watch.subprocess, "run", side_effect=fake_run),
        ):
            watch.commit_state_to_git()
        self.assertTrue(any(c[:4] == ["git", "add", "-f", "watchlist.json"] for c in calls))
        self.assertTrue(any("diff" in c and "--quiet" in c for c in calls))
        self.assertFalse(any("commit" in c for c in calls))
        self.assertFalse(any("push" in c for c in calls))

    def test_commits_and_pushes_with_token_url(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(args))
            if "diff" in args and "--quiet" in args:
                return subprocess.CompletedProcess(args, 1, "", "")
            if "diff" in args and "--name-only" in args:
                return subprocess.CompletedProcess(
                    args, 0, "watchlist.json\nwatch_state.json\n", ""
                )
            return subprocess.CompletedProcess(args, 0, "", "")

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "tok123"}, clear=False),
            patch.object(watch.subprocess, "run", side_effect=fake_run),
        ):
            watch.commit_state_to_git()
        self.assertTrue(
            any(
                c[:3] == ["git", "commit", "-m"]
                and "Aggiorna stato watchlist [skip ci]" in c
                for c in calls
            )
        )
        push = next(c for c in calls if c[:2] == ["git", "push"])
        self.assertIn("x-access-token:tok123@", push[2])
        self.assertTrue(push[2].endswith("danny-trade-squad-bot.git"))
        self.assertEqual(push[3:], ["HEAD:main"])

    def test_errors_do_not_raise(self) -> None:
        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "tok123"}, clear=False),
            patch.object(
                watch.subprocess, "run", side_effect=RuntimeError("down")
            ),
        ):
            watch.commit_state_to_git()


if __name__ == "__main__":
    unittest.main()
