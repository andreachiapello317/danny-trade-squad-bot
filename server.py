#!/usr/bin/env python3
"""Webhook Telegram + ciclo prezzi in background. Non piazza ordini."""

from __future__ import annotations

import hmac
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, request

from watch import (
    DEFAULT_STATE,
    DEFAULT_WATCHLIST,
    _execute_flow_order,
    _send_flow_message,
    apply_menu_action,
    chat_matches,
    check_fyi_notifications,
    check_order_fills,
    commit_state_to_git,
    cycle,
    ensure_reply_suppression,
    expire_order_messages,
    ibkr_sell_all,
    in_watch_window,
    load_dotenv,
    load_fired,
    load_state,
    load_watchlist,
    maybe_send_daily_summary,
    payload_text,
    persist_fired,
    process_callback_query,
    process_single_message,
    rome_now,
    save_watchlist,
    send_watchlist_summary,
    telegram_chat_id,
    update_payload,
)

load_dotenv()

app = Flask(__name__)
STATE_LOCK = threading.Lock()
WATCHLIST_PATH = DEFAULT_WATCHLIST
STATE_PATH = DEFAULT_STATE

_price_thread: threading.Thread | None = None


def in_scheduled_window() -> bool:
    """Stessa fascia del cron GitHub Actions: lun–ven, 15–22 ora italiana."""
    local = rome_now()
    return in_watch_window(local) and local.weekday() < 5


def price_loop() -> None:
    while True:
        try:
            if in_scheduled_window():
                with STATE_LOCK:
                    items = load_watchlist(WATCHLIST_PATH)
                    fired = load_fired(load_state(STATE_PATH))
                if items:
                    cycle(items, fired, STATE_PATH, lock=STATE_LOCK)
                with STATE_LOCK:
                    persist_fired(STATE_PATH, fired)
                    items = load_watchlist(WATCHLIST_PATH)
                    maybe_send_daily_summary(items, STATE_PATH)
                    check_order_fills(STATE_PATH)
                    check_fyi_notifications(STATE_PATH)
                    ensure_reply_suppression()
                    expire_order_messages(STATE_PATH)
                    commit_state_to_git()
            else:
                with STATE_LOCK:
                    check_order_fills(STATE_PATH)
                    check_fyi_notifications(STATE_PATH)
                    ensure_reply_suppression()
                    expire_order_messages(STATE_PATH)
                    commit_state_to_git()
        except Exception as exc:
            print(f"Ciclo prezzi: {exc}", file=sys.stderr)
        time.sleep(60)


def start_price_loop() -> None:
    global _price_thread
    if _price_thread is not None and _price_thread.is_alive():
        return
    _price_thread = threading.Thread(target=price_loop, daemon=True, name="watch-price-loop")
    _price_thread.start()


def _commit_watchlist_reset() -> None:
    """Committa solo watchlist.json. Non tocca watch_state.json."""
    try:
        path = Path(WATCHLIST_PATH).resolve()
        repo_root = Path.cwd().resolve()
        try:
            path.relative_to(repo_root)
        except ValueError:
            return
        if path.name != "watchlist.json":
            return
        rel = os.path.relpath(path, repo_root)

        def run(args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                args,
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )

        run(["git", "add", "-f", "--", rel])
        diff = run(["git", "diff", "--staged", "--quiet", "--", rel])
        if diff.returncode == 0:
            return
        commit = run(
            [
                "git",
                "-c",
                "user.name=watch-bot",
                "-c",
                "user.email=watch-bot@users.noreply.github.com",
                "commit",
                "-m",
                "Azzera watchlist al deploy [skip ci]",
                "--",
                rel,
            ]
        )
        if commit.returncode != 0:
            print(f"Commit watchlist reset: {commit.stderr.strip()}", file=sys.stderr)
            return
        push = run(["git", "push"])
        if push.returncode != 0:
            print(f"Push watchlist reset: {push.stderr.strip()}", file=sys.stderr)
    except Exception as exc:
        print(f"Commit watchlist reset: {exc}", file=sys.stderr)


def reset_watchlist_on_boot() -> None:
    save_watchlist(WATCHLIST_PATH, [])
    _commit_watchlist_reset()


def run_callback_action(
    action: dict | None,
    state_path: Path | None = None,
    watchlist_path: Path | None = None,
) -> None:
    """Esegue l'azione lenta restituita da process_callback_query, senza lock."""
    if not isinstance(action, dict):
        return
    path = STATE_PATH if state_path is None else state_path
    wpath = WATCHLIST_PATH if watchlist_path is None else watchlist_path
    kind = action.get("action")
    if kind == "execute_order":
        flow = action.get("flow")
        if isinstance(flow, dict):
            _execute_flow_order(flow, path)
        return
    if kind == "sell_all":
        ticker = str(action.get("ticker") or "").strip()
        if ticker:
            _send_flow_message(path, ibkr_sell_all(ticker, action.get("price")))
        return
    if kind in {"list", "saldo", "posizioni", "ordini", "buyflow", "sellflow"}:
        apply_menu_action(str(kind), wpath, path)


def webhook_secret_ok() -> bool:
    """Se WEBHOOK_SECRET manca (locale), accetta. In produzione Telegram lo rimanda."""
    expected = (os.environ.get("WEBHOOK_SECRET") or "").strip()
    if not expected:
        return True
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return hmac.compare_digest(got, expected)


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    if not webhook_secret_ok():
        return "forbidden", 403
    try:
        update = request.get_json(silent=True) or {}
        print(f"DEBUG webhook update: {update}", file=sys.stderr)
        if not isinstance(update, dict):
            return "ok", 200
        if "callback_query" in update:
            cq = update.get("callback_query")
            if isinstance(cq, dict):
                msg = cq.get("message")
                chat = msg.get("chat") if isinstance(msg, dict) else None
                if chat_matches(chat, telegram_chat_id()):
                    data = cq.get("data")
                    cq_id = cq.get("id")
                    chat_id = chat.get("id") if isinstance(chat, dict) else None
                    if isinstance(data, str) and cq_id is not None:
                        action = None
                        raw_mid = msg.get("message_id") if isinstance(msg, dict) else None
                        with STATE_LOCK:
                            action = process_callback_query(
                                data,
                                chat_id,
                                str(cq_id),
                                STATE_PATH,
                                raw_mid if isinstance(raw_mid, int) else None,
                            )
                        run_callback_action(action, STATE_PATH, WATCHLIST_PATH)
            return "ok", 200
        msg = update_payload(update)
        print(f"DEBUG msg: {msg}, chat_id atteso: {telegram_chat_id()}", file=sys.stderr)
        if not msg or not chat_matches(msg.get("chat"), telegram_chat_id()):
            return "ok", 200
        text = payload_text(msg)
        mid = msg.get("message_id")
        with STATE_LOCK:
            added, removed = process_single_message(
                text,
                mid if isinstance(mid, int) else None,
                WATCHLIST_PATH,
                STATE_PATH,
            )
            if added or removed:
                send_watchlist_summary(added, removed, WATCHLIST_PATH, STATE_PATH)
    except Exception as exc:
        print(f"Webhook: {exc}", file=sys.stderr)
    return "ok", 200


if os.environ.get("SERVER_SOFTWARE", "").lower().startswith("gunicorn"):
    reset_watchlist_on_boot()
    start_price_loop()


if __name__ == "__main__":
    reset_watchlist_on_boot()
    start_price_loop()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
