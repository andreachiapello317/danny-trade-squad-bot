#!/usr/bin/env python3
"""Test webhook Flask (senza rete)."""

from __future__ import annotations

import json
import os
import subprocess
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
                patch.object(server, "send_watchlist_summary") as summary,
                patch.object(server, "commit_state_to_git") as sync,
            ):
                resp = client.post("/webhook", json=payload)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_data(as_text=True), "ok")
            items = json.loads(wpath.read_text(encoding="utf-8"))
            self.assertEqual(items[0]["ticker"], "AMD")
            summary.assert_called_once()
            self.assertEqual(summary.call_args[0][0], ["AMD"])
            sync.assert_not_called()

    def test_processes_callback_query_and_skips_message_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            payload = {
                "update_id": 8,
                "callback_query": {
                    "id": "cb9",
                    "data": "size:shares",
                    "message": _msg(text="Azioni o Dollari?", message_id=70),
                },
            }
            client = server.app.test_client()
            with (
                patch.object(server, "STATE_PATH", spath),
                patch.object(server, "process_callback_query") as cb,
                patch.object(server, "process_single_message") as proc,
            ):
                resp = client.post("/webhook", json=payload)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.get_data(as_text=True), "ok")
            cb.assert_called_once_with(
                "size:shares",
                int(watch.DEFAULT_CHAT_ID),
                "cb9",
                spath,
                70,
            )
            proc.assert_not_called()

    def test_callback_executes_order_outside_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            watch.save_state(
                spath,
                {
                    "pending_flow": {
                        "type": "BUY",
                        "step": "price_type",
                        "ticker": "AMD",
                        "size_type": "shares",
                        "quantity": 2.0,
                        "price_type": None,
                    }
                },
            )
            held_during_order: list[bool] = []

            def fake_execute(flow: dict, state_path=None) -> str:
                held_during_order.append(server.STATE_LOCK.locked())
                return "✅ ok"

            payload = {
                "update_id": 10,
                "callback_query": {
                    "id": "cb11",
                    "data": "price:market",
                    "message": _msg(text="A mercato o a limite?", message_id=80),
                },
            }
            client = server.app.test_client()
            with (
                patch.object(server, "STATE_PATH", spath),
                patch.object(watch, "answer_callback_query"),
                patch.object(server, "_execute_flow_order", side_effect=fake_execute) as exe,
                patch.object(server, "process_single_message") as proc,
            ):
                resp = client.post("/webhook", json=payload)
            self.assertEqual(resp.status_code, 200)
            exe.assert_called_once()
            self.assertEqual(exe.call_args[0][0]["ticker"], "AMD")
            self.assertEqual(held_during_order, [False])
            self.assertIsNone(watch.load_state(spath)["pending_flow"])
            proc.assert_not_called()

    def test_run_callback_action_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            wpath = Path(tmp) / "watchlist.json"
            with (
                patch.object(server, "_execute_flow_order") as exe,
                patch.object(server, "ibkr_sell_all", return_value="✅ sold") as sell,
                patch.object(server, "_send_flow_message") as send,
                patch.object(server, "apply_menu_action") as menu,
            ):
                server.run_callback_action(None, spath)
                server.run_callback_action({"action": "noop"}, spath)
                server.run_callback_action(
                    {"action": "execute_order", "flow": {"ticker": "AMD"}},
                    spath,
                )
                server.run_callback_action(
                    {"action": "sell_all", "ticker": "NVDA", "price": None},
                    spath,
                )
                server.run_callback_action(
                    {"action": "saldo"}, spath, wpath
                )
            exe.assert_called_once_with({"ticker": "AMD"}, spath)
            sell.assert_called_once_with("NVDA", None)
            send.assert_called_once_with(spath, "✅ sold")
            menu.assert_called_once_with("saldo", wpath, spath)

    def test_ignores_callback_query_from_other_chat(self) -> None:
        payload = {
            "update_id": 9,
            "callback_query": {
                "id": "cb10",
                "data": "size:shares",
                "message": _msg(text="Azioni o Dollari?", chat_id=1, message_id=71),
            },
        }
        client = server.app.test_client()
        with patch.object(server, "process_callback_query") as cb:
            resp = client.post("/webhook", json=payload)
        self.assertEqual(resp.status_code, 200)
        cb.assert_not_called()

    def test_webhook_secret_rejects_wrong_header(self) -> None:
        client = server.app.test_client()
        payload = {"update_id": 1, "message": _msg(text="$AMD", message_id=1)}
        with (
            patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cret"}, clear=False),
            patch.object(server, "process_single_message") as proc,
        ):
            resp = client.post("/webhook", json=payload)
        self.assertEqual(resp.status_code, 403)
        proc.assert_not_called()
        with (
            patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cret"}, clear=False),
            patch.object(
                server, "process_single_message", return_value=([], [])
            ) as proc,
            patch.object(server, "send_watchlist_summary"),
        ):
            resp = client.post(
                "/webhook",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
            )
        self.assertEqual(resp.status_code, 200)
        proc.assert_called()

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
                patch.object(server, "check_fyi_notifications") as fyi,
                patch.object(server, "ensure_reply_suppression") as suppress,
                patch.object(server, "expire_order_messages") as expire,
                patch.object(server, "commit_state_to_git") as sync,
                patch.object(server, "time") as time_mod,
            ):
                time_mod.sleep.side_effect = KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt):
                    server.price_loop()
            cyc.assert_called_once()
            self.assertEqual(cyc.call_args.kwargs.get("lock"), server.STATE_LOCK)
            daily.assert_called_once()
            fills.assert_called_once_with(spath)
            fyi.assert_called_once_with(spath)
            suppress.assert_called_once_with()
            expire.assert_called_once_with(spath)
            sync.assert_called_once()

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

    def test_price_loop_runs_fills_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spath = Path(tmp) / "watch_state.json"
            with (
                patch.object(server, "STATE_PATH", spath),
                patch.object(server, "in_scheduled_window", return_value=False),
                patch.object(server, "check_order_fills") as fills,
                patch.object(server, "check_fyi_notifications") as fyi,
                patch.object(server, "ensure_reply_suppression") as suppress,
                patch.object(server, "expire_order_messages") as expire,
                patch.object(server, "commit_state_to_git") as sync,
                patch.object(server, "time") as time_mod,
            ):
                time_mod.sleep.side_effect = KeyboardInterrupt()
                with self.assertRaises(KeyboardInterrupt):
                    server.price_loop()
            fills.assert_called_once_with(spath)
            fyi.assert_called_once_with(spath)
            suppress.assert_called_once_with()
            expire.assert_called_once_with(spath)
            sync.assert_called_once()


