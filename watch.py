#!/usr/bin/env python3
"""Ticket Trader → watchlist automatica da Telegram. Prezzo Yahoo vs livelli.

Non piazza ordini. Non è consulenza finanziaria.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:  # pragma: no cover
    TelegramClient = None
    StringSession = None

DEFAULT_WATCHLIST = Path("watchlist.json")
DEFAULT_STATE = Path("watch_state.json")
DEFAULT_INTERVAL = 60
DEFAULT_CHAT_ID = "-1004312726798"
IBKR_BASE_URL = "https://danny-ibeam:5000"
_CONID_CACHE: dict[str, str] = {}
_ACCOUNT_ID_CACHE: str | None = None
_IBKR_PRICE_RE = re.compile(r"-?\d+(?:\.\d+)?")
SINGLE_TOUCH_PCT = 0.0015
WATCH_TZ = ZoneInfo("Europe/Rome")
WATCH_HOUR_START = 15
WATCH_HOUR_END = 22  # inclusivo: 15:00–22:59 ora italiana
ALERT_TTL = timedelta(hours=8)
ORDER_MESSAGE_TTL = timedelta(seconds=60)
FLOW_MESSAGE_TTL = timedelta(seconds=120)
MISSING_TOKEN_MSG = (
    "Manca TELEGRAM_BOT_TOKEN: mettilo una volta in .env e aggiungi il bot "
    "al gruppo (Group Privacy OFF su @BotFather). Poi gira da solo."
)
UPDATE_KEYS = (
    "message",
    "channel_post",
    "edited_message",
    "edited_channel_post",
)

TICKER_START = re.compile(r"^\$([A-Za-z]{1,8}(?:[.\-][A-Za-z]{1,4})?)\b", re.M)
FIRST_TICKER = re.compile(r"\$([A-Za-z]{1,8}(?:[.\-][A-Za-z]{1,4})?)\b")
TF_RE = re.compile(
    r"(?:^|\s)(?:[·•|,/\-]\s*)?(daily|weekly|monthly|intraday)\b",
    re.I,
)
DANNY_RE = re.compile(r"^Danny:\s*(.+)$", re.I | re.M)
NUM = r"(\d+(?:[.,]\d+)?)"
RANGE_SEP = r"[-–—−]"
INGRESSO_RE = re.compile(
    rf"ingresso\s*:?\s*{NUM}(?:\s*{RANGE_SEP}\s*{NUM})?",
    re.I,
)
STOP_RE = re.compile(rf"\bstop\s*:?\s*{NUM}", re.I)
TARGET_RE = re.compile(rf"\btarget\s*:?\s*{NUM}", re.I)
LIVELLI_LINE_RE = re.compile(r"^Livelli:\s*(.+)$", re.I | re.M)
BARE_NUM_RE = re.compile(rf"{NUM}(?:\s*{RANGE_SEP}\s*{NUM})?")
REMOVE_RE = re.compile(r"^/(?:rm|remove|rimuovi)\s+\$?([A-Za-z]{1,8})\b", re.I)
SET_RE = re.compile(
    rf"^/set\s+\$?([A-Za-z]{{1,8}})\s+({NUM}(?:{RANGE_SEP}{NUM})?)\s+"
    rf"{NUM}\s+{NUM}",
    re.I,
)
CLEAR_RE = re.compile(r"^/(?:clear|reset|clearall)\s*$", re.I)
LIST_RE = re.compile(r"^/(?:list|watchlist)\s*$", re.I)
SET_FIELD_RE = re.compile(
    rf"^/(setbuy|settarget|setstop)\s+\$?([A-Za-z]{{1,8}})\s+{NUM}",
    re.I,
)
SET_LINE_RE = re.compile(
    rf"^\$?([A-Za-z]{{1,8}})\s+({NUM}(?:{RANGE_SEP}{NUM})?)\s+"
    rf"{NUM}\s+{NUM}\s*$",
    re.I,
)
SETBUY_LINE_RE = re.compile(
    rf"^\$?([A-Za-z]{{1,8}})\s+{NUM}\s*$",
    re.I,
)
BALANCE_RE = re.compile(r"^/saldo\s*$", re.I)
PRICE_RE = re.compile(r"^/prezzo\s+\$?([A-Za-z]{1,8})\s*$", re.I)
BUY_RE = re.compile(
    r"^/compra\s+\$?([A-Za-z]{1,8})\s+(\d+)(?:\s+([\d.]+))?\s*$", re.I
)
SELL_RE = re.compile(
    r"^/vendi\s+\$?([A-Za-z]{1,8})\s+(\d+)(?:\s+([\d.]+))?\s*$", re.I
)
BUY_FLOW_START_RE = re.compile(r"^/compra\s*$", re.I)
SELL_FLOW_START_RE = re.compile(r"^/vendi\s*$", re.I)
FLOW_TICKER_RE = re.compile(r"^\$?([A-Za-z]{1,8})$")
CANCEL_ORDER_RE = re.compile(r"^/annulla\s+\$?([A-Za-z]{1,8})\s*$", re.I)
MODIFY_ORDER_RE = re.compile(
    r"^/modifica\s+\$?([A-Za-z]{1,8})\s+([\d.]+)\s*$", re.I
)
POSITIONS_RE = re.compile(r"^/posizioni\s*$", re.I)
ORDERS_RE = re.compile(r"^/ordini\s*$", re.I)
HISTORY_RE = re.compile(r"^/storico\s+(\d+)\s*$", re.I)
TRAIL_RE = re.compile(
    r"^/trail\s+\$?([A-Za-z]{1,8})\s+(\d+)\s+([\d.]+)\s*$", re.I
)


def parse_num(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def to_yahoo(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def classify_ticker(ticker: str) -> str | None:
    if yf is None:
        return None
    try:
        raw = yf.Ticker(to_yahoo(ticker)).info.get("quoteType")
    except Exception:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip().upper()


def is_valid_symbol(ticker: str) -> bool:
    kind = classify_ticker(ticker)
    if kind is None:
        return True
    return kind in {"EQUITY", "ETF"}


def split_tickets(text: str) -> list[str]:
    matches = list(TICKER_START.finditer(text))
    if not matches:
        return []
    blocks: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.start() : end].strip()
        if block:
            blocks.append(block)
    return blocks


def _levels_from_livelli_line(line: str) -> dict[str, float | None]:
    """Se Livelli: non ha etichette, leggi i numeri in ordine: ingresso, stop, target."""
    rest = line.split(":", 1)[-1] if ":" in line else line
    if re.search(r"ingresso|\bstop\b|\btarget\b", rest, re.I):
        return {}
    found = list(BARE_NUM_RE.finditer(rest))
    out: dict[str, float | None] = {}
    if not found:
        return out
    a, b = found[0].group(1), found[0].group(2)
    out["ingresso_low"] = parse_num(a)
    out["ingresso_high"] = parse_num(b) if b else parse_num(a)
    if len(found) >= 2:
        out["stop"] = parse_num(found[1].group(1))
    if len(found) >= 3:
        out["target"] = parse_num(found[2].group(1))
    return out


def parse_ticket(text: str) -> dict[str, Any] | None:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return None
    m = FIRST_TICKER.search(text)
    if not m:
        return None
    ticker = m.group(1).upper()
    first_line = text.split("\n", 1)[0]
    tf_m = TF_RE.search(first_line) or TF_RE.search(text[:120])
    tf = tf_m.group(1).lower() if tf_m else ""

    danny = DANNY_RE.search(text)
    motivo = danny.group(1).strip() if danny else ""

    ingresso_low = ingresso_high = stop = target = None
    ing = INGRESSO_RE.search(text)
    if ing:
        ingresso_low = parse_num(ing.group(1))
        ingresso_high = parse_num(ing.group(2)) if ing.group(2) else ingresso_low
    st = STOP_RE.search(text)
    if st:
        stop = parse_num(st.group(1))
    tg = TARGET_RE.search(text)
    if tg:
        target = parse_num(tg.group(1))

    if ingresso_low is None or stop is None or target is None:
        liv = LIVELLI_LINE_RE.search(text)
        if liv:
            extra = _levels_from_livelli_line(liv.group(0))
            if ingresso_low is None and extra.get("ingresso_low") is not None:
                ingresso_low = extra["ingresso_low"]
                ingresso_high = extra.get("ingresso_high")
            if stop is None and extra.get("stop") is not None:
                stop = extra["stop"]
            if target is None and extra.get("target") is not None:
                target = extra["target"]

    if ingresso_low is not None and ingresso_high is not None:
        if ingresso_low > ingresso_high:
            ingresso_low, ingresso_high = ingresso_high, ingresso_low

    return {
        "ticker": ticker,
        "tf": tf,
        "ingresso_low": ingresso_low,
        "ingresso_high": ingresso_high,
        "stop": stop,
        "target": target,
        "motivo": motivo,
    }


def parse_tickets(text: str) -> list[dict[str, Any]]:
    blocks = split_tickets(text)
    if not blocks:
        one = parse_ticket(text)
        return [one] if one else []
    out: list[dict[str, Any]] = []
    for block in blocks:
        item = parse_ticket(block)
        if item:
            out.append(item)
    return out


def load_watchlist(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("tickets") or raw.get("items") or []
    if not isinstance(raw, list):
        return []
    return raw


def save_watchlist(path: Path, items: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def upsert(items: list[dict[str, Any]], ticket: dict[str, Any]) -> list[dict[str, Any]]:
    key = (ticket["ticker"], ticket.get("tf") or "")
    next_items: list[dict[str, Any]] = []
    replaced = False
    for it in items:
        if (it.get("ticker"), it.get("tf") or "") == key:
            next_items.append(ticket)
            replaced = True
        else:
            next_items.append(it)
    if not replaced:
        next_items.append(ticket)
    return next_items


def _ticket_sig(ticket: dict[str, Any]) -> tuple[Any, ...]:
    return (
        ticket.get("ticker"),
        ticket.get("tf") or "",
        ticket.get("ingresso_low"),
        ticket.get("ingresso_high"),
        ticket.get("stop"),
        ticket.get("target"),
        ticket.get("motivo") or "",
    )


def upsert_if_changed(
    items: list[dict[str, Any]], ticket: dict[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    key = (ticket["ticker"], ticket.get("tf") or "")
    for it in items:
        if (it.get("ticker"), it.get("tf") or "") == key:
            if _ticket_sig(it) == _ticket_sig(ticket):
                return items, False
            return upsert(items, ticket), True
    return upsert(items, ticket), True


def merge_ticket(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for field in ("ingresso_low", "ingresso_high", "stop", "target"):
        value = incoming.get(field)
        if value is not None:
            merged[field] = value
    motivo = incoming.get("motivo")
    if isinstance(motivo, str) and motivo:
        merged["motivo"] = motivo
    merged["ticker"] = incoming["ticker"]
    merged["tf"] = incoming.get("tf") or ""
    return merged


def refresh_watchlist_summary(watchlist_path: Path, state_path: Path) -> None:
    state = load_state(state_path)
    old_id = state.get("summary_message_id")
    if old_id is not None:
        delete_telegram_message(old_id)
    items = load_watchlist(watchlist_path)
    if not items:
        body = "Watchlist vuota."
    else:
        body = "\n".join(fmt_ticket_line(it) for it in items)
    new_id = send_telegram(body)
    if isinstance(new_id, int):
        state["summary_message_id"] = new_id
        save_state(state_path, state)


def send_watchlist_summary(
    added: list[str],
    removed: list[str],
    watchlist_path: Path,
    state_path: Path,
) -> None:
    if not added and not removed:
        return
    items = load_watchlist(watchlist_path)
    lines = [f"✅ {ticker} aggiunto/aggiornato" for ticker in added]
    for item in removed:
        if "scartato" in item:
            lines.append(f"❌ {item}")
        else:
            lines.append(f"❌ {item} rimosso")
    lines.append("")
    if not items:
        lines.append("Watchlist vuota.")
    else:
        lines.extend(fmt_ticket_line(it) for it in items)
    state = load_state(state_path)
    old_id = state.get("summary_message_id")
    if isinstance(old_id, int):
        delete_telegram_message(old_id)
    new_id = send_telegram("\n".join(lines))
    if isinstance(new_id, int):
        state["summary_message_id"] = new_id
        save_state(state_path, state)


def fmt_level(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}"


def fmt_ingresso(item: dict[str, Any]) -> str:
    lo, hi = item.get("ingresso_low"), item.get("ingresso_high")
    if lo is None:
        return "—"
    if hi is None or hi == lo:
        return fmt_level(lo)
    return f"{fmt_level(lo)}-{fmt_level(hi)}"


def fmt_ticket_line(item: dict[str, Any]) -> str:
    motivo = (item.get("motivo") or "").strip()
    extra = f" {motivo}" if motivo else ""
    return (
        f"{item['ticker']} "
        f"i {fmt_ingresso(item)} "
        f"s {fmt_level(item.get('stop'))} "
        f"t {fmt_level(item.get('target'))}"
        f"{extra}"
    )


def fmt_ticket_line_no_motivo(item: dict[str, Any]) -> str:
    tf = item.get("tf") or "—"
    return (
        f"{item['ticker']:<6} {tf:<9}  "
        f"ing {fmt_ingresso(item):<12} "
        f"stop {fmt_level(item.get('stop')):<8} "
        f"tgt {fmt_level(item.get('target'))}"
    )


def load_dotenv(path: Path | None = None) -> None:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    else:
        candidates.append(Path(".env"))
        here = Path(__file__).resolve().with_name(".env")
        if here not in candidates:
            candidates.append(here)
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            raw = env_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip().strip("'").strip('"')
        break


def rome_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(WATCH_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(WATCH_TZ)


def in_watch_window(now: datetime | None = None) -> bool:
    """True dalle 15:00 alle 22:59 (Europe/Rome), estate e inverno."""
    local = rome_now(now)
    return WATCH_HOUR_START <= local.hour <= WATCH_HOUR_END


def alert_day(now: datetime | None = None) -> str:
    """Data di calendario YYYY-MM-DD in Europe/Rome."""
    return rome_now(now).date().isoformat()


def telegram_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def userbot_credentials() -> tuple[int, str, str] | None:
    api_id_raw = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    session = os.environ.get("TELEGRAM_USER_SESSION", "").strip()
    if not api_id_raw or not api_hash or not session:
        return None
    try:
        api_id = int(api_id_raw)
    except ValueError:
        return None
    return api_id, api_hash, session


def telegram_chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID).strip() or DEFAULT_CHAT_ID


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def fired_key_str(key: tuple[str, str, str]) -> str:
    return "|".join(key)


def load_fired(state: dict[str, Any]) -> dict[tuple[str, str, str], str | None]:
    raw = state.get("fired")
    if not isinstance(raw, dict):
        return {}
    out: dict[tuple[str, str, str], str | None] = {}
    today = alert_day()
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        parts = k.split("|")
        if len(parts) != 3:
            continue
        day: str | None
        if isinstance(v, str) and v.strip():
            day = v.strip()
        elif v is True:
            day = today
        else:
            continue
        out[(parts[0], parts[1], parts[2])] = day
    return out


def dump_fired(fired: dict[tuple[str, str, str], str | None]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, day in fired.items():
        if isinstance(day, str) and day.strip():
            out[fired_key_str(key)] = day.strip()
    return out


def persist_fired(
    state_path: Path, fired: dict[tuple[str, str, str], str | None]
) -> None:
    state = load_state(state_path)
    state["fired"] = dump_fired(fired)
    save_state(state_path, state)


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def update_payload(update: dict[str, Any]) -> dict[str, Any] | None:
    for key in UPDATE_KEYS:
        msg = update.get(key)
        if isinstance(msg, dict):
            return msg
    return None


def payload_text(msg: dict[str, Any]) -> str:
    caption = msg.get("caption")
    text = msg.get("text")
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def chat_matches(chat: Any, want: str) -> bool:
    if not isinstance(chat, dict):
        return False
    return str(chat.get("id", "")).strip() == str(want).strip()


def apply_telegram_list(text: str, watchlist_path: Path, state_path: Path) -> bool:
    if not LIST_RE.match(text.strip()):
        return False
    refresh_watchlist_summary(watchlist_path, state_path)
    return True


def ibkr_get(path: str) -> dict[str, Any] | list[Any] | None:
    try:
        import requests
    except ImportError:
        return None
    try:
        response = requests.get(IBKR_BASE_URL + path, verify=False, timeout=10)
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return data
    return None


def ibkr_post(path: str, body: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
    try:
        import requests
    except ImportError:
        return None
    try:
        response = requests.post(
            IBKR_BASE_URL + path, json=body, verify=False, timeout=15
        )
    except Exception:
        return None
    if response.status_code not in (200, 201):
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return data
    return None


def ibkr_delete(path: str) -> dict[str, Any] | list[Any] | None:
    try:
        import requests
    except ImportError:
        return None
    try:
        response = requests.delete(
            IBKR_BASE_URL + path, verify=False, timeout=15
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return data
    return None


def ibkr_get_account_id() -> str | None:
    global _ACCOUNT_ID_CACHE
    if _ACCOUNT_ID_CACHE:
        return _ACCOUNT_ID_CACHE
    accounts = ibkr_get("/v1/api/portfolio/accounts")
    if not isinstance(accounts, list) or not accounts:
        return None
    first = accounts[0]
    if not isinstance(first, dict) or not first.get("accountId"):
        return None
    _ACCOUNT_ID_CACHE = str(first["accountId"])
    return _ACCOUNT_ID_CACHE


def ibkr_lookup_conid(ticker: str) -> str | None:
    key = ticker.strip().upper()
    if not key:
        return None
    cached = _CONID_CACHE.get(key)
    if cached:
        return cached
    data = ibkr_get(f"/v1/api/trsrv/stocks?symbols={key}")
    if not data:
        return None
    try:
        if not isinstance(data, dict):
            return None
        rows = data.get(key)
        if not isinstance(rows, list) or not rows:
            rows = next(
                (v for k, v in data.items() if str(k).upper() == key),
                None,
            )
        if not isinstance(rows, list) or not rows:
            return None
        fallback: Any = None
        us_conid: Any = None
        for company in rows:
            if not isinstance(company, dict):
                continue
            contracts = company.get("contracts")
            if not isinstance(contracts, list):
                continue
            for contract in contracts:
                if not isinstance(contract, dict):
                    continue
                conid = contract.get("conid")
                if conid is None:
                    continue
                if fallback is None:
                    fallback = conid
                if us_conid is None and contract.get("isUS") is True:
                    us_conid = conid
        chosen = us_conid if us_conid is not None else fallback
        if chosen is None:
            return None
        out = str(chosen)
        _CONID_CACHE[key] = out
        return out
    except Exception:
        return None


def ibkr_get_price(ticker: str) -> float | None:
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return None
    path = f"/v1/api/iserver/marketdata/snapshot?conids={conid}&fields=31"
    ibkr_get(path)
    time.sleep(1)
    snap = ibkr_get(path)
    if not isinstance(snap, list) or not snap:
        return None
    first = snap[0]
    if not isinstance(first, dict):
        return None
    raw = first.get("31")
    if raw is None:
        return None
    match = _IBKR_PRICE_RE.search(str(raw).replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _send_replacing_message(
    state_path: Path,
    id_key: str,
    text: str,
    ttl: timedelta | None = None,
) -> None:
    state = load_state(state_path)
    old_id = state.get(id_key)
    if old_id is not None:
        delete_telegram_message(old_id)
    new_id = send_telegram(text)
    if isinstance(new_id, int):
        state[id_key] = new_id
    if ttl is not None:
        messages = [
            entry
            for entry in (state.get("order_messages") or [])
            if not (isinstance(entry, dict) and entry.get("message_id") == old_id)
        ]
        if isinstance(new_id, int):
            messages.append(
                {
                    "message_id": new_id,
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "ttl_seconds": int(ttl.total_seconds()),
                }
            )
        state["order_messages"] = messages
    save_state(state_path, state)


def apply_telegram_balance(text: str, state_path: Path) -> bool:
    if not BALANCE_RE.match(text.strip()):
        return False
    accounts = ibkr_get("/v1/api/portfolio/accounts")
    if not isinstance(accounts, list) or not accounts:
        _send_replacing_message(
            state_path,
            "balance_message_id",
            "⚠️ Impossibile leggere il conto IBKR al momento.",
        )
        return True
    first = accounts[0]
    if not isinstance(first, dict) or not first.get("accountId"):
        _send_replacing_message(
            state_path,
            "balance_message_id",
            "⚠️ Impossibile leggere il conto IBKR al momento.",
        )
        return True
    account_id = first["accountId"]
    ledger = ibkr_get(f"/v1/api/portfolio/{account_id}/ledger")
    if not isinstance(ledger, dict):
        _send_replacing_message(
            state_path,
            "balance_message_id",
            "⚠️ Impossibile leggere il saldo al momento.",
        )
        return True
    raw = ledger.get("BASE")
    if not isinstance(raw, dict):
        raw = next(iter(ledger.values()), None)
    if not isinstance(raw, dict):
        _send_replacing_message(
            state_path,
            "balance_message_id",
            "⚠️ Impossibile leggere il saldo al momento.",
        )
        return True
    cashbalance = raw.get("cashbalance", "—")
    netliquidationvalue = raw.get("netliquidationvalue", "—")
    currency = raw.get("currency", "")
    _send_replacing_message(
        state_path,
        "balance_message_id",
        f"💰 Conto {account_id}\n"
        f"Contanti: {cashbalance} {currency}\n"
        f"Valore netto: {netliquidationvalue} {currency}",
    )
    return True


def apply_telegram_price(text: str, state_path: Path) -> bool:
    m = PRICE_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    price = ibkr_get_price(ticker)
    if price is None:
        _send_replacing_message(
            state_path,
            "price_message_id",
            f"⚠️ Prezzo IBKR non disponibile per {ticker}.",
        )
    else:
        _send_replacing_message(
            state_path,
            "price_message_id",
            f"📈 {ticker} (IBKR): {price:.2f}",
        )
    return True


def ensure_reply_suppression() -> None:
    try:
        ibkr_post(
            "/v1/api/iserver/questions/suppress",
            {"messageIds": ["o10151", "o10153", "o10164", "o10223", "o354"]},
        )
    except Exception as exc:
        print(f"IBKR suppress: {exc}", file=sys.stderr)


def _confirm_order_replies(
    result: dict[str, Any] | list[Any] | None,
) -> dict[str, Any] | None:
    for _ in range(5):
        if isinstance(result, dict):
            result = [result]
        if not isinstance(result, list) or not result:
            return None
        first = result[0]
        if not isinstance(first, dict):
            return None
        if first.get("id") is not None and first.get("message") is not None:
            result = ibkr_post(
                f"/v1/api/iserver/reply/{first['id']}",
                {"confirmed": True},
            )
            continue
        if first.get("order_id") is not None or first.get("orderId") is not None:
            return first
        return None
    return None


def ibkr_place_order(
    ticker: str, quantity: int, side: str, price: float | None
) -> str:
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR."
    try:
        conid_int = int(conid)
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    auto_price = price is None
    if price is None:
        spot = ibkr_get_price(ticker)
        if spot is None:
            return f"⚠️ Impossibile determinare un prezzo per {ticker}."
        if side == "BUY":
            price = spot * 1.005
        else:
            price = spot * 0.995
        price = round(price, 2)
    order: dict[str, Any] = {
        "conid": conid_int,
        "orderType": "LMT",
        "side": side,
        "quantity": quantity,
        "price": price,
        "tif": "DAY",
        "outsideRTH": True,
    }
    result: dict[str, Any] | list[Any] | None = ibkr_post(
        f"/v1/api/iserver/account/{account_id}/orders",
        {"orders": [order]},
    )
    if result is None:
        return "⚠️ Errore nell'invio dell'ordine."
    confirmed = _confirm_order_replies(result)
    if confirmed is not None:
        if auto_price:
            return (
                f"✅ Ordine {side} {quantity} {ticker} @ {price:.2f} "
                f"(auto, ~mercato) inviato."
            )
        return f"✅ Ordine {side} {quantity} {ticker} @ {price} inviato."
    return (
        f"⚠️ Ordine non confermato per {ticker}, controlla manualmente su IBKR."
    )


def ibkr_place_cash_order(ticker: str, side: str, cash_amount: float) -> str:
    ticker = ticker.strip().upper()
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR."
    try:
        conid_int = int(conid)
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    corpo = {
        "conid": conid_int,
        "orderType": "MKT",
        "side": side,
        "cashQty": cash_amount,
        "tif": "DAY",
    }
    result = ibkr_post(
        f"/v1/api/iserver/account/{account_id}/orders",
        {"orders": [corpo]},
    )
    if result is None:
        return "⚠️ Errore nell'invio dell'ordine."
    confirmed = _confirm_order_replies(result)
    if confirmed is None:
        return (
            f"⚠️ Ordine non confermato per {ticker}, controlla manualmente su IBKR."
        )
    return (
        f"✅ Ordine {side} {ticker} ${cash_amount:.2f} (MKT, cashQty) inviato."
    )


def apply_telegram_buy(text: str, state_path: Path) -> bool:
    m = BUY_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    quantity = int(m.group(2))
    raw_price = m.group(3)
    price = float(raw_price) if raw_price is not None else None
    _send_order_message(state_path, ibkr_place_order(ticker, quantity, "BUY", price))
    return True


def apply_telegram_sell(text: str, state_path: Path) -> bool:
    m = SELL_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    quantity = int(m.group(2))
    raw_price = m.group(3)
    price = float(raw_price) if raw_price is not None else None
    _send_order_message(state_path, ibkr_place_order(ticker, quantity, "SELL", price))
    return True


def ibkr_place_trail(ticker: str, quantity: int, trailing_amount: float) -> str:
    ticker = ticker.strip().upper()
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR."
    try:
        conid_int = int(conid)
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    prezzo_attuale = ibkr_get_price(ticker)
    if prezzo_attuale is None:
        return f"⚠️ Impossibile determinare un prezzo per {ticker}."
    corpo = {
        "conid": conid_int,
        "orderType": "TRAIL",
        "side": "SELL",
        "quantity": quantity,
        "price": prezzo_attuale,
        "trailingAmt": trailing_amount,
        "trailingType": "amt",
        "tif": "DAY",
    }
    result = ibkr_post(
        f"/v1/api/iserver/account/{account_id}/orders",
        {"orders": [corpo]},
    )
    if result is None:
        return "⚠️ Errore nell'invio dell'ordine."
    confirmed = _confirm_order_replies(result)
    if confirmed is None:
        return (
            f"⚠️ Ordine non confermato per {ticker}, controlla manualmente su IBKR."
        )
    return (
        f"✅ Ordine SELL {quantity} {ticker} TRAIL {trailing_amount:g} inviato."
    )


def apply_telegram_trail(text: str, state_path: Path) -> bool:
    m = TRAIL_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    quantity = int(m.group(2))
    trailing_amount = float(m.group(3))
    _send_order_message(
        state_path, ibkr_place_trail(ticker, quantity, trailing_amount)
    )
    return True


def _new_pending_flow(kind: str) -> dict[str, Any]:
    return {
        "type": kind,
        "step": "ticker",
        "ticker": None,
        "size_type": None,
        "quantity": None,
        "price_type": None,
    }


def _pending_flow(state: dict[str, Any]) -> dict[str, Any] | None:
    raw = state.get("pending_flow")
    return raw if isinstance(raw, dict) else None


def _save_pending_flow(state_path: Path, flow: dict[str, Any] | None) -> None:
    state = load_state(state_path)
    state["pending_flow"] = flow
    save_state(state_path, state)


def apply_telegram_buy_flow_start(text: str, state_path: Path) -> bool:
    if not BUY_FLOW_START_RE.match(text.strip()):
        return False
    _save_pending_flow(state_path, _new_pending_flow("BUY"))
    _send_flow_message(state_path, "Quale ticker vuoi comprare?")
    return True


def _held_position_tickers(positions: list[Any] | None) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        try:
            qty = float(pos.get("position") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty == 0:
            continue
        ticker = str(pos.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def apply_telegram_sell_flow_start(text: str, state_path: Path) -> bool:
    if not SELL_FLOW_START_RE.match(text.strip()):
        return False
    tickers = _held_position_tickers(ibkr_get_positions())
    if not tickers:
        _save_pending_flow(state_path, None)
        _send_flow_message(state_path, "📭 Nessuna posizione aperta da vendere.")
        return True
    flow = _new_pending_flow("SELL")
    flow["step"] = "size_type"
    flow["ticker"] = None
    _save_pending_flow(state_path, flow)
    _send_flow_message(
        state_path,
        "Quale ticker vuoi vendere?",
        [(ticker, f"sellticker:{ticker}") for ticker in tickers],
    )
    return True


def _parse_flow_number(text: str) -> float | None:
    try:
        value = parse_num(text.strip())
    except ValueError:
        return None
    if value <= 0:
        return None
    return value


def _size_type_buttons(flow: dict[str, Any]) -> list[tuple[str, str]]:
    buttons = [("Azioni", "size:shares"), ("Dollari", "size:dollars")]
    if str(flow.get("type") or "") == "SELL":
        buttons.append(("Vendi tutto", "size:all"))
    return buttons


def _flow_share_quantity(flow: dict[str, Any]) -> tuple[int | None, str | None]:
    ticker = str(flow.get("ticker") or "").strip().upper()
    size_type = flow.get("size_type")
    try:
        raw = float(flow.get("quantity"))
    except (TypeError, ValueError):
        return None, "⚠️ Ordine incompleto."
    if size_type == "shares":
        return int(raw), None
    if size_type == "dollars":
        spot = ibkr_get_price(ticker)
        if spot is None or spot <= 0:
            return None, f"⚠️ Impossibile determinare un prezzo per {ticker}."
        qty = int(raw / spot)
        if qty == 0:
            return (
                None,
                f"⚠️ {raw}$ non bastano per comprare nemmeno 1 azione di "
                f"{ticker} (costa {spot:.2f}$).",
            )
        return qty, None
    return None, "⚠️ Ordine incompleto."


def _emit_flow_result(result: str, state_path: Path) -> str:
    _send_flow_message(state_path, result)
    return result


def _execute_flow_order(flow: dict[str, Any], state_path: Path) -> str:
    ticker = str(flow.get("ticker") or "").strip().upper()
    price_type = flow.get("price_type")
    side = str(flow.get("type") or "BUY")
    quantity, err = _flow_share_quantity(flow)
    if err is not None or quantity is None:
        return _emit_flow_result(err or "⚠️ Ordine incompleto.", state_path)
    price = None
    if price_type == "limit":
        try:
            price = float(flow.get("price"))
        except (TypeError, ValueError):
            return _emit_flow_result("⚠️ Prezzo non valido, riprova.", state_path)
    result = ibkr_place_order(ticker, quantity, side, price)
    return _emit_flow_result(result, state_path)


def process_pending_flow_text(text: str, state_path: Path) -> bool:
    state = load_state(state_path)
    flow = _pending_flow(state)
    if flow is None:
        return False
    step = flow.get("step")
    stripped = text.strip()
    if step == "ticker":
        if str(flow.get("type") or "") == "SELL":
            return False
        match = FLOW_TICKER_RE.match(stripped)
        ticker = match.group(1).upper() if match else ""
        if not ticker or not is_valid_symbol(ticker):
            _send_flow_message(state_path, "⚠️ Ticker non valido, riprova.")
            return True
        flow["ticker"] = ticker
        flow["step"] = "size_type"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path, "Azioni o Dollari?", _size_type_buttons(flow)
        )
        return True
    if step == "quantity":
        value = _parse_flow_number(stripped)
        if value is None:
            _send_flow_message(state_path, "⚠️ Numero non valido, riprova.")
            return True
        flow["quantity"] = value
        flow["step"] = "price_type"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "A mercato o a limite?",
            [("A mercato", "price:market"), ("A limite", "price:limit")],
        )
        return True
    if step == "price":
        value = _parse_flow_number(stripped)
        if value is None:
            _send_flow_message(state_path, "⚠️ Prezzo non valido, riprova.")
            return True
        flow["price"] = value
        _save_pending_flow(state_path, flow)
        _execute_flow_order(flow, state_path)
        _save_pending_flow(state_path, None)
        return True
    return False


def process_callback_query(
    callback_data: str,
    chat_id: Any,
    callback_query_id: str,
    state_path: Path,
) -> dict[str, Any] | None:
    """Aggiorna pending_flow. Non chiama IBKR.

    Ritorna None se non serve altro, altrimenti un'azione da eseguire
    fuori dal lock:

    - {"action": "execute_order", "flow": {...}} → _execute_flow_order
    - {"action": "sell_all", "ticker": str, "price": float|None} → ibkr_sell_all
    """
    answer_callback_query(callback_query_id)
    flow = _pending_flow(load_state(state_path))
    if flow is None:
        return None
    data = callback_data.strip()
    step = flow.get("step")
    if data.startswith("sellticker:"):
        if str(flow.get("type") or "") != "SELL":
            return None
        ticker = data.split(":", 1)[1].strip().upper()
        if not ticker:
            return None
        flow["ticker"] = ticker
        flow["step"] = "size_type"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Azioni o Dollari?",
            [
                ("Azioni", "size:shares"),
                ("Dollari", "size:dollars"),
                ("Vendi tutto", "size:all"),
            ],
        )
        return None
    if data.startswith("size:") and step == "size_type":
        choice = data.split(":", 1)[1]
        if choice == "all":
            if str(flow.get("type") or "") != "SELL":
                return None
            ticker = str(flow.get("ticker") or "").strip().upper()
            if not ticker:
                return None
            _save_pending_flow(state_path, None)
            return {"action": "sell_all", "ticker": ticker, "price": None}
        if choice not in {"shares", "dollars"}:
            return None
        flow["size_type"] = choice
        flow["step"] = "quantity"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quante azioni?" if choice == "shares" else "Quanti dollari?",
        )
        return None
    if data.startswith("price:") and step == "price_type":
        choice = data.split(":", 1)[1]
        if choice not in {"market", "limit"}:
            return None
        flow["price_type"] = choice
        if choice == "market":
            snapshot = dict(flow)
            _save_pending_flow(state_path, None)
            return {"action": "execute_order", "flow": snapshot}
        flow["step"] = "price"
        _save_pending_flow(state_path, flow)
        _send_flow_message(state_path, "A che prezzo?")
        return None
    return None


def ibkr_sell_all(ticker: str, price: float | None) -> str:
    ticker = ticker.strip().upper()
    positions = ibkr_get_positions()
    if not positions:
        return f"⚠️ Nessuna posizione aperta per {ticker}."
    found: dict[str, Any] | None = None
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        if str(pos.get("ticker") or "").upper() == ticker:
            found = pos
            break
    if found is None:
        return f"⚠️ Nessuna posizione aperta per {ticker}."
    try:
        qty = abs(float(found.get("position") or 0))
    except (TypeError, ValueError):
        qty = 0.0
    quantity = math.floor(qty)
    if quantity < 1:
        return f"⚠️ Nessuna posizione aperta per {ticker}."
    if price is None:
        spot = ibkr_get_price(ticker)
        if spot is None:
            return "⚠️ Impossibile determinare un prezzo per la vendita."
        price = round(spot * 0.995, 2)
    return ibkr_place_order(ticker, quantity, "SELL", price)


_IBKR_DEAD_ORDER_STATUSES = {
    "filled",
    "cancelled",
    "canceled",
    "inactive",
    "rejected",
    "expired",
    "pendingcancel",
    "apicancelled",
}
_IBKR_LIMIT_ORDER_TYPES = {"LMT", "LIMIT"}
_IBKR_TRAIL_ORDER_TYPES = {
    "TRAIL",
    "TRAILING_STOP",
    "TRAILING STOP",
    "STP TRAIL",
    "STPTRL",
}
_IBKR_NON_LIMIT_ORDER_TYPES = _IBKR_TRAIL_ORDER_TYPES | {
    "MKT",
    "MARKET",
    "STP",
    "STOP",
    "STP LMT",
    "STOP LIMIT",
}
_IBKR_WORKING_ORDER_STATUSES = {"submitted", "presubmitted"}


def _ibkr_order_status(order: dict[str, Any]) -> str:
    return str(order.get("status") or "").strip().lower()


def _ibkr_order_type(order: dict[str, Any]) -> str:
    return str(order.get("orderType") or "").strip().upper()


def _ibkr_order_id(order: dict[str, Any]) -> Any | None:
    raw = order.get("orderId")
    if raw is None or raw == "":
        return None
    try:
        if int(float(str(raw).strip())) == 0:
            return None
    except (TypeError, ValueError):
        return raw
    return raw


def _ibkr_is_dead_order(order: dict[str, Any]) -> bool:
    return _ibkr_order_status(order) in _IBKR_DEAD_ORDER_STATUSES


def _ibkr_is_limit_order(order: dict[str, Any]) -> bool:
    typ = _ibkr_order_type(order)
    if typ in _IBKR_LIMIT_ORDER_TYPES:
        return True
    if typ in _IBKR_NON_LIMIT_ORDER_TYPES:
        return False
    if typ:
        return False
    return order.get("price") not in (None, "")


def _ibkr_delete_orders(account_id: str, order_ids: list[Any]) -> int:
    cancelled = 0
    for order_id in order_ids:
        result = ibkr_delete(
            f"/v1/api/iserver/account/{account_id}/order/{order_id}"
        )
        if result is not None:
            cancelled += 1
    return cancelled


def ibkr_cancel_order(ticker: str) -> str:
    ticker = ticker.strip().upper()
    orders = ibkr_get_active_orders()
    if orders is None:
        return "⚠️ Impossibile leggere gli ordini aperti."
    open_ids: list[Any] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("ticker") or "").upper() != ticker:
            continue
        order_id = _ibkr_order_id(order)
        if order_id is None:
            continue
        open_ids.append(order_id)
    if not open_ids:
        return f"⚠️ Nessun ordine aperto trovato per {ticker}."
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR."
    cancelled = _ibkr_delete_orders(account_id, open_ids)
    if cancelled == 0:
        return f"⚠️ Errore nell'annullamento dell'ordine per {ticker}."
    if cancelled == 1:
        return f"🚫 Ordine per {ticker} annullato."
    return f"🚫 {cancelled} ordini per {ticker} annullati."


def _ibkr_replace_limit_order(
    account_id: str, order: dict[str, Any], new_price: float, ticker: str
) -> str | None:
    try:
        conid_int = int(order.get("conid"))
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR."
    side = order.get("side") or "SELL"
    raw_qty = order.get("remainingQuantity", order.get("totalSize"))
    try:
        quantity = int(float(raw_qty))
    except (TypeError, ValueError):
        return (
            f"⚠️ Modifica non confermata per {ticker}, controlla manualmente su IBKR."
        )
    if quantity < 1:
        return f"⚠️ Nessun ordine aperto trovato per {ticker}."
    order_id = order["orderId"]
    result = ibkr_post(
        f"/v1/api/iserver/account/{account_id}/order/{order_id}",
        {
            "conid": conid_int,
            "orderType": "LMT",
            "side": side,
            "quantity": quantity,
            "price": new_price,
            "tif": "DAY",
        },
    )
    if result is None or _confirm_order_replies(result) is None:
        return (
            f"⚠️ Modifica non confermata per {ticker}, controlla manualmente su IBKR."
        )
    return None


def ibkr_modify_order(ticker: str, new_price: float) -> str:
    ticker = ticker.strip().upper()
    orders = ibkr_get_active_orders()
    if orders is None:
        return "⚠️ Impossibile leggere gli ordini aperti."
    ticker_orders: list[dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("ticker") or "").upper() != ticker:
            continue
        if _ibkr_order_id(order) is None:
            continue
        ticker_orders.append(order)
    if not ticker_orders:
        return f"⚠️ Nessun ordine aperto trovato per {ticker}."
    limits = [order for order in ticker_orders if _ibkr_is_limit_order(order)]
    if not limits:
        shown = _ibkr_order_type(ticker_orders[0]) or "?"
        return (
            f"⚠️ Impossibile modificare un ordine di tipo {shown}, "
            "solo ordini a limite."
        )
    working = [
        order
        for order in limits
        if _ibkr_order_status(order) in _IBKR_WORKING_ORDER_STATUSES
    ]
    targets = working or limits
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR."
    updated = 0
    updated_ids: set[str] = set()
    last_error: str | None = None
    for order in targets:
        error = _ibkr_replace_limit_order(account_id, order, new_price, ticker)
        if error is None:
            updated += 1
            order_id = _ibkr_order_id(order)
            if order_id is not None:
                updated_ids.add(str(order_id))
        else:
            last_error = error
    extras: list[Any] = []
    for order in limits:
        order_id = _ibkr_order_id(order)
        if order_id is None:
            continue
        if str(order_id) in updated_ids:
            continue
        extras.append(order_id)
    if extras:
        _ibkr_delete_orders(account_id, extras)
    if updated == 0:
        return last_error or (
            f"⚠️ Modifica non confermata per {ticker}, controlla manualmente su IBKR."
        )
    if updated == 1:
        return f"✅ Ordine {ticker} modificato a {new_price:.2f}."
    return f"✅ {updated} ordini {ticker} modificati a {new_price:.2f}."


def apply_telegram_modify_order(text: str, state_path: Path) -> bool:
    m = MODIFY_ORDER_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    new_price = float(m.group(2))
    _send_order_message(state_path, ibkr_modify_order(ticker, new_price))
    return True


def apply_telegram_cancel_order(text: str, state_path: Path) -> bool:
    m = CANCEL_ORDER_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    _send_order_message(state_path, ibkr_cancel_order(ticker))
    return True


def _ibkr_positions_need_retry(data: Any) -> bool:
    if not data:
        return True
    if not isinstance(data, list) or not data:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return True
    ticker = first.get("ticker")
    return not isinstance(ticker, str) or not ticker.strip()


def ibkr_get_positions() -> list[Any] | None:
    account_id = ibkr_get_account_id()
    if not account_id:
        return None
    path = f"/v1/api/portfolio/{account_id}/positions/0"
    data = ibkr_get(path)
    if _ibkr_positions_need_retry(data):
        time.sleep(1)
        data = ibkr_get(path)
    if data is None:
        return None
    if isinstance(data, dict):
        data = data.get("positions")
    if not isinstance(data, list):
        return None
    return data


def _fmt_position_line(pos: dict[str, Any]) -> str:
    ticker = pos.get("ticker") or "?"
    qty = pos.get("position", 0)
    try:
        avg = float(pos.get("avgCost") or 0)
    except (TypeError, ValueError):
        avg = 0.0
    try:
        mkt = float(pos.get("mktValue") or 0)
    except (TypeError, ValueError):
        mkt = 0.0
    currency = pos.get("currency", "") or ""
    try:
        pnl = float(pos.get("unrealizedPnl") or 0)
    except (TypeError, ValueError):
        pnl = 0.0
    return (
        f"{ticker}: {qty} @ {avg:.2f} "
        f"(valore: {mkt:.2f} {currency}, P&L: {pnl:+.2f})"
    )


def apply_telegram_positions(text: str, state_path: Path) -> bool:
    if not POSITIONS_RE.match(text.strip()):
        return False
    positions = ibkr_get_positions()
    if positions is None:
        _send_replacing_message(
            state_path,
            "positions_message_id",
            "⚠️ Impossibile leggere le posizioni al momento.",
        )
        return True
    lines = ["📊 Posizioni aperte:", ""]
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        try:
            qty = float(pos.get("position") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty == 0:
            continue
        lines.append(_fmt_position_line(pos))
    if len(lines) <= 2:
        _send_replacing_message(
            state_path,
            "positions_message_id",
            "📭 Nessuna posizione aperta.",
        )
        return True
    _send_replacing_message(state_path, "positions_message_id", "\n".join(lines))
    return True


def ibkr_get_active_orders() -> list[Any] | None:
    path = "/v1/api/iserver/account/orders"
    ibkr_get(path)
    time.sleep(1)
    data = ibkr_get(path)
    if data is None:
        return None
    if not isinstance(data, dict):
        return None
    orders = data.get("orders")
    if not isinstance(orders, list):
        return []
    active: list[Any] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if _ibkr_is_dead_order(order):
            continue
        if _ibkr_order_id(order) is None:
            continue
        active.append(order)
    return active


def _fmt_order_line(order: dict[str, Any]) -> str:
    qty = order.get("remainingQuantity", order.get("totalSize", "?"))
    price = order.get("price") or order.get("avgPrice")
    if price in (None, ""):
        order_type = _ibkr_order_type(order)
        if order_type in _IBKR_TRAIL_ORDER_TYPES:
            trail = order.get("trailingAmt") or order.get("auxPrice")
            price = f"TRAIL {trail}" if trail not in (None, "") else "TRAIL"
        else:
            price = order_type or "MKT"
    return (
        f"{order.get('ticker', '?')} {order.get('side', '?')} "
        f"{qty} @ {price} · {order.get('status', '?')}"
    )


def apply_telegram_orders(text: str, state_path: Path) -> bool:
    if not ORDERS_RE.match(text.strip()):
        return False
    orders = ibkr_get_active_orders()
    if orders is None:
        body = "⚠️ Impossibile leggere gli ordini al momento."
    elif not orders:
        body = "📭 Nessun ordine attivo."
    else:
        lines = [_fmt_order_line(o) for o in orders if isinstance(o, dict)]
        if not lines:
            body = "📭 Nessun ordine attivo."
        else:
            body = "📋 Ordini attivi:\n\n" + "\n".join(lines)
    _send_replacing_message(
        state_path, "orders_message_id", body, ttl=ORDER_MESSAGE_TTL
    )
    return True


def ibkr_get_trades() -> list[Any] | None:
    data = ibkr_get("/v1/api/iserver/account/trades")
    if data is None:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        trades = data.get("trades")
        if isinstance(trades, list):
            return trades
        if any(
            key in data
            for key in ("symbol", "ticker", "trade_time", "trade_time_r", "side")
        ):
            return [data]
        return None
    return None


def _trade_timestamp(trade: dict[str, Any]) -> float:
    raw_r = trade.get("trade_time_r")
    if raw_r is not None:
        try:
            value = float(raw_r)
            if value > 1e12:
                value /= 1000.0
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    raw = trade.get("trade_time")
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        for fmt in (
            "%Y%m%d-%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
        try:
            iso = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    return 0.0


def _is_cash_fx_trade(trade: dict[str, Any]) -> bool:
    sec_type = str(trade.get("secType") or "").strip().upper()
    if sec_type == "CASH":
        return True
    symbol = str(trade.get("symbol") or trade.get("ticker") or "").strip().upper()
    return symbol == "EUR"


def _trade_symbol(trade: dict[str, Any]) -> str:
    return str(trade.get("symbol") or trade.get("ticker") or "").strip().upper()


def _trade_side(raw: Any) -> str:
    side = str(raw or "").strip().upper()
    if side in {"B", "BUY", "BOT"} or side.startswith("B"):
        return "B"
    if side in {"S", "SELL", "SLD"} or side.startswith("S"):
        return "S"
    return side


def _trade_number(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        if isinstance(raw, (int, float)):
            return float(raw)
        return parse_num(str(raw))
    except (TypeError, ValueError):
        return None


def _average_cost_pnls(trades: list[dict[str, Any]]) -> list[float | None]:
    avg_cost: dict[str, tuple[float, float]] = {}
    pnls: list[float | None] = []
    for trade in trades:
        symbol = _trade_symbol(trade)
        side = _trade_side(trade.get("side"))
        size = _trade_number(trade.get("size", trade.get("quantity")))
        price = _trade_number(trade.get("price"))
        commission = _trade_number(trade.get("commission"))
        if commission is None:
            commission = 0.0
        pnl: float | None = None
        if not symbol or size is None or price is None or size <= 0:
            pnls.append(None)
            continue
        if side == "B":
            old_qty, old_cost = avg_cost.get(symbol, (0.0, 0.0))
            new_qty = old_qty + size
            new_cost = (
                ((old_qty * old_cost) + (size * price + commission)) / new_qty
                if new_qty > 0
                else 0.0
            )
            avg_cost[symbol] = (new_qty, new_cost)
        elif side == "S":
            old_qty, avg = avg_cost.get(symbol, (0.0, 0.0))
            if avg != 0.0:
                pnl = (price - avg) * size - commission
            avg_cost[symbol] = (max(0.0, old_qty - size), avg)
        pnls.append(pnl)
    return pnls


def apply_telegram_history(text: str) -> bool:
    match = HISTORY_RE.match(text.strip())
    if not match:
        return False
    days = int(match.group(1))
    trades = ibkr_get_trades()
    if trades is None:
        send_telegram("⚠️ Impossibile leggere lo storico ordini al momento.")
        return True
    now = time.time()
    soglia = now - (days * 86400)
    usable: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict) or _is_cash_fx_trade(trade):
            continue
        if _trade_timestamp(trade) == 0.0:
            continue
        usable.append(trade)
    usable.sort(key=_trade_timestamp)
    pnls = _average_cost_pnls(usable)
    window: list[tuple[dict[str, Any], float | None]] = [
        (trade, pnl)
        for trade, pnl in zip(usable, pnls)
        if _trade_timestamp(trade) >= soglia
    ]
    if not window:
        send_telegram(f"📭 Nessun ordine eseguito negli ultimi {days} giorni.")
        return True
    lines: list[str] = []
    totale = 0.0
    fee_ok = False
    totale_pnl = 0.0
    pnl_ok = False
    for trade, pnl in window:
        size = trade.get("size", trade.get("quantity", "?"))
        symbol = trade.get("symbol", trade.get("ticker", "?"))
        line = (
            f"{trade.get('side', '?')} {size} {symbol} @ "
            f"{trade.get('price', '?')} · fee: {trade.get('commission', 'n/d')}"
        )
        if _trade_side(trade.get("side")) == "S" and pnl is not None:
            line += f" · PNL: {pnl:+.2f}"
            totale_pnl += pnl
            pnl_ok = True
        lines.append(line)
        try:
            totale += float(trade.get("commission"))
            fee_ok = True
        except (TypeError, ValueError):
            pass
    body = f"📜 Ordini eseguiti (ultimi {days} giorni):\n\n" + "\n".join(lines)
    if fee_ok:
        body += f"\nTotale fee: {totale:.2f}"
    if pnl_ok:
        body += f"\nTotale PNL: {totale_pnl:+.2f}"
    send_telegram(body)
    return True


def _commission_from_trades(order: dict[str, Any], order_id: str) -> str:
    try:
        trades_data = ibkr_get("/v1/api/iserver/account/trades")
        trades: Any = trades_data
        if isinstance(trades_data, dict):
            trades = trades_data.get("trades") or trades_data.get("orders") or []
        if not isinstance(trades, list):
            return "n/d"
        order_conid = order.get("conid")
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            trade_oid = str(trade.get("order_id") or trade.get("orderId") or "")
            same_order = trade_oid == order_id
            same_conid = (
                order_conid is not None and trade.get("conid") == order_conid
            )
            if not (same_order or same_conid):
                continue
            fee = trade.get("commission", trade.get("comm", trade.get("fee")))
            if fee is None:
                return "n/d"
            return str(fee)
    except Exception:
        return "n/d"
    return "n/d"


def check_order_fills(state_path: Path) -> None:
    data = ibkr_get("/v1/api/iserver/account/orders")
    if data is None:
        return
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        return
    state = load_state(state_path)
    raw_known = state.get("known_order_status")
    known: dict[str, Any] = dict(raw_known) if isinstance(raw_known, dict) else {}
    for order in orders:
        if not isinstance(order, dict) or order.get("orderId") is None:
            continue
        order_id = str(order["orderId"])
        status = order.get("status")
        if known.get(order_id) != "Filled" and status == "Filled":
            fee = _commission_from_trades(order, order_id)
            avg = order.get("avgPrice", order.get("price", "n/d"))
            _send_order_message(
                state_path,
                f"✅ ESEGUITO: {order.get('side')} {order.get('filledQuantity')} "
                f"{order.get('ticker')} @ {avg} · fee: {fee}",
            )
            known[order_id] = status
            state = load_state(state_path)
            state["known_order_status"] = known
            save_state(state_path, state)
            commit_state_to_git()
        known[order_id] = status
    state = load_state(state_path)
    state["known_order_status"] = known
    save_state(state_path, state)


def ibkr_get_fyi_notifications() -> list[Any] | None:
    data = ibkr_get("/v1/api/fyi/notifications")
    if data is None:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("notifications", "fyi", "items", "data", "result"):
            val = data.get(key)
            if isinstance(val, list):
                return val
        if any(
            key in data
            for key in (
                "notificationId",
                "id",
                "ID",
                "text",
                "message",
                "msgText",
                "MS",
            )
        ):
            return [data]
        return None
    return None


def _fyi_field(note: dict[str, Any], key: str) -> str:
    val = note.get(key)
    if val is None or isinstance(val, (dict, list)):
        return ""
    return str(val).strip()


def _fyi_strip_html(raw: str) -> str:
    text = raw.replace("\r\n", "\n")
    text = re.sub(r"(?is)<a\s+[^>]*>(.*?)</a>", r"\1", text)
    text = re.sub(r"(?i)</?div\b[^>]*>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _fyi_notification_id(note: dict[str, Any]) -> str:
    for key in ("notificationId", "notification_id", "id", "ID", "nId"):
        val = note.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    raw = (
        _fyi_field(note, "MS")
        or _fyi_field(note, "MD")
        or json.dumps(note, sort_keys=True, default=str)
    )
    return "h:" + hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def check_fyi_notifications(state_path: Path) -> None:
    notes = ibkr_get_fyi_notifications()
    if not notes:
        return
    state = load_state(state_path)
    raw_known = state.get("known_fyi_ids")
    known: set[str] = {str(x) for x in raw_known} if isinstance(raw_known, list) else set()
    for note in notes:
        if not isinstance(note, dict):
            continue
        nid = _fyi_notification_id(note)
        if not nid or nid in known:
            continue
        title_raw = _fyi_field(note, "MS")
        if "currency conversion" in title_raw.lower():
            known.add(nid)
            continue
        title = _fyi_strip_html(title_raw)
        body = _fyi_strip_html(_fyi_field(note, "MD"))
        if title and body:
            send_telegram(f"📢 {title}\n\n{body}")
        elif title:
            send_telegram(f"📢 {title}")
        elif body:
            send_telegram(f"📢 {body}")
        known.add(nid)
    state["known_fyi_ids"] = list(known)
    save_state(state_path, state)


def apply_telegram_clear(text: str, watchlist_path: Path) -> list[str] | None:
    if not CLEAR_RE.match(text.strip()):
        return None
    items = load_watchlist(watchlist_path)
    tickers = [str(it.get("ticker") or "").upper() for it in items if it.get("ticker")]
    save_watchlist(watchlist_path, [])
    print(f"Watchlist svuotata ({len(tickers)} ticker).", flush=True)
    return tickers


def _add_locked_fields(ticket: dict[str, Any], *fields: str) -> None:
    locked = list(ticket.get("locked_fields") or [])
    for field in fields:
        if field not in locked:
            locked.append(field)
    ticket["locked_fields"] = locked


def _multiline_command_lines(text: str, command: str) -> list[str] | None:
    """Body lines if the first line is only /command and more lines follow."""
    stripped = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not stripped:
        return None
    lines = stripped.split("\n")
    first = lines[0].strip()
    rest_of_first = re.sub(rf"^/{re.escape(command)}\b", "", first, flags=re.I).strip()
    if rest_of_first or len(lines) < 2:
        return None
    return [ln.strip() for ln in lines[1:] if ln.strip()]


def _line_error_label(line: str) -> str:
    token = line.split(None, 1)[0] if line.split() else line
    return token.lstrip("$").upper()


def _send_set_summary(ok: list[str], err: list[str]) -> None:
    parts: list[str] = []
    if ok:
        parts.append(f"✅ Impostati: {', '.join(ok)}")
    if err:
        parts.append(f"⚠️ Errori: {', '.join(err)}")
    if parts:
        send_telegram("\n".join(parts))


def _parse_set_levels(
    match: re.Match[str],
) -> tuple[str, float, float, float, float] | None:
    try:
        ticker = match.group(1).upper()
        if not is_valid_symbol(ticker):
            return None
        ingresso_low = parse_num(match.group(3))
        high_raw = match.group(4)
        ingresso_high = parse_num(high_raw) if high_raw else ingresso_low
        if ingresso_low > ingresso_high:
            ingresso_low, ingresso_high = ingresso_high, ingresso_low
        stop = parse_num(match.group(5))
        target = parse_num(match.group(6))
    except (TypeError, ValueError, IndexError):
        return None
    return ticker, ingresso_low, ingresso_high, stop, target


def _upsert_set_levels(
    watchlist_path: Path,
    ticker: str,
    ingresso_low: float,
    ingresso_high: float,
    stop: float,
    target: float,
) -> None:
    items = load_watchlist(watchlist_path)
    found = False
    next_items: list[dict[str, Any]] = []
    for it in items:
        if (it.get("ticker") or "").upper() == ticker:
            updated = dict(it)
            updated["ingresso_low"] = ingresso_low
            updated["ingresso_high"] = ingresso_high
            updated["stop"] = stop
            updated["target"] = target
            _add_locked_fields(
                updated, "ingresso_low", "ingresso_high", "stop", "target"
            )
            next_items.append(updated)
            found = True
        else:
            next_items.append(it)
    if not found:
        next_items.append(
            {
                "ticker": ticker,
                "tf": "",
                "ingresso_low": ingresso_low,
                "ingresso_high": ingresso_high,
                "stop": stop,
                "target": target,
                "motivo": "",
            }
        )
        _add_locked_fields(
            next_items[-1], "ingresso_low", "ingresso_high", "stop", "target"
        )
    save_watchlist(watchlist_path, next_items)
    print(
        f"Set  {ticker}  ing {ingresso_low:g}-{ingresso_high:g}  "
        f"stop {stop:g}  tgt {target:g}",
        flush=True,
    )


def apply_telegram_set(text: str, watchlist_path: Path) -> str | list[str] | None:
    body = _multiline_command_lines(text, "set")
    if body is not None:
        ok: list[str] = []
        err: list[str] = []
        for line in body:
            m = SET_LINE_RE.match(line)
            parsed = _parse_set_levels(m) if m else None
            if parsed is None:
                err.append(_line_error_label(line))
                continue
            ticker, ingresso_low, ingresso_high, stop, target = parsed
            _upsert_set_levels(
                watchlist_path, ticker, ingresso_low, ingresso_high, stop, target
            )
            ok.append(ticker)
        _send_set_summary(ok, err)
        return ok
    m = SET_RE.match(text.strip())
    if not m:
        return None
    ticker = m.group(1).upper()
    ingresso_low = parse_num(m.group(3))
    high_raw = m.group(4)
    ingresso_high = parse_num(high_raw) if high_raw else ingresso_low
    if ingresso_low > ingresso_high:
        ingresso_low, ingresso_high = ingresso_high, ingresso_low
    stop = parse_num(m.group(5))
    target = parse_num(m.group(6))
    _upsert_set_levels(watchlist_path, ticker, ingresso_low, ingresso_high, stop, target)
    return ticker


def _upsert_setbuy(watchlist_path: Path, ticker: str, price: float) -> None:
    items = load_watchlist(watchlist_path)
    found = False
    next_items: list[dict[str, Any]] = []
    for it in items:
        if (it.get("ticker") or "").upper() == ticker:
            updated = dict(it)
            updated["ingresso_low"] = price
            updated["ingresso_high"] = price
            _add_locked_fields(updated, "ingresso_low", "ingresso_high")
            next_items.append(updated)
            found = True
        else:
            next_items.append(it)
    if not found:
        blank: dict[str, Any] = {
            "ticker": ticker,
            "tf": "",
            "ingresso_low": price,
            "ingresso_high": price,
            "stop": None,
            "target": None,
            "motivo": "",
        }
        _add_locked_fields(blank, "ingresso_low", "ingresso_high")
        next_items.append(blank)
    save_watchlist(watchlist_path, next_items)
    print(f"setbuy  {ticker}  {price:g}", flush=True)


def apply_telegram_set_field(text: str, watchlist_path: Path) -> str | list[str] | None:
    body = _multiline_command_lines(text, "setbuy")
    if body is not None:
        ok: list[str] = []
        err: list[str] = []
        for line in body:
            m = SETBUY_LINE_RE.match(line)
            ticker = ""
            price: float | None = None
            if m:
                ticker = m.group(1).upper()
                try:
                    price = parse_num(m.group(2))
                except (TypeError, ValueError):
                    price = None
            if not m or not ticker or price is None or not is_valid_symbol(ticker):
                err.append(_line_error_label(line))
                continue
            _upsert_setbuy(watchlist_path, ticker, price)
            ok.append(ticker)
        _send_set_summary(ok, err)
        return ok
    m = SET_FIELD_RE.match(text.strip())
    if not m:
        return None
    command = m.group(1).lower()
    ticker = m.group(2).upper()
    price = parse_num(m.group(3))
    if command == "setbuy":
        _upsert_setbuy(watchlist_path, ticker, price)
        return ticker
    items = load_watchlist(watchlist_path)
    found = False
    next_items: list[dict[str, Any]] = []
    for it in items:
        if (it.get("ticker") or "").upper() == ticker:
            updated = dict(it)
            if command == "settarget":
                updated["target"] = price
                _add_locked_fields(updated, "target")
            else:
                updated["stop"] = price
                _add_locked_fields(updated, "stop")
            next_items.append(updated)
            found = True
        else:
            next_items.append(it)
    if not found:
        blank: dict[str, Any] = {
            "ticker": ticker,
            "tf": "",
            "ingresso_low": None,
            "ingresso_high": None,
            "stop": None,
            "target": None,
            "motivo": "",
        }
        if command == "settarget":
            blank["target"] = price
            _add_locked_fields(blank, "target")
        else:
            blank["stop"] = price
            _add_locked_fields(blank, "stop")
        next_items.append(blank)
    save_watchlist(watchlist_path, next_items)
    print(f"{command}  {ticker}  {price:g}", flush=True)
    return ticker


def apply_telegram_remove(text: str, watchlist_path: Path) -> str | None:
    m = REMOVE_RE.match(text.strip())
    if not m:
        return None
    ticker = m.group(1).upper()
    items = load_watchlist(watchlist_path)
    keep = [it for it in items if (it.get("ticker") or "").upper() != ticker]
    if len(keep) == len(items):
        print(f"{ticker} non era in watchlist.", flush=True)
        return None
    save_watchlist(watchlist_path, keep)
    print(f"Rimosso {ticker} dalla watchlist (via comando Telegram).", flush=True)
    return ticker


def is_noise_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("ALERT "):
        return True
    if stripped.startswith("/"):
        return True
    return False


def tickets_from_updates(
    updates: list[dict[str, Any]],
    chat_id: str,
) -> tuple[list[dict[str, Any]], int | None]:
    tickets: list[dict[str, Any]] = []
    max_id: int | None = None
    for update in updates:
        uid = update.get("update_id")
        if isinstance(uid, int):
            max_id = uid if max_id is None else max(max_id, uid)
        msg = update_payload(update)
        if not msg or not chat_matches(msg.get("chat"), chat_id):
            continue
        text = payload_text(msg)
        if is_noise_text(text):
            continue
        tickets.extend(parse_tickets(text))
    return tickets, max_id


def read_input(files: list[str]) -> str:
    if files:
        parts = [Path(f).read_text(encoding="utf-8") for f in files]
        return "\n\n".join(parts)
    if sys.stdin.isatty():
        print("Incolla i ticket, poi Ctrl+D.", file=sys.stderr)
    return sys.stdin.read()


def cmd_add(args: argparse.Namespace) -> int:
    path = Path(args.watchlist)
    try:
        text = read_input(args.files)
    except OSError as exc:
        print(f"File non letto: {exc}", file=sys.stderr)
        return 1
    tickets = parse_tickets(text)
    if not tickets:
        print("Nessun ticket. Serve $TICKER e, se ci sono, ingresso/stop/target.", file=sys.stderr)
        return 1
    items = load_watchlist(path)
    for t in tickets:
        items = upsert(items, t)
        print(fmt_ticket_line(t))
    save_watchlist(path, items)
    print(f"Watchlist: {len(items)} ticker → {path}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = load_watchlist(Path(args.watchlist))
    if not items:
        print("Watchlist vuota.")
        return 0
    for it in items:
        print(fmt_ticket_line(it))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    path = Path(args.watchlist)
    ticker = args.ticker.strip().lstrip("$").upper()
    items = load_watchlist(path)
    keep = [it for it in items if (it.get("ticker") or "").upper() != ticker]
    if len(keep) == len(items):
        print(f"{ticker} non è in watchlist.")
        return 1
    save_watchlist(path, keep)
    print(f"Tolta {ticker}. Restano {len(keep)}.")
    return 0


def in_ingresso(
    price: float,
    low: float | None,
    high: float | None,
    day_low: float | None = None,
    day_high: float | None = None,
) -> bool:
    if low is None:
        return False
    if high is None or high == low:
        tol = max(0.01, abs(low) * SINGLE_TOUCH_PCT)
        if abs(price - low) <= tol:
            return True
        if day_low is not None and day_high is not None:
            return day_low <= low + tol and day_high >= low - tol
        return False
    if low <= price <= high:
        return True
    if day_low is not None and day_high is not None:
        return day_low <= high and day_high >= low
    return False


def _fetch_price_yahoo(ticker: str) -> float | None:
    if yf is None:
        return None
    sym = to_yahoo(ticker)
    t = yf.Ticker(sym)
    try:
        info = t.fast_info
        px = None
        if hasattr(info, "get"):
            px = info.get("last_price")
            if px is None:
                px = info.get("lastPrice")
        else:
            px = getattr(info, "last_price", None)
        if px is not None and px == px:
            return float(px)
    except Exception:
        pass
    try:
        hist = t.history(period="1d", interval="1m")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    try:
        hist = t.history(period="5d", interval="1d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def fetch_price(ticker: str) -> float | None:
    px = ibkr_get_price(ticker)
    if px is not None:
        return px
    return _fetch_price_yahoo(ticker)


def fetch_prices(tickers: list[str]) -> dict[str, float | None]:
    return {t: fetch_price(t) for t in tickers}


def fetch_day_range(ticker: str) -> tuple[float, float] | None:
    try:
        hist = yf.Ticker(to_yahoo(ticker)).history(period="1d", interval="1m")
        if hist is None or hist.empty:
            return None
        return (float(hist["Low"].min()), float(hist["High"].max()))
    except Exception:
        return None


def fetch_day_ranges(tickers: list[str]) -> dict[str, tuple[float, float] | None]:
    return {t: fetch_day_range(t) for t in tickers}


def _day_bounds(
    ranges: dict[str, tuple[float, float] | None], ticker: str
) -> tuple[float | None, float | None]:
    raw = ranges.get(ticker)
    if not isinstance(raw, tuple) or len(raw) != 2:
        return None, None
    return raw[0], raw[1]


def _intraday_note(spot: bool, hit: bool, price: float) -> str:
    if hit and not spot:
        return f" (toccato in giornata, ora {price:.2f})"
    return ""


def telegram_api(method: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> Any:
    token = telegram_token()
    if not token:
        raise RuntimeError("no token")
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as decode_exc:
            raise RuntimeError(f"HTTP {exc.code}") from decode_exc
        raise RuntimeError(data.get("description") or f"HTTP {exc.code}") from exc
    data = json.loads(raw)
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or method)
    return data.get("result")


def send_telegram(
    text: str,
    chat_id_override: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> int | None:
    if not telegram_token():
        return None
    chat_id = (chat_id_override or "").strip() or telegram_chat_id()
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        result = telegram_api(
            "sendMessage",
            payload,
            timeout=12,
        )
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        print(f"Telegram: invio fallito ({exc})", file=sys.stderr)
        return None
    if isinstance(result, dict):
        mid = result.get("message_id")
        if isinstance(mid, int):
            return mid
    return None


def send_telegram_buttons(text: str, buttons: list[tuple[str, str]]) -> int | None:
    markup = {
        "inline_keyboard": [[{"text": t, "callback_data": d}] for t, d in buttons]
    }
    return send_telegram(text, reply_markup=markup)


def answer_callback_query(callback_query_id: str) -> None:
    try:
        telegram_api(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id},
            timeout=12,
        )
    except Exception:
        pass


def delete_telegram_message(message_id: int | None) -> None:
    if not isinstance(message_id, int):
        return
    try:
        telegram_api(
            "deleteMessage",
            {"chat_id": telegram_chat_id(), "message_id": message_id},
            timeout=12,
        )
    except Exception:
        pass


def should_delete_chat_message(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("ALERT "):
        return False
    if stripped.startswith("📋"):
        return False
    if stripped.startswith("📊"):
        return False
    if stripped.startswith("✅") or stripped.startswith("❌"):
        return False
    if stripped.startswith("💰") or stripped.startswith("📈") or stripped.startswith("⚠️"):
        return False
    if stripped.startswith("🚫") or stripped.startswith("📭"):
        return False
    if stripped.startswith("📜"):
        return False
    if stripped.startswith("📢"):
        return False
    if stripped == "Watchlist vuota.":
        return False
    return True


def telegram_get_updates(offset: int | None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {
        "timeout": 0,
        "allowed_updates": list(UPDATE_KEYS),
    }
    if offset is not None:
        payload["offset"] = offset
    result = telegram_api("getUpdates", payload, timeout=20)
    if not isinstance(result, list):
        return []
    return [u for u in result if isinstance(u, dict)]


def process_single_message(
    text: str,
    message_id: int | None,
    watchlist_path: Path,
    state_path: Path,
) -> tuple[list[str], list[str]]:
    added: list[str] = []
    removed: list[str] = []
    if apply_telegram_buy_flow_start(text, state_path):
        pass
    elif apply_telegram_sell_flow_start(text, state_path):
        pass
    elif process_pending_flow_text(text, state_path):
        pass
    elif apply_telegram_list(text, watchlist_path, state_path):
        pass
    elif apply_telegram_balance(text, state_path):
        pass
    elif apply_telegram_price(text, state_path):
        pass
    elif apply_telegram_buy(text, state_path):
        pass
    elif apply_telegram_sell(text, state_path):
        pass
    elif apply_telegram_trail(text, state_path):
        pass
    elif apply_telegram_cancel_order(text, state_path):
        pass
    elif apply_telegram_modify_order(text, state_path):
        pass
    elif apply_telegram_positions(text, state_path):
        pass
    elif apply_telegram_orders(text, state_path):
        pass
    elif apply_telegram_history(text):
        pass
    else:
        cleared = apply_telegram_clear(text, watchlist_path)
        if cleared is not None:
            removed.extend(cleared)
        else:
            set_ticker = apply_telegram_set(text, watchlist_path)
            if set_ticker is not None:
                if isinstance(set_ticker, str):
                    added.append(set_ticker)
            else:
                field_ticker = apply_telegram_set_field(text, watchlist_path)
                if field_ticker is not None:
                    if isinstance(field_ticker, str):
                        added.append(field_ticker)
                else:
                    gone = apply_telegram_remove(text, watchlist_path)
                    if gone:
                        removed.append(gone)
                    elif not is_noise_text(text):
                        tickets = parse_tickets(text)
                        items = load_watchlist(watchlist_path)
                        for ticket in tickets:
                            ticker = str(ticket.get("ticker") or "").upper()
                            if not is_valid_symbol(ticker):
                                removed.append(
                                    f"{ticker} scartato (non è un'azione/ETF)"
                                )
                                continue
                            key = (ticket["ticker"], ticket.get("tf") or "")
                            existing = next(
                                (
                                    it
                                    for it in items
                                    if (it.get("ticker"), it.get("tf") or "") == key
                                ),
                                None,
                            )
                            if existing is not None:
                                ticket = merge_ticket(existing, ticket)
                            items, changed = upsert_if_changed(items, ticket)
                            if changed:
                                added.append(str(ticket["ticker"]))
                                print(f"Ticket  {fmt_ticket_line(ticket)}", flush=True)
                        if tickets:
                            save_watchlist(watchlist_path, items)
    if should_delete_chat_message(text) and isinstance(message_id, int):
        delete_telegram_message(message_id)
    return added, removed


def ingest_telegram(watchlist_path: Path, state_path: Path) -> int:
    """Legge i ticket nuovi dal gruppo. Offset persistito. Ritorna quanti ticket ha preso."""
    if not telegram_token():
        return 0
    state = load_state(state_path)
    raw_offset = state.get("telegram_offset")
    offset = raw_offset if isinstance(raw_offset, int) else None
    try:
        updates = telegram_get_updates(offset)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        print(f"Telegram: lettura fallita ({exc})", file=sys.stderr)
        return 0
    chat_id = telegram_chat_id()
    added: list[str] = []
    removed: list[str] = []
    for update in updates:
        msg = update_payload(update)
        if not msg or not chat_matches(msg.get("chat"), chat_id):
            continue
        text = payload_text(msg)
        mid = msg.get("message_id")
        one_added, one_removed = process_single_message(
            text,
            mid if isinstance(mid, int) else None,
            watchlist_path,
            state_path,
        )
        added.extend(one_added)
        removed.extend(one_removed)
    tickets, max_id = tickets_from_updates(updates, chat_id)
    if max_id is not None:
        state = load_state(state_path)
        state["telegram_offset"] = max_id + 1
        save_state(state_path, state)
    send_watchlist_summary(added, removed, watchlist_path, state_path)
    return len(tickets)


def ingest_telegram_userbot(watchlist_path: Path, state_path: Path) -> int:
    """Stesso gruppo via account utente (Telethon). Vede i messaggi scritti da bot."""
    if TelegramClient is None or StringSession is None:
        return 0
    creds = userbot_credentials()
    if creds is None:
        return 0
    api_id, api_hash, session = creds
    state = load_state(state_path)
    raw_last = state.get("userbot_last_id")
    last_id = raw_last if isinstance(raw_last, int) else 0
    chat_raw = telegram_chat_id()
    try:
        chat_id: int | str = int(chat_raw)
    except ValueError:
        chat_id = chat_raw

    client = TelegramClient(StringSession(session), api_id, api_hash)
    count = 0
    max_seen = last_id
    try:
        client.start()
        items = load_watchlist(watchlist_path)
        added: list[str] = []
        removed: list[str] = []
        kwargs: dict[str, Any] = {"min_id": last_id, "reverse": True}
        if last_id == 0:
            kwargs["limit"] = 100
        for message in client.iter_messages(chat_id, **kwargs):
            mid = getattr(message, "id", None)
            if isinstance(mid, int):
                max_seen = mid if max_seen == 0 else max(max_seen, mid)
            text = (getattr(message, "text", None) or "").strip()
            if apply_telegram_list(text, watchlist_path, state_path):
                pass
            else:
                cleared = apply_telegram_clear(text, watchlist_path)
                if cleared is not None:
                    removed.extend(cleared)
                    items = load_watchlist(watchlist_path)
                else:
                    set_ticker = apply_telegram_set(text, watchlist_path)
                    if set_ticker is not None:
                        if isinstance(set_ticker, str):
                            added.append(set_ticker)
                        items = load_watchlist(watchlist_path)
                    else:
                        field_ticker = apply_telegram_set_field(text, watchlist_path)
                        if field_ticker is not None:
                            if isinstance(field_ticker, str):
                                added.append(field_ticker)
                            items = load_watchlist(watchlist_path)
                        else:
                            gone = apply_telegram_remove(text, watchlist_path)
                            if gone:
                                removed.append(gone)
                                items = load_watchlist(watchlist_path)
                            elif not is_noise_text(text):
                                tickets = parse_tickets(text)
                                for ticket in tickets:
                                    ticker = str(ticket.get("ticker") or "").upper()
                                    if not is_valid_symbol(ticker):
                                        removed.append(
                                            f"{ticker} scartato (non è un'azione/ETF)"
                                        )
                                        continue
                                    key = (ticket["ticker"], ticket.get("tf") or "")
                                    existing = next(
                                        (
                                            it
                                            for it in items
                                            if (it.get("ticker"), it.get("tf") or "") == key
                                        ),
                                        None,
                                    )
                                    if existing is not None:
                                        ticket = merge_ticket(existing, ticket)
                                    items, changed = upsert_if_changed(items, ticket)
                                    if changed:
                                        added.append(str(ticket["ticker"]))
                                        print(f"Ticket  {fmt_ticket_line(ticket)}", flush=True)
                                        count += 1
            if should_delete_chat_message(text) and isinstance(mid, int):
                delete_telegram_message(mid)
        if added or count:
            save_watchlist(watchlist_path, items)
        send_watchlist_summary(added, removed, watchlist_path, state_path)
        if max_seen:
            state = load_state(state_path)
            state["userbot_last_id"] = max_seen
            save_state(state_path, state)
    except (OSError, TimeoutError, RuntimeError, ValueError, ConnectionError) as exc:
        print(f"Telegram userbot: lettura fallita ({exc})", file=sys.stderr)
        return 0
    except Exception as exc:
        print(f"Telegram userbot: lettura fallita ({exc})", file=sys.stderr)
        return 0
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
    return count


def alert_key(item: dict[str, Any], kind: str) -> tuple[str, str, str]:
    return (item.get("ticker") or "", item.get("tf") or "", kind)


def record_sent_alert(state_path: Path, message_id: int) -> None:
    state = load_state(state_path)
    alerts = list(state.get("sent_alerts") or [])
    alerts.append(
        {
            "message_id": message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    state["sent_alerts"] = alerts
    save_state(state_path, state)


def expire_sent_alerts(state_path: Path, now: datetime | None = None) -> None:
    """Cancella gli alert Telegram più vecchi di 8 ore. Non tocca il riepilogo."""
    state = load_state(state_path)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    kept: list[Any] = []
    for entry in state.get("sent_alerts") or []:
        if not isinstance(entry, dict):
            continue
        expired = False
        sent_at_raw = entry.get("sent_at")
        if isinstance(sent_at_raw, str):
            try:
                sent_at = datetime.fromisoformat(sent_at_raw.replace("Z", "+00:00"))
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                expired = now - sent_at > ALERT_TTL
            except ValueError:
                expired = False
        if expired:
            mid = entry.get("message_id")
            if isinstance(mid, int):
                delete_telegram_message(mid)
        else:
            kept.append(entry)
    state["sent_alerts"] = kept
    save_state(state_path, state)


def record_order_message(
    state_path: Path, message_id: int, ttl: timedelta | None = None
) -> None:
    state = load_state(state_path)
    messages = list(state.get("order_messages") or [])
    ttl = ORDER_MESSAGE_TTL if ttl is None else ttl
    messages.append(
        {
            "message_id": message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "ttl_seconds": int(ttl.total_seconds()),
        }
    )
    state["order_messages"] = messages
    save_state(state_path, state)


def _send_order_message(state_path: Path, text: str) -> None:
    mid = send_telegram(text)
    if isinstance(mid, int):
        record_order_message(state_path, mid)


def _send_flow_message(
    state_path: Path,
    text: str,
    buttons: list[tuple[str, str]] | None = None,
) -> int | None:
    if buttons:
        mid = send_telegram_buttons(text, buttons)
    else:
        mid = send_telegram(text)
    if isinstance(mid, int):
        record_order_message(state_path, mid, ttl=FLOW_MESSAGE_TTL)
    return mid


def expire_order_messages(state_path: Path, now: datetime | None = None) -> None:
    """Cancella i messaggi Telegram scaduti (60s ordini, 120s flusso guidato)."""
    state = load_state(state_path)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    kept: list[Any] = []
    for entry in state.get("order_messages") or []:
        if not isinstance(entry, dict):
            continue
        expired = False
        sent_at_raw = entry.get("sent_at")
        if isinstance(sent_at_raw, str):
            try:
                sent_at = datetime.fromisoformat(sent_at_raw.replace("Z", "+00:00"))
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                ttl_raw = entry.get("ttl_seconds")
                if isinstance(ttl_raw, (int, float)) and ttl_raw > 0:
                    ttl = timedelta(seconds=float(ttl_raw))
                else:
                    ttl = ORDER_MESSAGE_TTL
                expired = now - sent_at > ttl
            except ValueError:
                expired = False
        if expired:
            mid = entry.get("message_id")
            if isinstance(mid, int):
                delete_telegram_message(mid)
                if state.get("orders_message_id") == mid:
                    state["orders_message_id"] = None
        else:
            kept.append(entry)
    state["order_messages"] = kept
    save_state(state_path, state)


def maybe_alert(
    item: dict[str, Any],
    kind: str,
    line: str,
    active: bool,
    fired: dict[tuple[str, str, str], str | None],
    state_path: Path,
) -> None:
    key = alert_key(item, kind)
    if not active:
        return
    today = alert_day()
    if fired.get(key) == today:
        return
    print(line, flush=True)
    mid = send_telegram(line)
    fired[key] = today
    if isinstance(mid, int):
        record_sent_alert(state_path, mid)


GIT_SYNC_REMOTE = (
    "https://x-access-token:{token}@github.com/"
    "andreachiapello317/danny-trade-squad-bot.git"
)
GIT_SYNC_FILES = ("watchlist.json", "watch_state.json")


def commit_state_to_git() -> None:
    """Best-effort: committa watchlist e stato su main. Non deve mai crashare."""
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        print("Git sync: GITHUB_TOKEN assente, skip.", file=sys.stderr)
        return
    cwd = str(Path.cwd())
    remote = GIT_SYNC_REMOTE.format(token=urllib.parse.quote(token, safe=""))

    def run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    def redact(text: str) -> str:
        return (text or "").replace(token, "***").strip()

    try:
        for cfg in (
            ["git", "config", "user.name", "watch-bot"],
            ["git", "config", "user.email", "watch-bot@users.noreply.github.com"],
        ):
            done = run(cfg)
            if done.returncode != 0:
                print(f"Git sync: {redact(done.stderr) or cfg}", file=sys.stderr)
                return
        added = run(["git", "add", "-f", *GIT_SYNC_FILES])
        if added.returncode != 0:
            print(f"Git sync: add fallito ({redact(added.stderr)})", file=sys.stderr)
            return
        diff = run(["git", "diff", "--staged", "--quiet"])
        if diff.returncode == 0:
            print("Git sync: nessuna modifica", flush=True)
            return
        if diff.returncode != 1:
            print(f"Git sync: diff fallito ({redact(diff.stderr)})", file=sys.stderr)
            return
        names = run(["git", "diff", "--staged", "--name-only"])
        n = len(
            [line for line in (names.stdout or "").splitlines() if line.strip()]
        )
        commit = run(
            ["git", "commit", "-m", "Aggiorna stato watchlist [skip ci]"]
        )
        if commit.returncode != 0:
            print(
                f"Git sync: commit fallito ({redact(commit.stderr)})",
                file=sys.stderr,
            )
            return
        print(f"Git sync: {n} modifiche committate", flush=True)
        push = run(["git", "push", remote, "HEAD:main"], timeout=60)
        if push.returncode != 0:
            print(f"Git sync: push fallito ({redact(push.stderr)})", file=sys.stderr)
    except Exception as exc:
        print(f"Git sync: {exc}", file=sys.stderr)


def cycle(
    items: list[dict[str, Any]],
    fired: dict[tuple[str, str, str], str | None],
    state_path: Path,
    lock: threading.Lock | None = None,
) -> None:
    tickers = list(dict.fromkeys(it["ticker"] for it in items if it.get("ticker")))
    prices = fetch_prices(tickers)
    ranges = fetch_day_ranges(tickers)
    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    held = lock if lock is not None else nullcontext()
    with held:
        expire_sent_alerts(state_path)
        for it in items:
            ticker = it["ticker"]
            price = prices.get(ticker)
            day_low, day_high = _day_bounds(ranges, ticker)
            px = f"{price:.2f}" if price is not None else "n/d"
            print(
                f"{now}  {ticker:<6} {px:>8}  "
                f"ing {fmt_ingresso(it):<12} "
                f"stop {fmt_level(it.get('stop')):<8} "
                f"tgt {fmt_level(it.get('target'))}",
                flush=True,
            )
            if price is None:
                continue
            motivo = (it.get("motivo") or "").strip()
            suffix = f"  · {motivo}" if motivo else ""

            lo, hi = it.get("ingresso_low"), it.get("ingresso_high")
            spot_in = in_ingresso(price, lo, hi)
            in_band = in_ingresso(price, lo, hi, day_low, day_high)
            maybe_alert(
                it,
                "ingresso",
                (
                    f"ALERT {ticker} ingresso {price:.2f} ({fmt_ingresso(it)})"
                    f"{_intraday_note(spot_in, in_band, price)}{suffix}"
                ),
                in_band,
                fired,
                state_path,
            )

            stop = it.get("stop")
            if stop is not None:
                stop_lv = float(stop)
                spot_stop = price <= stop_lv
                hit_stop = spot_stop or (day_low is not None and day_low <= stop_lv)
                maybe_alert(
                    it,
                    "stop",
                    (
                        f"ALERT {ticker} stop {price:.2f} (<= {fmt_level(stop)})"
                        f"{_intraday_note(spot_stop, hit_stop, price)}{suffix}"
                    ),
                    hit_stop,
                    fired,
                    state_path,
                )

            target = it.get("target")
            if target is not None:
                target_lv = float(target)
                spot_tgt = price >= target_lv
                hit_tgt = spot_tgt or (day_high is not None and day_high >= target_lv)
                maybe_alert(
                    it,
                    "target",
                    (
                        f"ALERT {ticker} target {price:.2f} (>= {fmt_level(target)})"
                        f"{_intraday_note(spot_tgt, hit_tgt, price)}{suffix}"
                    ),
                    hit_tgt,
                    fired,
                    state_path,
                )


def format_priced_watchlist_lines(items: list[dict[str, Any]]) -> list[str]:
    tickers = list(dict.fromkeys(it["ticker"] for it in items if it.get("ticker")))
    prices = fetch_prices(tickers) if tickers else {}
    lines: list[str] = []
    for it in items:
        ticker = it["ticker"]
        price = prices.get(ticker)
        px = f"{price:.2f}" if price is not None else "n/d"
        lines.append(
            f"{ticker:<6} {px:>8}  "
            f"ing {fmt_ingresso(it):<12} "
            f"stop {fmt_level(it.get('stop')):<8} "
            f"tgt {fmt_level(it.get('target'))}"
        )
    return lines


def maybe_send_daily_summary(items: list[dict[str, Any]], state_path: Path) -> None:
    local = rome_now()
    if local.hour != WATCH_HOUR_START:
        return
    today = local.strftime("%Y-%m-%d")
    state = load_state(state_path)
    if state.get("last_daily_summary") == today:
        return
    if not items:
        body = "📋 Riepilogo giornaliero\nWatchlist vuota."
    else:
        body = "📋 Riepilogo giornaliero\n" + "\n".join(format_priced_watchlist_lines(items))
    send_telegram(body)
    state["last_daily_summary"] = today
    save_state(state_path, state)


def cmd_run(args: argparse.Namespace) -> int:
    if yf is None:
        print("Manca yfinance. pip install -r requirements.txt", file=sys.stderr)
        return 1
    interval = max(5, int(args.interval))
    path = Path(args.watchlist)
    state_path = Path(args.state)
    fired = load_fired(load_state(state_path))
    if not telegram_token():
        print(MISSING_TOKEN_MSG, flush=True)
    else:
        print(
            f"Telegram chat {telegram_chat_id()}: ticket da soli. "
            "Se non arrivano: bot nel gruppo, Group Privacy OFF su @BotFather, un /start nel gruppo.",
            flush=True,
        )
    print(
        "Prezzi vs livelli del ticket. Finestra 15–22 ora italiana. Non è consulenza. Ctrl+C esce.",
        flush=True,
    )
    try:
        while True:
            if not args.ignore_window and not in_watch_window():
                local = rome_now()
                print(
                    f"Fuori finestra ({local.strftime('%H:%M')} ora italiana). "
                    "Prossimo controllo dalle 15:00.",
                    flush=True,
                )
                if args.once:
                    return 0
                time.sleep(interval)
                continue
            ingest_telegram(path, state_path)
            ingest_telegram_userbot(path, state_path)
            expire_sent_alerts(state_path)
            items = load_watchlist(path)
            fired.update(load_fired(load_state(state_path)))
            if not items:
                print("Watchlist vuota. In attesa dei ticket Trader su Telegram.", flush=True)
            else:
                cycle(items, fired, state_path)
            maybe_send_daily_summary(items, state_path)
            persist_fired(state_path, fired)
            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStop.", flush=True)
    return 0


def _watchlist_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-w",
        "--watchlist",
        default=str(DEFAULT_WATCHLIST),
        help="File JSON della watchlist (default: watchlist.json)",
    )


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    _watchlist_arg(common)
    p = argparse.ArgumentParser(
        prog="watch.py",
        description=(
            "Ticket Trader da Telegram → watchlist. "
            "Controlla il prezzo vs ingresso/stop/target. "
            "Non piazza ordini. Non è consulenza finanziaria."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser(
        "add",
        parents=[common],
        help="emergenza: ticket da file/stdin",
    )
    add_p.add_argument("files", nargs="*", help="File testo. Vuoto = stdin")
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", parents=[common], help="Mostra la watchlist")
    list_p.set_defaults(func=cmd_list)

    rm_p = sub.add_parser("remove", parents=[common], help="Togli un ticker (es. AMD)")
    rm_p.add_argument("ticker", help="Ticker, es. AMD")
    rm_p.set_defaults(func=cmd_remove)

    run_p = sub.add_parser("run", parents=[common], help="Telegram + Yahoo, fino a Ctrl+C")
    run_p.add_argument(
        "-i",
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Secondi tra un poll e l'altro (default {DEFAULT_INTERVAL})",
    )
    run_p.add_argument(
        "--once",
        action="store_true",
        help="Un solo ciclo, poi esce",
    )
    run_p.add_argument(
        "--ignore-window",
        action="store_true",
        help="Controlla anche fuori dalle 15–22 ora italiana",
    )
    run_p.add_argument(
        "--state",
        default=str(DEFAULT_STATE),
        help="File offset Telegram (default: watch_state.json)",
    )
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
