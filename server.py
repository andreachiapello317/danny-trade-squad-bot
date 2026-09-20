#!/usr/bin/env python3
"""Webhook Telegram + ciclo prezzi in background. Non piazza ordini."""

from __future__ import annotations

import hmac
import os
import sys
import threading
import time
from pathlib import Path

from flask import Flask, request

from watch import (
    DEFAULT_STATE,
    DEFAULT_WATCHLIST,
    MENU_ACTION_KINDS,
    _execute_flow_order,
    _send_flow_message,
    apply_menu_action,
    chat_matches,
    check_fyi_notifications,
    check_order_fills,
    check_step_trails,
    commit_state_to_git,
    cycle,
    ensure_reply_suppression,
    expire_order_messages,
    ibkr_sell_all,
    maybe_refresh_home,
    in_watch_window,
    load_dotenv,
    load_fired,
    load_state,
    load_watchlist,
    payload_text,
    persist_fired,
    process_callback_query,
    process_single_message,
    rome_now,
    run_ibkr_order_socket,
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
_ws_thread: threading.Thread | None = None
_ws_stop = threading.Event()


def in_scheduled_window() -> bool:
    """Stessa fascia del cron GitHub Actions: lun–ven, 15–22 ora italiana."""
    local = rome_now()
    return in_watch_window(local) and local.weekday() < 5


def price_loop() -> None:
    while True:
        try:
            ensure_reply_suppression()
            with STATE_LOCK:
                items = load_watchlist(WATCHLIST_PATH)
                fired = load_fired(load_state(STATE_PATH))
            if items:
                cycle(
                    items,
                    fired,
                    STATE_PATH,
                    lock=STATE_LOCK,
                    watchlist_path=WATCHLIST_PATH,
                )
            with STATE_LOCK:
                persist_fired(STATE_PATH, fired)
                check_order_fills(STATE_PATH)
                check_step_trails(STATE_PATH)
                check_fyi_notifications(STATE_PATH)
                expire_order_messages(STATE_PATH)
                maybe_refresh_home(STATE_PATH)
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


def start_ibkr_order_socket() -> None:
    global _ws_thread
    if _ws_thread is not None and _ws_thread.is_alive():
        return
    _ws_stop.clear()
    _ws_thread = threading.Thread(
        target=run_ibkr_order_socket,
        kwargs={
            "state_path": STATE_PATH,
            "watchlist_path": WATCHLIST_PATH,
            "stop": _ws_stop,
            "lock": STATE_LOCK,
        },
        daemon=True,
        name="ibkr-order-ws",
    )
    _ws_thread.start()


def reset_watchlist_on_boot() -> None:
    """Non svuota più: Set buy deve restare dopo restart/deploy."""
    return


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
    if kind in MENU_ACTION_KINDS:
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
                                WATCHLIST_PATH,
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
    ensure_reply_suppression()
    start_price_loop()
    start_ibkr_order_socket()


if __name__ == "__main__":
    ensure_reply_suppression()
    start_price_loop()
    start_ibkr_order_socket()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
