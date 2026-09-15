#!/usr/bin/env python3
"""Test webhook Flask (senza rete)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import watch
from test_watch import TICKET, _msg

import server


class ScheduledWindowTests(unittest.TestCase):
    def test_weekdays_inside_hours(self) -> None:
        rome = ZoneInfo("Europe/Rome")
        monday = datetime(2026, 9, 14, 16, 0, tzinfo=rome)
        saturday = datetime(2026, 9, 12, 16, 0, tzinfo=rome)
        with patch.object(server, "rome_now", return_value=monday):
            self.assertTrue(server.in_scheduled_window())
        with patch.object(server, "rome_now", return_value=saturday):
            self.assertFalse(server.in_scheduled_window())


class WebhookTests(unittest.TestCase):
    def test_ignores_other_chat(self) -> None:
        client = server.app.test_client()
        payload = {"update_id": 1, "message": _msg(text=TICKET, chat_id=1, message_id=9)}
        with (
            patch.object(server, "process_single_message") as proc,
            patch.object(server, "send_watchlist_summary") as summary,
        ):
            resp = client.post("/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        proc.assert_not_called()
        summary.assert_not_called()

    def test_processes_ticket_and_sends_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            payload = {
                "update_id": 2,
                "message": _msg(text=TICKET, message_id=44),
            }
            client = server.app.test_client()
            with (
                patch.object(server, "WATCHLIST_PATH", wpath),
                patch.object(server, "STATE_PATH", spath),
                patch.object(watch, "is_valid_symbol", return_value=True),
                patch.object(watch, "delete_telegram_message"),
                patch.object(watch, "run_screener") as run,
                patch.object(server, "send_watchlist_summary") as summary,
            ):
                resp = client.post("/webhook", json=payload)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_data(as_text=True), "ok")
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "AMD")
            run.assert_not_called()
            summary.assert_called_once()
            self.assertEqual(summary.call_args[0][0], ["AMD"])

    def test_returns_200_on_internal_error(self) -> None:
        client = server.app.test_client()
        payload = {"update_id": 3, "message": _msg(text="$AMD", message_id=1)}
        with patch.object(server, "update_payload", side_effect=RuntimeError("boom")):
            resp = client.post("/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)

    def test_price_loop_runs_cycle_inside_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            watch.save_state(spath, {})
            with (
                patch.object(server, "WATCHLIST_PATH", wpath),
                patch.object(server, "STATE_PATH", spath),
                patch.object(server, "in_scheduled_window", return_value=True),
                patch.object(server, "cycle") as cyc,
                patch.object(server, "maybe_send_daily_summary") as daily,
                patch.object(server, "check_order_fills") as fills,
                patch.object(server, "expire_order_messages") as expire,
                patch.object(server, "time") as time_mod,
            ):
                time_mod.sleep.side_effect = KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt):
                    server.price_loop()
            cyc.assert_called_once()
            self.assertEqual(cyc.call_args.kwargs.get("lock"), server.STATE_LOCK)
            daily.assert_called_once()
            fills.assert_called_once_with(spath)
            expire.assert_called_once_with(spath)

    def test_price_loop_keeps_going_after_error(self) -> None:
        calls = {"n": 0}

        def boom() -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fail")
            raise KeyboardInterrupt()

        with (
            patch.object(server, "in_scheduled_window", side_effect=boom),
            patch.object(server, "time") as time_mod,
        ):
            time_mod.sleep.return_value = None
            with self.assertRaises(KeyboardInterrupt):
                server.price_loop()
        self.assertEqual(calls["n"], 2)
        time_mod.sleep.assert_called_with(60)


if __name__ == "__main__":
    unittest.main()
