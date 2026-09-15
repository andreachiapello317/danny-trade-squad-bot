#!/usr/bin/env python3
"""Webhook Telegram + ciclo prezzi in background. Non piazza ordini."""

from __future__ import annotations

import os
import sys
import threading
import time

from flask import Flask, request

from watch import (
    DEFAULT_STATE,
    DEFAULT_WATCHLIST,
    chat_matches,
    cycle,
    in_watch_window,
    load_dotenv,
    load_fired,
    load_state,
    load_watchlist,
    maybe_send_daily_summary,
    payload_text,
    persist_fired,
    process_single_message,
    rome_now,
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
        except Exception as exc:
            print(f"Ciclo prezzi: {exc}", file=sys.stderr)
        time.sleep(60)


def start_price_loop() -> None:
    global _price_thread
    if _price_thread is not None and _price_thread.is_alive():
        return
    _price_thread = threading.Thread(target=price_loop, daemon=True, name="watch-price-loop")
    _price_thread.start()


@app.post("/webhook")
def webhook() -> tuple[str, int]:
    try:
        update = request.get_json(silent=True) or {}
        print(f"DEBUG webhook update: {update}", file=sys.stderr)
        if not isinstance(update, dict):
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
    start_price_loop()


if __name__ == "__main__":
    start_price_loop()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
