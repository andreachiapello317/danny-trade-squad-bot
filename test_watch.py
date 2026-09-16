#!/usr/bin/env python3
"""Test parser ticket + ingest Telegram (senza rete)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
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
            send.assert_called_once_with(
                "💰 Conto U9\nContanti: 10 EUR\nValore netto: 20 EUR"
            )

    def test_apply_telegram_balance_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(watch, "ibkr_get", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            send.assert_called_with("⚠️ Impossibile leggere il conto IBKR al momento.")
            with (
                patch.object(
                    watch, "ibkr_get", side_effect=[[{"accountId": "U1"}], None]
                ),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_balance("/saldo", spath))
            send.assert_called_with("⚠️ Impossibile leggere il saldo al momento.")

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
            send.assert_called_once_with("📈 AMD (IBKR): 148.20")
            with (
                patch.object(watch, "ibkr_get_price", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_price("/prezzo NVDA", spath))
            send.assert_called_once_with("⚠️ Prezzo IBKR non disponibile per NVDA.")

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
            send.assert_called_once_with("📈 AMD (IBKR): 10.50")
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
                "⚠️ Ordine non confermato per AMD, controlla manualmente su IBKR.",
            )

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
        with patch.object(watch, "ibkr_get", return_value=None):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Impossibile leggere gli ordini aperti.",
            )
        with patch.object(watch, "ibkr_get", return_value={"orders": []}):
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
        ):
            self.assertEqual(
                watch.ibkr_cancel_order("AMD"),
                "⚠️ Errore nell'annullamento dell'ordine per AMD.",
            )

    def test_apply_telegram_cancel_order(self) -> None:
        with (
            patch.object(
                watch, "ibkr_cancel_order", return_value="🚫 Ordine per AMD annullato."
            ) as cancel,
            patch.object(watch, "send_telegram") as send,
        ):
            self.assertTrue(watch.apply_telegram_cancel_order("/annulla $amd"))
            self.assertTrue(watch.apply_telegram_cancel_order("/ANNULLA NVDA"))
            self.assertFalse(watch.apply_telegram_cancel_order("/vendi AMD 1"))
        self.assertEqual([c.args[0] for c in cancel.call_args_list], ["AMD", "NVDA"])
        self.assertEqual(send.call_count, 2)

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
            cancel.assert_called_once_with("/annulla AMD")
            delete.assert_called_once_with(23)

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
            send.assert_called_once_with("📭 Nessuna posizione aperta.")
            with (
                patch.object(watch, "ibkr_get_positions", return_value=None),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_positions("/posizioni", spath))
            send.assert_called_once_with("⚠️ Impossibile leggere le posizioni al momento.")
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
            send.assert_called_once_with("📭 Nessuna posizione aperta.")
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
            ]
        }
        with patch.object(watch, "ibkr_get", return_value=payload):
            active = watch.ibkr_get_active_orders()
        self.assertEqual([o["ticker"] for o in active], ["AMD", "HOOD"])
        with patch.object(watch, "ibkr_get", return_value=None):
            self.assertIsNone(watch.ibkr_get_active_orders())

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
            with (
                patch.object(watch, "ibkr_get_active_orders", return_value=[]),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.apply_telegram_orders("/ORDINI", spath))
            send.assert_called_with("📭 Nessun ordine attivo.")

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
        self.assertIn("Totale fee: 1.05", body)

    def test_apply_telegram_history_empty_and_unavailable(self) -> None:
        with (
            patch.object(watch, "ibkr_get_trades", return_value=None),
            patch.object(watch, "send_telegram") as send,
        ):
            self.assertTrue(watch.apply_telegram_history("/storico 3"))
        send.assert_called_with("⚠️ Impossibile leggere lo storico ordini al momento.")
        with (
            patch.object(watch, "ibkr_get_trades", return_value=[]),
            patch.object(watch, "send_telegram") as send,
        ):
            self.assertTrue(watch.apply_telegram_history("/STORICO 3"))
        send.assert_called_with("📭 Nessun ordine eseguito negli ultimi 3 giorni.")

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
            hist.assert_called_once_with("/storico 7")
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
            ):
                watch.check_order_fills(spath)
                watch.check_order_fills(spath)
            send.assert_called_once_with(
                "✅ ESEGUITO: BUY 2 AMD @ 148.2 · fee: 1.05"
            )
            state = watch.load_state(spath)
            self.assertEqual(state["known_order_status"]["77"], "Filled")
            self.assertEqual(state["order_messages"][0]["message_id"], 66)

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
            send.assert_called_with("Watchlist vuota.")

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

        def fake_send(text: str, chat_id_override: str | None = None) -> int | None:
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
            send.assert_called_once_with("Quale ticker vuoi comprare?")
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["type"], "BUY")
            self.assertEqual(flow["step"], "ticker")
            self.assertIsNone(flow["ticker"])

    def test_apply_telegram_sell_flow_start_sets_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.apply_telegram_sell_flow_start("/vendi", spath))
            send.assert_called_once_with("Quale ticker vuoi vendere?")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["type"], "SELL")

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
                [("Azioni", "size:shares"), ("Dollari", "size:dollars")],
            )
            send.assert_not_called()
            flow = watch.load_state(spath)["pending_flow"]
            self.assertEqual(flow["ticker"], "AMD")
            self.assertEqual(flow["step"], "size_type")
            watch.save_state(spath, {"pending_flow": self._flow()})
            with patch.object(watch, "send_telegram") as send:
                self.assertTrue(watch.process_pending_flow_text("too-long-name", spath))
            send.assert_called_once_with("⚠️ Ticker non valido, riprova.")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "ticker")

    def test_sell_flow_size_buttons_include_vendi_tutto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath, {"pending_flow": self._flow(type="SELL")}
            )
            with (
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "send_telegram_buttons") as buttons,
            ):
                self.assertTrue(watch.process_pending_flow_text("AMD", spath))
            buttons.assert_called_once_with(
                "Azioni o Dollari?",
                [
                    ("Azioni", "size:shares"),
                    ("Dollari", "size:dollars"),
                    ("Vendi tutto", "size:all"),
                ],
            )
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(spath, {"pending_flow": self._flow()})
            with (
                patch.object(watch, "is_valid_symbol", return_value=False),
                patch.object(watch, "send_telegram") as send,
            ):
                self.assertTrue(watch.process_pending_flow_text("BTC", spath))
            send.assert_called_once_with("⚠️ Ticker non valido, riprova.")
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
            send.assert_called_once_with("⚠️ Numero non valido, riprova.")
            self.assertEqual(
                watch.load_state(spath)["pending_flow"]["step"], "quantity"
            )
            with patch.object(watch, "send_telegram_buttons") as buttons:
                self.assertTrue(watch.process_pending_flow_text("2", spath))
            buttons.assert_called_once_with(
                "A mercato o a limite?",
                [("A mercato", "price:market"), ("A limite", "price:limit")],
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
            send.assert_called_once_with("⚠️ Prezzo non valido, riprova.")
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
            send.assert_called_once_with("Quante azioni?")
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
            send.assert_called_once_with("Quanti dollari?")
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
            send.assert_called_once_with("A che prezzo?")
            self.assertEqual(watch.load_state(spath)["pending_flow"]["step"], "price")
            self.assertEqual(
                watch.load_state(spath)["pending_flow"]["price_type"], "limit"
            )

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
        with (
            patch.object(
                watch, "ibkr_place_order", return_value="✅ shares"
            ) as place,
            patch.object(watch, "ibkr_place_cash_order") as cash,
            patch.object(watch, "send_telegram") as send,
        ):
            msg = watch._execute_flow_order(
                self._flow(
                    ticker="AMD",
                    size_type="shares",
                    quantity=2.0,
                    price_type="market",
                )
            )
        self.assertEqual(msg, "✅ shares")
        place.assert_called_once_with("AMD", 2, "BUY", None)
        cash.assert_not_called()
        send.assert_called_once_with("✅ shares")
        with (
            patch.object(watch, "ibkr_get_price", return_value=10.0),
            patch.object(
                watch, "ibkr_place_order", return_value="✅ cash"
            ) as place,
            patch.object(watch, "ibkr_place_cash_order") as cash,
            patch.object(watch, "send_telegram") as send,
        ):
            msg = watch._execute_flow_order(
                self._flow(
                    type="SELL",
                    ticker="NVDA",
                    size_type="dollars",
                    quantity=25.0,
                    price_type="market",
                )
            )
        self.assertEqual(msg, "✅ cash")
        place.assert_called_once_with("NVDA", 2, "SELL", None)
        cash.assert_not_called()
        send.assert_called_once_with("✅ cash")
        with (
            patch.object(watch, "ibkr_get_price", return_value=10.0),
            patch.object(
                watch, "ibkr_place_order", return_value="✅ lmt"
            ) as place,
            patch.object(watch, "send_telegram") as send,
        ):
            msg = watch._execute_flow_order(
                self._flow(
                    ticker="AMD",
                    size_type="dollars",
                    quantity=25.0,
                    price_type="limit",
                    price=9.5,
                )
            )
        self.assertEqual(msg, "✅ lmt")
        place.assert_called_once_with("AMD", 2, "BUY", 9.5)
        send.assert_called_once_with("✅ lmt")
        with (
            patch.object(watch, "ibkr_get_price", return_value=80.0),
            patch.object(watch, "ibkr_place_order") as place,
            patch.object(watch, "send_telegram") as send,
        ):
            msg = watch._execute_flow_order(
                self._flow(
                    ticker="CRCL",
                    size_type="dollars",
                    quantity=3.0,
                    price_type="limit",
                    price=70.0,
                )
            )
        place.assert_not_called()
        send.assert_called_once_with(
            "⚠️ 3.0$ non bastano per comprare nemmeno 1 azione di CRCL (costa 80.00$)."
        )
        self.assertIn("non bastano", msg)

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
            pending.assert_called_once_with("AMD", spath)
            lst.assert_not_called()
            delete.assert_called_once_with(41)


if __name__ == "__main__":
    unittest.main()