class ResetWatchlistOnBootTests(unittest.TestCase):
    def test_empties_watchlist_and_keeps_known_order_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            watch.save_watchlist(wpath, [{"ticker": "AMD", "tf": "daily"}])
            watch.save_state(spath, {"known_order_status": {"77": "Filled"}})
            with (
                patch.object(server, "WATCHLIST_PATH", wpath),
                patch.object(server, "STATE_PATH", spath),
                patch.object(server, "_commit_watchlist_reset") as commit,
            ):
                server.reset_watchlist_on_boot()
            self.assertEqual(json.loads(wpath.read_text(encoding="utf-8")), [])
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertEqual(state["known_order_status"], {"77": "Filled"})
            commit.assert_called_once()

    def test_git_commit_only_watchlist_json(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(args))
            result = subprocess.CompletedProcess(args, 0, "", "")
            if "diff" in args:
                result.returncode = 1
            return result

        with (
            patch.object(server, "WATCHLIST_PATH", Path("watchlist.json")),
            patch.object(server.subprocess, "run", side_effect=fake_run),
        ):
            server._commit_watchlist_reset()
        self.assertTrue(any(c[:2] == ["git", "add"] for c in calls))
        self.assertTrue(any("commit" in c for c in calls))
        joined = [" ".join(c) for c in calls]
        self.assertTrue(any("watchlist.json" in line for line in joined))
        self.assertFalse(any("watch_state.json" in line for line in joined))


if __name__ == "__main__":
    unittest.main()
