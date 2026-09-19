#!/usr/bin/env python3
"""Watchlist: entry sotto prezzo → parte la strategia automatica (ora solo Trail).

Non è consulenza finanziaria.
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
TELEGRAM_MAX_LEN = 4096
IBKR_LOADING_TEXT = "⏳ Un attimo, sto interrogando IBKR…"
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
START_RE = re.compile(r"^/(start|menu)\s*$", re.I)
INGRESSO_INPUT_RE = re.compile(
    rf"^{NUM}(?:\s*{RANGE_SEP}\s*{NUM})?\s*$"
)
MENU_MAIN_TEXT = "🤖 Danny Trade Squad Bot\n\nScegli una categoria:"
MENU_MAIN_BUTTONS = [
    ("📋 Watchlist", "menu:watchlist"),
    ("💰 Trading", "menu:trading"),
    ("🤖 Trading automatico", "menu:automatico"),
    ("📊 Conto", "menu:conto"),
    ("ℹ️ Info", "menu:info"),
]
MENU_NAV_BUTTONS = [
    ("◀️ Indietro", "menu:back"),
    ("🏠 Home", "menu:main"),
]
MENU_WATCHLIST_TEXT = (
    "📋 Watchlist\n\n"
    "Set buy: ticker e prezzo sotto lo spot, poi scegli la "
    "strategia di trading automatico. Oggi c'è solo Trail "
    "(azioni + delta %). Quando l'entry viene toccato parte da sola."
)
MENU_WATCHLIST_BUTTONS = [
    ("📋 Lista attuale", "action:list"),
    ("🟢 Set buy", "action:setbuy"),
    ("🗑️ Rimuovi", "action:rm"),
    ("🧹 Svuota", "action:clear"),
]
MENU_TRADING_TEXT = "💰 Trading\n\nScegli un'azione:"
MENU_TRADING_BUTTONS = [
    ("🟢 Compra", "action:buyflow"),
    ("🔴 Vendi", "action:sellflow"),
    ("🚫 Annulla", "action:cancel"),
    ("✏️ Modifica", "action:modify"),
]
MENU_AUTO_TEXT = (
    "🤖 Trading automatico\n\n"
    "Trail: compra a mercato, nessuno stop sotto. "
    "Break-even = medio + 1% entrata + 1% uscita. "
    "Il delta è in %. Quando il prezzo supera il BE di un delta, "
    "parte uno stop su quel livello e sale a scalini."
)
AUTO_STRATEGIES: dict[str, dict[str, Any]] = {
    "trail": {
        "label": "📉 Trail",
        "action": "trail",
        "params": (
            {
                "key": "quantity",
                "step": "quantity",
                "kind": "shares",
                "prompt": "{ticker}: quante azioni?",
            },
            {
                "key": "delta",
                "step": "delta",
                "kind": "percent",
                "prompt": "{ticker}: delta in %? (es. 2 = 2%)",
            },
        ),
    },
}
MENU_AUTO_BUTTONS = [
    (str(spec["label"]), f"action:{spec['action']}")
    for spec in AUTO_STRATEGIES.values()
] + [("🛑 Ferma Trail", "action:stoptrail")]


def auto_strategy_pick_buttons() -> list[tuple[str, str]]:
    return [
        (str(spec["label"]), f"strategy:{name}")
        for name, spec in AUTO_STRATEGIES.items()
    ]
MENU_CONTO_TEXT = "📊 Conto\n\nScegli un'azione:"
MENU_CONTO_BUTTONS = [
    ("💰 Saldo", "action:saldo"),
    ("📊 Posizioni", "action:posizioni"),
    ("📋 Ordini", "action:ordini"),
    ("📜 Storico", "action:history"),
]
MENU_INFO_TEXT = (
    "ℹ️ Info stock\n\n"
    "Tocca i campi che vuoi (anche più di uno), poi Mostra."
)
MENU_INFO_BUTTONS = [
    ("📈 Prezzo", "action:price"),
]
QUOTE_FIELDS: dict[str, dict[str, Any]] = {
    "price": {"label": "Prezzo", "ids": ("31",)},
    "book": {"label": "Bid / Ask", "ids": ("84", "86", "88", "85")},
    "volume": {"label": "Volume", "ids": ("87",)},
    "range": {"label": "Min / Max", "ids": ("71", "70")},
    "change": {"label": "Variazione", "ids": ("82", "83")},
    "session": {"label": "Open / Close", "ids": ("7295", "7296")},
}
QUOTE_ALWAYS_IDS = ("55", "58")
QUOTE_DEFAULT_FIELDS = ["price", "volume"]
BOT_MESSAGE_KEY = "bot_message_id"
LEGACY_MESSAGE_KEYS = (
    "menu_message_id",
    "summary_message_id",
    "balance_message_id",
    "positions_message_id",
    "orders_message_id",
    "price_message_id",
    "flow_message_id",
)
MENU_PAGES: dict[str, tuple[str, list[tuple[str, str]] | None, bool]] = {
    "main": (MENU_MAIN_TEXT, MENU_MAIN_BUTTONS, False),
    "watchlist": (MENU_WATCHLIST_TEXT, MENU_WATCHLIST_BUTTONS, True),
    "trading": (MENU_TRADING_TEXT, MENU_TRADING_BUTTONS, True),
    "automatico": (MENU_AUTO_TEXT, MENU_AUTO_BUTTONS, True),
    "conto": (MENU_CONTO_TEXT, MENU_CONTO_BUTTONS, True),
    "info": (MENU_INFO_TEXT, MENU_INFO_BUTTONS, True),
}
MENU_ACTION_KINDS = {
    "list",
    "saldo",
    "posizioni",
    "ordini",
    "buyflow",
    "sellflow",
    "setbuy",
    "rm",
    "clear",
    "cancel",
    "modify",
    "trail",
    "stoptrail",
    "history",
    "price",
}
MENU_SLOW_ACTIONS = {
    "list",
    "saldo",
    "posizioni",
    "ordini",
    "sellflow",
    "cancel",
    "modify",
    "stoptrail",
}
MENU_FLOW_KINDS = {
    "setbuy": "SETBUY",
    "rm": "RM",
    "clear": "CLEAR",
    "cancel": "CANCEL",
    "modify": "MODIFY",
    "trail": "TRAIL",
    "stoptrail": "STOPTRAIL",
    "history": "HISTORY",
    "price": "PRICE",
}


def parse_num(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def clip_text(text: str, limit: int = TELEGRAM_MAX_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _is_not_modified(exc: BaseException) -> bool:
    return "not modified" in str(exc).lower()


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
    items = load_watchlist(watchlist_path)
    if not items:
        body = "Watchlist vuota."
    else:
        body = "\n".join(fmt_ticket_line(it) for it in items)
    _send_replacing_message(state_path, "summary_message_id", body)


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
    _send_replacing_message(state_path, "summary_message_id", "\n".join(lines))


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
    ticker = str(item.get("ticker") or "?").upper()
    strategy = str(item.get("strategy") or "").strip().lower()
    if strategy:
        entry = item.get("entry")
        qty = item.get("quantity")
        delta = item.get("delta")
        status = str(item.get("status") or "waiting")
        label = "in attesa" if status == "waiting" else "scattato"
        return (
            f"{ticker} entry {fmt_level(_float_or_none(entry))} · "
            f"{strategy.title()} {qty} az · Δ {fmt_level(_float_or_none(delta))}% · "
            f"{label}"
        )
    motivo = (item.get("motivo") or "").strip()
    extra = f" {motivo}" if motivo else ""
    return f"{ticker} (senza strategia){extra}"


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


def _bot_message_id(state: dict[str, Any]) -> int | None:
    raw = state.get(BOT_MESSAGE_KEY)
    if isinstance(raw, int):
        return raw
    for key in LEGACY_MESSAGE_KEYS:
        legacy = state.get(key)
        if isinstance(legacy, int):
            return legacy
    return None


def _remember_bot_message(state_path: Path, message_id: int) -> None:
    state = load_state(state_path)
    state[BOT_MESSAGE_KEY] = message_id
    for key in LEGACY_MESSAGE_KEYS:
        state[key] = message_id
    save_state(state_path, state)


def deliver_text(
    state_path: Path,
    text: str,
    buttons: list[tuple[str, str]] | None = None,
    *,
    with_nav: bool = False,
) -> int | None:
    """Un solo messaggio del bot: lo modifica, o lo sostituisce se l'edit fallisce."""
    text = clip_text(text)
    shown = list(buttons or [])
    if with_nav:
        shown.extend(MENU_NAV_BUTTONS)
    old_id = _bot_message_id(load_state(state_path))
    chat = telegram_chat_id()
    if isinstance(old_id, int) and edit_telegram_message(chat, old_id, text, shown):
        _remember_bot_message(state_path, old_id)
        return old_id
    if isinstance(old_id, int):
        delete_telegram_message(old_id)
    new_id = (
        send_telegram_buttons(text, shown) if shown else send_telegram(text)
    )
    if isinstance(new_id, int):
        _remember_bot_message(state_path, new_id)
        return new_id
    return None


def _save_menu_message_id(state_path: Path, message_id: int) -> None:
    _remember_bot_message(state_path, message_id)


def _menu_nav_state(state_path: Path) -> tuple[str, list[str]]:
    state = load_state(state_path)
    page = state.get("menu_page")
    if page not in MENU_PAGES:
        page = "main"
    raw = state.get("menu_nav_stack")
    stack = [str(item) for item in raw] if isinstance(raw, list) else []
    return str(page), stack


def _save_menu_nav(state_path: Path, page: str, stack: list[str]) -> None:
    state = load_state(state_path)
    state["menu_page"] = page
    state["menu_nav_stack"] = stack
    save_state(state_path, state)


def _clear_pending_flow(state_path: Path) -> None:
    if _pending_flow(load_state(state_path)) is None:
        return
    _save_pending_flow(state_path, None)


def _show_menu_page(
    chat_id: Any,
    message_id: int | None,
    text: str,
    buttons: list[tuple[str, str]] | None,
    state_path: Path,
    *,
    with_nav: bool = False,
) -> None:
    del chat_id, message_id
    deliver_text(state_path, text, buttons, with_nav=with_nav)


def _show_named_menu(
    chat_id: Any,
    message_id: int | None,
    state_path: Path,
    page: str,
    *,
    push: bool = False,
    reset: bool = False,
) -> None:
    if page not in MENU_PAGES:
        page = "main"
    here, stack = _menu_nav_state(state_path)
    if reset:
        stack = []
    elif push and here != page:
        if not stack or stack[-1] != here:
            stack.append(here)
        if len(stack) > 8:
            stack = stack[-8:]
    _save_menu_nav(state_path, page, stack)
    text, buttons, with_nav = MENU_PAGES[page]
    if page == "main":
        text = format_home_text(live=True)
    elif page == "info":
        _start_quote_picker(state_path)
        return
    _show_menu_page(
        chat_id, message_id, text, buttons, state_path, with_nav=with_nav
    )


def _show_menu_loading(state_path: Path) -> bool:
    old_id = _bot_message_id(load_state(state_path))
    if not isinstance(old_id, int):
        return False
    return edit_telegram_message(
        telegram_chat_id(), old_id, IBKR_LOADING_TEXT, []
    )


def _push_result_nav(state_path: Path) -> None:
    """Così ◀️ Indietro dal risultato torna alla categoria, non salta la home."""
    here, stack = _menu_nav_state(state_path)
    if here == "main":
        return
    if not stack or stack[-1] != here:
        stack.append(here)
        _save_menu_nav(state_path, here, stack)


def apply_telegram_start(text: str, state_path: Path) -> bool:
    if not START_RE.match(text.strip()):
        return False
    _clear_pending_flow(state_path)
    _show_named_menu(
        telegram_chat_id(),
        None,
        state_path,
        "main",
        reset=True,
    )
    return True


def apply_menu_action(
    kind: str, watchlist_path: Path, state_path: Path
) -> None:
    if kind in MENU_SLOW_ACTIONS:
        _show_menu_loading(state_path)
    if kind == "list":
        apply_telegram_list("/list", watchlist_path, state_path)
        return
    if kind == "saldo":
        apply_telegram_balance("/saldo", state_path)
        return
    if kind == "posizioni":
        apply_telegram_positions("/posizioni", state_path)
        return
    if kind == "ordini":
        apply_telegram_orders("/ordini", state_path)
        return
    if kind == "buyflow":
        apply_telegram_buy_flow_start("/compra", state_path)
        return
    if kind == "sellflow":
        apply_telegram_sell_flow_start("/vendi", state_path)
        return
    flow_kind = MENU_FLOW_KINDS.get(kind)
    if flow_kind:
        _start_guided_flow(flow_kind, watchlist_path, state_path)


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


def ibkr_account_snapshot() -> dict[str, Any] | None:
    accounts = ibkr_get("/v1/api/portfolio/accounts")
    if not isinstance(accounts, list) or not accounts:
        return None
    first = accounts[0]
    if not isinstance(first, dict) or not first.get("accountId"):
        return None
    account_id = str(first["accountId"])
    ledger = ibkr_get(f"/v1/api/portfolio/{account_id}/ledger")
    cashbalance: Any = None
    netliquidationvalue: Any = None
    currency = ""
    if isinstance(ledger, dict):
        raw = ledger.get("BASE")
        if not isinstance(raw, dict):
            raw = next(iter(ledger.values()), None)
        if isinstance(raw, dict):
            cashbalance = raw.get("cashbalance")
            netliquidationvalue = raw.get("netliquidationvalue")
            currency = str(raw.get("currency") or "")
    return {
        "account_id": account_id,
        "cashbalance": cashbalance,
        "netliquidationvalue": netliquidationvalue,
        "currency": currency,
    }


def format_account_lines(snapshot: dict[str, Any] | None) -> str:
    if snapshot is None:
        return "Conto: n/d\nContanti: n/d\nValore netto: n/d"
    account_id = str(snapshot.get("account_id") or "").strip() or "n/d"
    currency = str(snapshot.get("currency") or "").strip()
    cash = snapshot.get("cashbalance")
    nlv = snapshot.get("netliquidationvalue")
    cash_s = "n/d" if cash is None else f"{cash} {currency}".strip()
    nlv_s = "n/d" if nlv is None else f"{nlv} {currency}".strip()
    return f"Conto: {account_id}\nContanti: {cash_s}\nValore netto: {nlv_s}"


def _open_positions(positions: list[Any] | None) -> list[dict[str, Any]]:
    if not positions:
        return []
    open_rows: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        try:
            qty = float(pos.get("position") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty == 0:
            continue
        open_rows.append(pos)
    return open_rows


def format_home_positions(positions: list[Any] | None) -> str:
    if positions is None:
        return "Posizioni: n/d"
    rows = _open_positions(positions)
    if not rows:
        return "Posizioni: nessuna"
    lines = ["Posizioni:"]
    lines.extend(_fmt_position_line(pos) for pos in rows)
    return "\n".join(lines)


def format_home_text(
    snapshot: dict[str, Any] | None = None,
    positions: list[Any] | None = None,
    *,
    live: bool = False,
) -> str:
    if live:
        snapshot = ibkr_account_snapshot()
        positions = ibkr_get_positions()
    return (
        "🤖 Danny Trade Squad Bot\n\n"
        f"{format_account_lines(snapshot)}\n\n"
        f"{format_home_positions(positions)}\n\n"
        "Scegli una categoria:"
    )


def maybe_refresh_home(state_path: Path) -> None:
    """Ri-legge saldo, conto e posizioni sulla home, se è quella a schermo."""
    state = load_state(state_path)
    if _pending_flow(state) is not None:
        return
    if state.get("menu_page") != "main":
        return
    if not isinstance(_bot_message_id(state), int):
        return
    deliver_text(state_path, format_home_text(live=True), MENU_MAIN_BUTTONS)


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


def ibkr_get_snapshot(
    ticker: str, field_ids: list[str]
) -> dict[str, Any] | None:
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return None
    fields = ",".join(dict.fromkeys(fid for fid in field_ids if fid))
    if not fields:
        fields = "31"
    path = f"/v1/api/iserver/marketdata/snapshot?conids={conid}&fields={fields}"
    ibkr_get(path)
    time.sleep(1)
    snap = ibkr_get(path)
    if not isinstance(snap, list) or not snap:
        return None
    first = snap[0]
    return first if isinstance(first, dict) else None


def _quote_selected_fields(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return list(QUOTE_DEFAULT_FIELDS)
    return [key for key in QUOTE_FIELDS if key in raw]


def _quote_field_ids(selected: list[str]) -> list[str]:
    ids = list(QUOTE_ALWAYS_IDS)
    for key in selected:
        spec = QUOTE_FIELDS.get(key)
        if spec is None:
            continue
        ids.extend(str(item) for item in spec["ids"])
    return list(dict.fromkeys(ids))


def _quote_cell(row: dict[str, Any], field_id: str) -> str | None:
    raw = row.get(field_id)
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if not text or text.upper() in {"N/A", "--", "—"}:
        return None
    return text


def _fmt_quote_volume(raw: str) -> str:
    match = _IBKR_PRICE_RE.search(raw.replace(",", ""))
    if not match:
        return raw
    try:
        value = float(match.group(0))
    except ValueError:
        return raw
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:g}"


def _format_quote_line(key: str, row: dict[str, Any]) -> str | None:
    if key == "price":
        last = _quote_cell(row, "31")
        return f"Prezzo: {last}" if last else None
    if key == "book":
        bid = _quote_cell(row, "84")
        ask = _quote_cell(row, "86")
        bid_sz = _quote_cell(row, "88")
        ask_sz = _quote_cell(row, "85")
        left = f"{bid} × {bid_sz}" if bid and bid_sz else bid
        right = f"{ask} × {ask_sz}" if ask and ask_sz else ask
        if left and right:
            return f"Bid / Ask: {left}  ·  {right}"
        if left:
            return f"Bid: {left}"
        if right:
            return f"Ask: {right}"
        return None
    if key == "volume":
        volume = _quote_cell(row, "87")
        return f"Volume: {_fmt_quote_volume(volume)}" if volume else None
    if key == "range":
        low = _quote_cell(row, "71")
        high = _quote_cell(row, "70")
        if low and high:
            return f"Min / Max: {low} – {high}"
        if low:
            return f"Min: {low}"
        if high:
            return f"Max: {high}"
        return None
    if key == "change":
        change = _quote_cell(row, "82")
        pct = _quote_cell(row, "83")
        if change and pct:
            return f"Variazione: {change} ({pct})"
        if change:
            return f"Variazione: {change}"
        if pct:
            return f"Variazione: {pct}"
        return None
    if key == "session":
        opened = _quote_cell(row, "7295")
        closed = _quote_cell(row, "7296")
        if opened and closed:
            return f"Open / Close: {opened} / {closed}"
        if opened:
            return f"Open: {opened}"
        if closed:
            return f"Close: {closed}"
        return None
    return None


def format_quote_card(
    ticker: str, row: dict[str, Any] | None, selected: list[str]
) -> str:
    if row is None:
        return f"⚠️ Dati IBKR non disponibili per {ticker}."
    keys = _quote_selected_fields(selected)
    lines = [f"📈 {ticker}"]
    name = _quote_cell(row, "58")
    if name and name.upper() != ticker.upper():
        lines.append(name)
    body = [_format_quote_line(key, row) for key in keys]
    shown = [line for line in body if line]
    if not shown:
        return f"⚠️ Dati IBKR non disponibili per {ticker}."
    lines.append("")
    lines.extend(shown)
    return "\n".join(lines)


def _quote_picker_buttons(selected: list[str]) -> list[tuple[str, str]]:
    buttons: list[tuple[str, str]] = []
    chosen = set(selected)
    for key, spec in QUOTE_FIELDS.items():
        mark = "✓ " if key in chosen else ""
        buttons.append((f"{mark}{spec['label']}", f"quotefield:{key}"))
    buttons.append(("🔎 Mostra", "quote:go"))
    return buttons


def _load_quote_fields(state_path: Path) -> list[str]:
    raw = load_state(state_path).get("quote_fields")
    if not isinstance(raw, list):
        return list(QUOTE_DEFAULT_FIELDS)
    return _quote_selected_fields(raw)


def _save_quote_fields(state_path: Path, selected: list[str]) -> None:
    state = load_state(state_path)
    state["quote_fields"] = _quote_selected_fields(selected)
    save_state(state_path, state)


def _start_quote_picker(state_path: Path) -> None:
    selected = _load_quote_fields(state_path)
    _send_flow_message(
        state_path,
        MENU_INFO_TEXT,
        _quote_picker_buttons(selected),
    )


def _show_quote_for_ticker(ticker: str, flow: dict[str, Any], state_path: Path) -> None:
    selected = _quote_selected_fields(flow.get("quote_fields"))
    _save_pending_flow(state_path, None)
    _preview_loading(state_path, "price_message_id")
    row = ibkr_get_snapshot(ticker, _quote_field_ids(selected))
    _send_replacing_message(
        state_path, "price_message_id", format_quote_card(ticker, row, selected)
    )


def _preview_loading(state_path: Path, id_key: str) -> None:
    del id_key
    old_id = _bot_message_id(load_state(state_path))
    if isinstance(old_id, int):
        edit_telegram_message(telegram_chat_id(), old_id, IBKR_LOADING_TEXT, [])


def _send_replacing_message(
    state_path: Path,
    id_key: str,
    text: str,
    ttl: timedelta | None = None,
) -> None:
    del id_key
    _push_result_nav(state_path)
    mid = deliver_text(state_path, text, with_nav=True)
    if ttl is not None and isinstance(mid, int):
        state = load_state(state_path)
        state["order_messages"] = [
            {
                "message_id": mid,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "ttl_seconds": int(ttl.total_seconds()),
            }
        ]
        save_state(state_path, state)


def apply_telegram_balance(text: str, state_path: Path) -> bool:
    if not BALANCE_RE.match(text.strip()):
        return False
    _preview_loading(state_path, "balance_message_id")
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
    _preview_loading(state_path, "price_message_id")
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


_IBKR_SUPPRESS_MESSAGE_IDS = [
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


def ensure_reply_suppression() -> None:
    try:
        ibkr_post(
            "/v1/api/iserver/questions/suppress",
            {"messageIds": list(_IBKR_SUPPRESS_MESSAGE_IDS)},
        )
    except Exception as exc:
        print(f"IBKR suppress: {exc}", file=sys.stderr)


def _ibkr_payload_items(
    result: dict[str, Any] | list[Any] | None,
) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _ibkr_error_text(result: dict[str, Any] | list[Any] | None) -> str | None:
    for item in _ibkr_payload_items(result):
        err = item.get("error") or item.get("errorMessage")
        if err:
            return " ".join(str(err).split())
        if item.get("id") is not None:
            continue
        raw = item.get("message")
        if isinstance(raw, list):
            text = " ".join(str(part) for part in raw if part)
        elif raw:
            text = str(raw)
        else:
            continue
        text = " ".join(text.split())
        if text:
            return text
    return None


def _ibkr_is_question(item: dict[str, Any]) -> bool:
    if item.get("id") is None:
        return False
    return item.get("message") is not None or item.get("messageIds") is not None


def _ibkr_item_status(item: dict[str, Any]) -> str:
    return str(item.get("order_status") or item.get("status") or "").strip().lower()


def _ibkr_item_is_dead(item: dict[str, Any]) -> bool:
    return _ibkr_item_status(item) in _STEP_TRAIL_DEAD


def _ibkr_is_submitted(item: dict[str, Any]) -> bool:
    if item.get("order_id") is not None or item.get("orderId") is not None:
        return True
    if item.get("local_order_id") is not None:
        return True
    status = _ibkr_item_status(item)
    return status in {
        "submitted",
        "presubmitted",
        "pendingsubmit",
        "filled",
        "cancelled",
        "canceled",
    }


def _confirm_order_replies(
    result: dict[str, Any] | list[Any] | None,
) -> dict[str, Any] | None:
    confirmed, _ = _confirm_order_replies_detail(result)
    return confirmed


def _confirm_order_replies_detail(
    result: dict[str, Any] | list[Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    last = result
    for _ in range(8):
        items = _ibkr_payload_items(last)
        if not items:
            err = _ibkr_error_text(last)
            return None, err
        for item in items:
            if _ibkr_is_submitted(item):
                return item, None
        question = next((item for item in items if _ibkr_is_question(item)), None)
        if question is None:
            err = _ibkr_error_text(last)
            if err:
                return None, err
            print(f"IBKR confirm fail: {last}", file=sys.stderr)
            return None, None
        last = ibkr_post(
            f"/v1/api/iserver/reply/{question['id']}",
            {"confirmed": True},
        )
        if last is None:
            return None, "IBKR non ha risposto alla conferma."
    return None, "IBKR ha chiesto troppe conferme."


def _order_not_confirmed(ticker: str, detail: str | None) -> str:
    if detail:
        if len(detail) > 280:
            detail = detail[:277] + "..."
        return f"⚠️ {detail}"
    return (
        f"⚠️ Ordine non confermato per {ticker}, controlla manualmente su IBKR."
    )


def _confirmed_order_id(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("order_id", "orderId"):
        raw = item.get(key)
        if raw not in (None, ""):
            return str(raw)
    return None


def _float_or_none(raw: Any) -> float | None:
    if raw in (None, "", "n/d"):
        return None
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _share_qty(raw: Any) -> int | None:
    value = _float_or_none(raw)
    if value is None:
        return None
    qty = int(value)
    if qty < 1:
        return None
    return qty


def _fee_amount(raw: Any) -> float:
    value = _float_or_none(raw)
    if value is None:
        return 0.0
    return abs(value)


def ibkr_place_order_ex(
    ticker: str, quantity: int, side: str, price: float | None
) -> tuple[str, str | None]:
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return f"⚠️ Impossibile trovare {ticker} su IBKR.", None
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR.", None
    try:
        conid_int = int(conid)
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR.", None
    auto_price = price is None
    if price is None:
        spot = ibkr_get_price(ticker)
        if spot is None:
            return f"⚠️ Impossibile determinare un prezzo per {ticker}.", None
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
        return "⚠️ Errore nell'invio dell'ordine.", None
    confirmed, err = _confirm_order_replies_detail(result)
    if confirmed is not None:
        if _ibkr_item_is_dead(confirmed):
            status = _ibkr_item_status(confirmed) or "cancellato"
            return f"⚠️ Ordine {ticker} non attivo ({status}).", None
        oid = _confirmed_order_id(confirmed)
        if auto_price:
            return (
                f"✅ Ordine {side} {quantity} {ticker} @ {price:.2f} "
                f"(auto, ~mercato) inviato.",
                oid,
            )
        return f"✅ Ordine {side} {quantity} {ticker} @ {price} inviato.", oid
    return _order_not_confirmed(ticker, err), None


def ibkr_place_order(
    ticker: str, quantity: int, side: str, price: float | None
) -> str:
    message, _order_id = ibkr_place_order_ex(ticker, quantity, side, price)
    return message


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
    confirmed, err = _confirm_order_replies_detail(result)
    if confirmed is None:
        return _order_not_confirmed(ticker, err)
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


_ACTIVE_TRAIL_STATUSES = {"buying", "watching", "armed"}
_STEP_TRAIL_DEAD = {
    "cancelled",
    "canceled",
    "rejected",
    "expired",
    "apicancelled",
}


def _auto_trails(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("auto_trails")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _active_step_trails(state_path: Path) -> list[dict[str, Any]]:
    return [
        trail
        for trail in _auto_trails(load_state(state_path))
        if str(trail.get("status") or "") in _ACTIVE_TRAIL_STATUSES
    ]


def _save_auto_trails(state_path: Path, trails: list[dict[str, Any]]) -> None:
    state = load_state(state_path)
    state["auto_trails"] = trails
    save_state(state_path, state)


TRAIL_ENTRY_FEE_PCT = 1.0
TRAIL_EXIT_FEE_PCT = 1.0


def step_trail_step_amount(breakeven: float, delta_pct: float) -> float | None:
    if delta_pct <= 0 or breakeven <= 0:
        return None
    step = breakeven * (delta_pct / 100.0)
    if step <= 0:
        return None
    return step


def step_trail_stop_price(
    price: float, breakeven: float, delta_pct: float
) -> float | None:
    """Stop a scalini: delta in % sul BE. Parte a BE quando prezzo >= BE+delta%."""
    step = step_trail_step_amount(breakeven, delta_pct)
    if step is None:
        return None
    if price + 1e-9 < breakeven + step:
        return None
    levels = int((price - breakeven + 1e-9) / step)
    if levels < 1:
        return None
    return round(breakeven + (levels - 1) * step, 2)


def step_trail_breakeven(avg_price: float) -> float:
    """BE dopo 1% in entrata e 1% in uscita: avg * 1.01 / 0.99."""
    entry = 1.0 + TRAIL_ENTRY_FEE_PCT / 100.0
    exit_keep = 1.0 - TRAIL_EXIT_FEE_PCT / 100.0
    if exit_keep <= 0:
        return avg_price
    return round(avg_price * entry / exit_keep, 4)


def ibkr_place_stop(
    ticker: str, quantity: int, stop_price: float
) -> tuple[str | None, str | None]:
    ticker = ticker.strip().upper()
    conid = ibkr_lookup_conid(ticker)
    if not conid:
        return f"⚠️ Impossibile trovare {ticker} su IBKR.", None
    account_id = ibkr_get_account_id()
    if not account_id:
        return "⚠️ Impossibile leggere l'account IBKR.", None
    try:
        conid_int = int(conid)
    except (TypeError, ValueError):
        return f"⚠️ Impossibile trovare {ticker} su IBKR.", None
    last_err: str | None = "⚠️ Errore nell'invio dello stop."
    for extra in ({"outsideRTH": True}, {}):
        order = {
            "conid": conid_int,
            "orderType": "STP",
            "side": "SELL",
            "quantity": quantity,
            "price": stop_price,
            "auxPrice": stop_price,
            "tif": "GTC",
            **extra,
        }
        result = ibkr_post(
            f"/v1/api/iserver/account/{account_id}/orders",
            {"orders": [order]},
        )
        if result is None:
            continue
        confirmed, err = _confirm_order_replies_detail(result)
        if confirmed is not None:
            if _ibkr_item_is_dead(confirmed):
                last_err = (
                    f"⚠️ Stop {ticker} non attivo "
                    f"({_ibkr_item_status(confirmed) or 'cancellato'})."
                )
                continue
            oid = _confirmed_order_id(confirmed)
            if oid:
                return None, oid
            last_err = "⚠️ Stop inviato ma IBKR non ha dato l'id."
            continue
        last_err = _order_not_confirmed(ticker, err)
    return last_err, None


def ibkr_replace_stop(
    order_id: str, ticker: str, quantity: int, stop_price: float
) -> str | None:
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
    result = ibkr_post(
        f"/v1/api/iserver/account/{account_id}/order/{order_id}",
        {
            "conid": conid_int,
            "orderType": "STP",
            "side": "SELL",
            "quantity": quantity,
            "price": stop_price,
            "auxPrice": stop_price,
            "tif": "GTC",
            "outsideRTH": True,
        },
    )
    confirmed, err = _confirm_order_replies_detail(result)
    if confirmed is None:
        return _order_not_confirmed(ticker, err)
    return None


def start_step_trail(
    ticker: str, quantity: int, delta: float, state_path: Path
) -> str:
    ticker = ticker.strip().upper()
    if quantity < 1:
        return "⚠️ Numero di azioni non valido."
    if delta <= 0 or delta > 100:
        return "⚠️ Delta non valido. Usa una percentuale, es. 2."
    for existing in _active_step_trails(state_path):
        if str(existing.get("ticker") or "").strip().upper() == ticker:
            return (
                f"⚠️ C'è già un Trail attivo su {ticker}. "
                "Fermalo prima di aprirne un altro."
            )
    message, order_id = ibkr_place_order_ex(ticker, quantity, "BUY", None)
    if message.startswith("⚠️"):
        return message
    trails = _auto_trails(load_state(state_path))
    trails.append(
        {
            "id": f"tr{int(time.time() * 1000) % 10**10}",
            "ticker": ticker,
            "quantity": quantity,
            "delta": delta,
            "buy_order_id": order_id,
            "avg_price": None,
            "buy_fee": None,
            "breakeven": None,
            "stop_level": None,
            "stop_order_id": None,
            "status": "buying",
        }
    )
    _save_auto_trails(state_path, trails)
    check_order_fills(state_path)
    return f"{message}\n{_trail_start_followup(state_path, ticker, order_id, delta)}"


def stop_step_trail(state_path: Path, ticker: str | None = None) -> str:
    """Ferma il Trail: toglie lo stop IBKR e lascia la posizione."""
    wanted = ticker.strip().upper() if ticker else None
    trails = _auto_trails(load_state(state_path))
    targets = [
        trail
        for trail in trails
        if str(trail.get("status") or "") in _ACTIVE_TRAIL_STATUSES
        and (
            wanted is None
            or str(trail.get("ticker") or "").strip().upper() == wanted
        )
    ]
    if not targets:
        if wanted:
            return f"📭 Nessun Trail attivo su {wanted}."
        return "📭 Nessun Trail attivo."
    account_id = ibkr_get_account_id()
    names: list[str] = []
    for trail in targets:
        cancel_ids: list[Any] = []
        if str(trail.get("status") or "") == "buying":
            buy_id = trail.get("buy_order_id")
            if buy_id:
                cancel_ids.append(buy_id)
        stop_id = trail.get("stop_order_id")
        if stop_id:
            cancel_ids.append(stop_id)
        if account_id and cancel_ids:
            _ibkr_delete_orders(account_id, cancel_ids)
        trail["status"] = "stopped"
        trail["stop_order_id"] = None
        name = str(trail.get("ticker") or "?").upper()
        if name not in names:
            names.append(name)
    _save_auto_trails(state_path, trails)
    return (
        f"🛑 Trail fermato: {', '.join(names)}. "
        "Stop IBKR tolto. Puoi vendere tu."
    )


def _trail_by_buy(state_path: Path, ticker: str, order_id: str | None) -> dict[str, Any] | None:
    ticker = ticker.strip().upper()
    wanted = str(order_id or "")
    found: dict[str, Any] | None = None
    for trail in _auto_trails(load_state(state_path)):
        if str(trail.get("ticker") or "").strip().upper() != ticker:
            continue
        if wanted and str(trail.get("buy_order_id") or "") == wanted:
            return trail
        found = trail
    return found


def _trail_start_followup(
    state_path: Path, ticker: str, order_id: str | None, delta: float
) -> str:
    trail = _trail_by_buy(state_path, ticker, order_id)
    status = str((trail or {}).get("status") or "buying")
    if status == "error":
        return (
            f"⚠️ Trail {ticker}: il buy è stato cancellato o rifiutato da IBKR. "
            "Non c'è un ordine attivo. Riprova (in orario di mercato se è weekend)."
        )
    if status == "watching":
        avg = trail.get("avg_price") if trail else None
        be = trail.get("breakeven") if trail else None
        avg_s = f"{avg:g}" if isinstance(avg, (int, float)) else "?"
        be_s = f"{be:g}" if isinstance(be, (int, float)) else "?"
        return (
            f"Trail {ticker}: fill @ {avg_s} · break-even {be_s} "
            f"(1% entrata + 1% uscita). Nessuno stop sotto. "
            f"Attendo +{delta:g}% sul BE. "
            "Il buy non è più tra gli ordini aperti perché è già eseguito."
        )
    return (
        f"Trail {ticker}: nessuno stop sotto. "
        f"Delta {delta:g}%. Attendo il fill per il break-even "
        f"(1% entrata + 1% uscita)."
    )


def format_trail_status_lines(trails: list[dict[str, Any]]) -> list[str]:
    labels = {
        "buying": "buy inviato, attendo fill",
        "watching": "in posizione, stop non ancora armato",
        "armed": "stop attivo",
        "error": "buy/stop cancellato, strategia ferma",
        "stopped": "fermato a mano",
        "done": "chiuso",
    }
    latest: dict[str, dict[str, Any]] = {}
    for trail in trails:
        if not isinstance(trail, dict):
            continue
        status = str(trail.get("status") or "")
        if status not in {"buying", "watching", "armed", "error"}:
            continue
        ticker = str(trail.get("ticker") or "?").upper()
        latest[ticker] = trail
    lines: list[str] = []
    for ticker, trail in latest.items():
        status = str(trail.get("status") or "")
        label = labels.get(status, status)
        extra = ""
        if status == "armed":
            level = trail.get("stop_level")
            if level is not None:
                extra = f" @ {level}"
        elif status == "watching":
            be = trail.get("breakeven")
            if be is not None:
                extra = f" · BE {be}"
        lines.append(f"{ticker}: {label}{extra}")
    return lines


def apply_telegram_trail(
    text: str, state_path: Path, watchlist_path: Path | None = None
) -> bool:
    m = TRAIL_RE.match(text.strip())
    if not m:
        return False
    ticker = m.group(1).upper()
    quantity = int(m.group(2))
    try:
        delta = float(m.group(3))
    except ValueError:
        _send_order_message(
            state_path, "⚠️ Delta non valido. Usa una percentuale, es. 2."
        )
        return True
    _send_order_message(
        state_path, start_step_trail(ticker, quantity, delta, state_path)
    )
    return True


def _on_step_trail_fill(
    state_path: Path,
    order: dict[str, Any],
    order_id: str,
    avg: Any,
    fee: Any,
) -> None:
    trails = _auto_trails(load_state(state_path))
    if not trails:
        return
    side = str(order.get("side") or "").upper()
    ticker = str(order.get("ticker") or "").upper()
    changed = False
    for trail in trails:
        status = str(trail.get("status") or "")
        if status == "buying" and side == "BUY":
            known_buy = str(trail.get("buy_order_id") or "")
            if known_buy and known_buy != order_id:
                continue
            if str(trail.get("ticker") or "").upper() != ticker:
                continue
            avg_f = _float_or_none(avg)
            if avg_f is None:
                avg_f = _float_or_none(order.get("avgPrice"))
            if avg_f is None:
                continue
            qty = _share_qty(trail.get("quantity")) or 0
            filled = _share_qty(order.get("filledQuantity"))
            if filled is not None:
                qty = filled
            if qty < 1:
                continue
            trail["buy_order_id"] = order_id
            trail["quantity"] = qty
            trail["avg_price"] = avg_f
            trail["breakeven"] = step_trail_breakeven(avg_f)
            trail["status"] = "watching"
            changed = True
            try:
                arm_at = float(trail["breakeven"]) * (
                    1.0 + float(trail.get("delta") or 0) / 100.0
                )
            except (TypeError, ValueError):
                arm_at = float(trail["breakeven"])
            _send_order_message(
                state_path,
                f"Trail {ticker}: fill @ {avg_f:g} · "
                f"break-even {trail['breakeven']:g} "
                f"(1% entrata + 1% uscita). "
                f"Stop si arma a {arm_at:g}.",
            )
            break
        if status in {"armed", "watching"} and side == "SELL":
            same_ticker = str(trail.get("ticker") or "").upper() == ticker
            if not same_ticker:
                continue
            stop_id = str(trail.get("stop_order_id") or "")
            trail_qty = _share_qty(trail.get("quantity")) or 0
            sold = _share_qty(order.get("filledQuantity")) or 0
            is_our_stop = bool(stop_id) and stop_id == order_id
            covers = sold >= trail_qty >= 1
            if not is_our_stop and not covers:
                continue
            if stop_id and stop_id != order_id:
                account_id = ibkr_get_account_id()
                if account_id:
                    _ibkr_delete_orders(account_id, [stop_id])
            trail["status"] = "done"
            trail["stop_order_id"] = None
            changed = True
            break
    if changed:
        _save_auto_trails(state_path, trails)


def _on_step_trail_dead(
    state_path: Path, order: dict[str, Any], order_id: str, status: Any
) -> None:
    trails = _auto_trails(load_state(state_path))
    if not trails:
        return
    changed = False
    label = str(status or "cancellato")
    ticker = str(order.get("ticker") or "").upper()
    for trail in trails:
        trail_ticker = str(trail.get("ticker") or "").upper()
        if (
            str(trail.get("status") or "") == "buying"
            and str(trail.get("buy_order_id") or "") == order_id
        ):
            trail["status"] = "error"
            changed = True
            _send_order_message(
                state_path,
                f"⚠️ Trail {trail.get('ticker')}: buy {label}, strategia fermata.",
            )
            break
        if (
            str(trail.get("status") or "") == "armed"
            and str(trail.get("stop_order_id") or "") == order_id
        ):
            trail["stop_order_id"] = None
            trail["stop_level"] = None
            trail["status"] = "watching"
            changed = True
            _send_order_message(
                state_path,
                f"⚠️ Trail {trail.get('ticker')}: stop {label}. "
                "Lo ripiazzo al prossimo tick se il prezzo è ancora sopra.",
            )
            break
        if (
            ticker
            and trail_ticker == ticker
            and str(trail.get("status") or "") == "buying"
            and not trail.get("buy_order_id")
        ):
            trail["status"] = "error"
            changed = True
            _send_order_message(
                state_path,
                f"⚠️ Trail {ticker}: buy {label}, strategia fermata.",
            )
            break
    if changed:
        _save_auto_trails(state_path, trails)


def apply_step_trail_price(state_path: Path, ticker: str, price: float) -> None:
    """Alza lo stop sul tick, senza aspettare il ciclo da 60s."""
    ticker = ticker.strip().upper()
    trails = _auto_trails(load_state(state_path))
    changed = False
    for trail in trails:
        if str(trail.get("ticker") or "").strip().upper() != ticker:
            continue
        if str(trail.get("status") or "") not in {"watching", "armed"}:
            continue
        breakeven = _float_or_none(trail.get("breakeven"))
        delta = _float_or_none(trail.get("delta"))
        try:
            qty = int(trail.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if breakeven is None or delta is None or qty < 1:
            continue
        wanted = step_trail_stop_price(price, breakeven, delta)
        if wanted is None:
            continue
        current = _float_or_none(trail.get("stop_level"))
        if current is not None and wanted <= current + 1e-9:
            continue
        stop_id = str(trail.get("stop_order_id") or "")
        if stop_id:
            known = load_state(state_path).get("known_order_status")
            if (
                isinstance(known, dict)
                and str(known.get(stop_id) or "").lower() == "filled"
            ):
                trail["status"] = "done"
                trail["stop_order_id"] = None
                changed = True
                continue
            err = ibkr_replace_stop(stop_id, ticker, qty, wanted)
            if err is not None:
                trail["stop_order_id"] = None
                trail["stop_level"] = None
                trail["status"] = "watching"
                changed = True
                _send_order_message(state_path, err)
                continue
        else:
            err, new_id = ibkr_place_stop(ticker, qty, wanted)
            if err is None and new_id:
                trail["stop_order_id"] = new_id
            if err is not None or not trail.get("stop_order_id"):
                if err is not None:
                    _send_order_message(state_path, err)
                continue
        if not trail.get("stop_order_id"):
            continue
        first = current is None
        trail["stop_level"] = wanted
        trail["status"] = "armed"
        changed = True
        if first:
            _send_order_message(
                state_path,
                f"🛡️ Trail {ticker}: stop attivato a {wanted:.2f} "
                f"(break-even). Prezzo {price:.2f}.",
            )
        else:
            _send_order_message(
                state_path,
                f"🛡️ Trail {ticker}: stop alzato a {wanted:.2f}. "
                f"Prezzo {price:.2f}.",
            )
    if changed:
        _save_auto_trails(state_path, trails)


def check_step_trails(state_path: Path) -> None:
    tickers: list[str] = []
    seen: set[str] = set()
    for trail in _auto_trails(load_state(state_path)):
        if str(trail.get("status") or "") not in {"watching", "armed"}:
            continue
        ticker = str(trail.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    for ticker in tickers:
        price = ibkr_get_price(ticker)
        if price is not None:
            apply_step_trail_price(state_path, ticker, price)


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


def _watchlist_tickers(watchlist_path: Path) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for item in load_watchlist(watchlist_path):
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _order_tickers(limit_only: bool = False) -> list[str] | None:
    orders = ibkr_get_active_orders()
    if orders is None:
        return None
    tickers: list[str] = []
    seen: set[str] = set()
    for order in orders:
        if not isinstance(order, dict):
            continue
        if limit_only and not _ibkr_is_limit_order(order):
            continue
        ticker = str(order.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _flow_ticker_buttons(tickers: list[str]) -> list[tuple[str, str]]:
    return [(ticker, f"flowticker:{ticker}") for ticker in tickers]


def _parse_ingresso_input(text: str) -> tuple[float, float] | None:
    match = INGRESSO_INPUT_RE.match(text.strip())
    if not match:
        return None
    try:
        low = parse_num(match.group(1))
        high_raw = match.group(2)
        high = parse_num(high_raw) if high_raw else low
    except (TypeError, ValueError):
        return None
    if low > high:
        low, high = high, low
    return low, high


def _complete_clear_flow(watchlist_path: Path, state_path: Path) -> None:
    _save_pending_flow(state_path, None)
    cleared = apply_telegram_clear("/clear", watchlist_path)
    count = len(cleared or [])
    if count:
        _send_flow_message(state_path, f"🧹 Watchlist svuotata ({count} ticker).")
    else:
        _send_flow_message(state_path, "🧹 Watchlist già vuota.")


def _strategy_param_list(name: str) -> list[dict[str, Any]]:
    spec = AUTO_STRATEGIES.get(str(name or "").strip().lower())
    if not spec:
        return []
    return [dict(param) for param in spec.get("params") or ()]


def _strategy_param_for_step(name: str, step: str) -> dict[str, Any] | None:
    for param in _strategy_param_list(name):
        if param.get("step") == step:
            return param
    return None


def _next_strategy_param(name: str, step: str) -> dict[str, Any] | None:
    params = _strategy_param_list(name)
    for index, param in enumerate(params):
        if param.get("step") == step and index + 1 < len(params):
            return params[index + 1]
    return None


def _prompt_strategy_param(
    flow: dict[str, Any], param: dict[str, Any], state_path: Path
) -> None:
    ticker = str(flow.get("ticker") or "").strip().upper()
    flow["step"] = param["step"]
    _save_pending_flow(state_path, flow)
    _send_flow_message(
        state_path, str(param["prompt"]).format(ticker=ticker or "?")
    )


def _begin_strategy_params(flow: dict[str, Any], state_path: Path) -> None:
    params = _strategy_param_list(str(flow.get("strategy") or ""))
    if not params:
        _save_pending_flow(state_path, None)
        _send_flow_message(state_path, "⚠️ Strategia non disponibile.")
        return
    _prompt_strategy_param(flow, params[0], state_path)


def _parse_strategy_param(param: dict[str, Any], raw: float) -> Any | None:
    kind = str(param.get("kind") or "")
    if kind == "shares":
        qty = int(raw)
        return qty if qty >= 1 else None
    if kind in {"percent", "number"}:
        return raw if raw > 0 else None
    return raw


def _finish_armed_strategy(
    flow: dict[str, Any], state_path: Path, watchlist_path: Path
) -> None:
    kind = str(flow.get("type") or "")
    ticker = str(flow.get("ticker") or "").strip().upper()
    qty = _share_qty(flow.get("quantity"))
    delta = _float_or_none(flow.get("delta"))
    if kind == "SETBUY":
        entry = _float_or_none(flow.get("entry"))
        strategy = str(flow.get("strategy") or "").strip().lower()
        if not ticker or entry is None or qty is None or delta is None:
            _save_pending_flow(state_path, None)
            _send_flow_message(state_path, "⚠️ Ordine incompleto, ricomincia.")
            return
        upsert_strategy_trigger(
            watchlist_path, ticker, entry, strategy, qty, delta
        )
        _save_pending_flow(state_path, None)
        label = AUTO_STRATEGIES.get(strategy, {}).get("label") or strategy.title()
        _send_flow_message(
            state_path,
            f"✅ {ticker} in watchlist: entry {entry:g} · "
            f"{label} {qty} az · Δ {delta:g}%. "
            "Parte da solo quando il prezzo tocca l'entry.",
        )
        return
    if qty is None or delta is None:
        _save_pending_flow(state_path, None)
        _send_flow_message(state_path, "⚠️ Ordine incompleto, ricomincia.")
        return
    _save_pending_flow(state_path, None)
    _send_order_message(
        state_path, start_step_trail(ticker, qty, delta, state_path)
    )


def _collect_strategy_param_text(
    flow: dict[str, Any],
    stripped: str,
    state_path: Path,
    watchlist_path: Path,
) -> bool:
    strategy = str(flow.get("strategy") or "").strip().lower()
    if not strategy:
        return False
    param = _strategy_param_for_step(strategy, str(flow.get("step") or ""))
    if param is None:
        return False
    raw = _parse_flow_number(stripped)
    if raw is None:
        _send_flow_message(state_path, "⚠️ Numero non valido, riprova.")
        return True
    parsed = _parse_strategy_param(param, raw)
    if parsed is None:
        _send_flow_message(state_path, "⚠️ Numero non valido, riprova.")
        return True
    flow[str(param["key"])] = parsed
    nxt = _next_strategy_param(strategy, str(param["step"]))
    if nxt is not None:
        _prompt_strategy_param(flow, nxt, state_path)
        return True
    _finish_armed_strategy(flow, state_path, watchlist_path)
    return True


def _start_guided_flow(
    kind: str, watchlist_path: Path, state_path: Path
) -> None:
    if kind == "CLEAR":
        if not _watchlist_tickers(watchlist_path):
            _save_pending_flow(state_path, None)
            _send_flow_message(state_path, "📭 Watchlist già vuota.")
            return
        flow = _new_pending_flow("CLEAR")
        flow["step"] = "confirm"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Svuotare tutta la watchlist?",
            [("Sì, svuota", "confirm:yes"), ("No", "confirm:no")],
        )
        return
    if kind == "HISTORY":
        flow = _new_pending_flow("HISTORY")
        flow["step"] = "days"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quanti giorni di storico?",
            [
                ("1 giorno", "days:1"),
                ("7 giorni", "days:7"),
                ("30 giorni", "days:30"),
            ],
        )
        return
    if kind == "CANCEL":
        tickers = _order_tickers()
        if tickers is None:
            _save_pending_flow(state_path, None)
            _send_flow_message(
                state_path, "⚠️ Impossibile leggere gli ordini aperti."
            )
            return
        if not tickers:
            _save_pending_flow(state_path, None)
            _send_flow_message(
                state_path, "📭 Nessun ordine attivo da annullare."
            )
            return
        flow = _new_pending_flow("CANCEL")
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quale ticker vuoi annullare?",
            _flow_ticker_buttons(tickers),
        )
        return
    if kind == "MODIFY":
        tickers = _order_tickers(limit_only=True)
        if tickers is None:
            _save_pending_flow(state_path, None)
            _send_flow_message(
                state_path, "⚠️ Impossibile leggere gli ordini aperti."
            )
            return
        if not tickers:
            _save_pending_flow(state_path, None)
            _send_flow_message(
                state_path, "📭 Nessun ordine a limite da modificare."
            )
            return
        flow = _new_pending_flow("MODIFY")
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quale ticker vuoi modificare?",
            _flow_ticker_buttons(tickers),
        )
        return
    if kind == "RM":
        tickers = _watchlist_tickers(watchlist_path)
        if not tickers:
            _save_pending_flow(state_path, None)
            _send_flow_message(state_path, "📭 Watchlist vuota.")
            return
        flow = _new_pending_flow("RM")
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quale ticker vuoi togliere?",
            _flow_ticker_buttons(tickers),
        )
        return
    if kind == "TRAIL":
        tickers = _watchlist_tickers(watchlist_path)
        flow = _new_pending_flow("TRAIL")
        flow["strategy"] = "trail"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quale ticker vuoi comprare?",
            _flow_ticker_buttons(tickers) if tickers else None,
        )
        return
    if kind == "STOPTRAIL":
        actives = _active_step_trails(state_path)
        if not actives:
            _save_pending_flow(state_path, None)
            _send_flow_message(state_path, "📭 Nessun Trail attivo.")
            return
        tickers: list[str] = []
        seen: set[str] = set()
        for trail in actives:
            name = str(trail.get("ticker") or "").strip().upper()
            if not name or name in seen:
                continue
            seen.add(name)
            tickers.append(name)
        if len(tickers) == 1:
            _save_pending_flow(state_path, None)
            _send_order_message(state_path, stop_step_trail(state_path, tickers[0]))
            return
        flow = _new_pending_flow("STOPTRAIL")
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            "Quale Trail vuoi fermare?",
            _flow_ticker_buttons(tickers),
        )
        return
    prompts = {
        "SETBUY": "Quale ticker vuoi mettere in Set buy?",
        "PRICE": "Di quale ticker vuoi il prezzo?",
    }
    prompt = prompts.get(kind)
    if not prompt:
        return
    flow = _new_pending_flow(kind)
    _save_pending_flow(state_path, flow)
    shortcuts = _watchlist_tickers(watchlist_path)
    _send_flow_message(
        state_path,
        prompt,
        _flow_ticker_buttons(shortcuts) if shortcuts else None,
    )


def _advance_flow_after_ticker(
    flow: dict[str, Any],
    ticker: str,
    state_path: Path,
    watchlist_path: Path,
) -> None:
    kind = str(flow.get("type") or "")
    flow["ticker"] = ticker
    if kind == "SETBUY":
        flow["step"] = "entry"
        _save_pending_flow(state_path, flow)
        spot = ibkr_get_price(ticker)
        if spot is not None:
            prompt = (
                f"{ticker} ora quota {spot:g}. "
                "Prezzo Set buy? Deve stare sotto."
            )
        else:
            prompt = (
                f"{ticker}: prezzo Set buy? Deve stare sotto il prezzo attuale."
            )
        _send_flow_message(state_path, prompt)
        return
    if kind == "PRICE":
        _save_pending_flow(state_path, None)
        apply_telegram_price(f"/prezzo {ticker}", state_path)
        return
    if kind == "QUOTE":
        _show_quote_for_ticker(ticker, flow, state_path)
        return
    if kind == "CANCEL":
        _save_pending_flow(state_path, None)
        _send_order_message(state_path, ibkr_cancel_order(ticker))
        return
    if kind == "MODIFY":
        flow["step"] = "price"
        _save_pending_flow(state_path, flow)
        _send_flow_message(state_path, f"{ticker}: nuovo prezzo limite?")
        return
    if kind == "TRAIL":
        flow["strategy"] = "trail"
        _begin_strategy_params(flow, state_path)
        return
    if kind == "STOPTRAIL":
        _save_pending_flow(state_path, None)
        _send_order_message(state_path, stop_step_trail(state_path, ticker))
        return
    if kind == "RM":
        _save_pending_flow(state_path, None)
        gone = apply_telegram_remove(f"/rm {ticker}", watchlist_path)
        if gone:
            _send_flow_message(
                state_path, f"🗑️ {ticker} rimosso dalla watchlist."
            )
        else:
            _send_flow_message(
                state_path, f"⚠️ {ticker} non era in watchlist."
            )
        return
    if kind == "BUY":
        flow["step"] = "size_type"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path, "Azioni o Dollari?", _size_type_buttons(flow)
        )


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


def process_pending_flow_text(
    text: str, state_path: Path, watchlist_path: Path | None = None
) -> bool:
    state = load_state(state_path)
    flow = _pending_flow(state)
    if flow is None:
        return False
    wpath = DEFAULT_WATCHLIST if watchlist_path is None else watchlist_path
    kind = str(flow.get("type") or "")
    step = flow.get("step")
    stripped = text.strip()
    if step == "ticker":
        if kind == "SELL":
            return False
        match = FLOW_TICKER_RE.match(stripped)
        ticker = match.group(1).upper() if match else ""
        if not ticker or not is_valid_symbol(ticker):
            _send_flow_message(state_path, "⚠️ Ticker non valido, riprova.")
            return True
        _advance_flow_after_ticker(flow, ticker, state_path, wpath)
        return True
    if _collect_strategy_param_text(flow, stripped, state_path, wpath):
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
    if step == "entry" and kind == "SETBUY":
        value = _parse_flow_number(stripped)
        if value is None:
            _send_flow_message(state_path, "⚠️ Prezzo non valido, riprova.")
            return True
        ticker = str(flow.get("ticker") or "").strip().upper()
        spot = ibkr_get_price(ticker)
        if spot is None:
            _send_flow_message(
                state_path,
                f"⚠️ Impossibile leggere il prezzo di {ticker}. Riprova.",
            )
            return True
        if value >= spot:
            _send_flow_message(
                state_path,
                f"⚠️ L'entry deve stare sotto il prezzo attuale ({spot:g}).",
            )
            return True
        flow["entry"] = value
        flow["step"] = "strategy"
        _save_pending_flow(state_path, flow)
        _send_flow_message(
            state_path,
            f"{ticker} entry {value:g}: quale strategia di "
            "trading automatico vuoi far partire quando tocca?",
            auto_strategy_pick_buttons(),
        )
        return True
    if step == "strategy" and kind == "SETBUY":
        _send_flow_message(
            state_path,
            "Scegli una strategia di trading automatico dai bottoni.",
            auto_strategy_pick_buttons(),
        )
        return True
    if step == "price":
        value = _parse_flow_number(stripped)
        if value is None:
            _send_flow_message(state_path, "⚠️ Prezzo non valido, riprova.")
            return True
        ticker = str(flow.get("ticker") or "").strip().upper()
        if kind == "MODIFY":
            _save_pending_flow(state_path, None)
            _send_order_message(state_path, ibkr_modify_order(ticker, value))
            return True
        flow["price"] = value
        _save_pending_flow(state_path, flow)
        _execute_flow_order(flow, state_path)
        _save_pending_flow(state_path, None)
        return True
    if step == "days":
        try:
            days = int(stripped)
        except ValueError:
            _send_flow_message(
                state_path, "⚠️ Inserisci un numero di giorni, es. 7"
            )
            return True
        if days < 1 or days > 365:
            _send_flow_message(
                state_path, "⚠️ I giorni devono essere tra 1 e 365."
            )
            return True
        _save_pending_flow(state_path, None)
        apply_telegram_history(f"/storico {days}", state_path)
        return True
    if step == "confirm" and kind == "CLEAR":
        low = stripped.lower()
        if low in {"si", "sì", "yes", "s"}:
            _complete_clear_flow(wpath, state_path)
            return True
        if low in {"no", "n"}:
            _save_pending_flow(state_path, None)
            _show_named_menu(telegram_chat_id(), None, state_path, "watchlist")
            return True
        _send_flow_message(
            state_path, "Conferma con Sì o No, oppure usa i bottoni."
        )
        return True
    return False


def _handle_start_menu_callback(
    data: str,
    chat_id: Any,
    message_id: int | None,
    state_path: Path,
) -> dict[str, Any] | None:
    kind = data.split(":", 1)[1].strip()
    if kind == "main":
        _clear_pending_flow(state_path)
        _show_named_menu(chat_id, message_id, state_path, "main", reset=True)
        return None
    if kind == "back":
        _here, stack = _menu_nav_state(state_path)
        previous = stack.pop() if stack else "main"
        if previous not in MENU_PAGES:
            previous = "main"
        _save_menu_nav(state_path, previous, stack)
        _show_named_menu(chat_id, message_id, state_path, previous)
        return None
    if kind in MENU_PAGES and kind != "main":
        _show_named_menu(chat_id, message_id, state_path, kind, push=True)
        return None
    return None


def process_callback_query(
    callback_data: str,
    chat_id: Any,
    callback_query_id: str,
    state_path: Path,
    message_id: int | None = None,
    watchlist_path: Path | None = None,
) -> dict[str, Any] | None:
    """Aggiorna pending_flow o il menu /start. Non chiama IBKR
    sulle azioni lente: quelle tornano al caller.

    Ritorna None se non serve altro, altrimenti un'azione da eseguire
    fuori dal lock:

    - {"action": "execute_order", "flow": {...}} → _execute_flow_order
    - {"action": "sell_all", "ticker": str, "price": float|None} → ibkr_sell_all
    - {"action": "<menu action>"} → apply_menu_action
    """
    answer_callback_query(callback_query_id)
    wpath = DEFAULT_WATCHLIST if watchlist_path is None else watchlist_path
    if isinstance(message_id, int):
        _remember_bot_message(state_path, message_id)
    data = callback_data.strip()
    if data.startswith("menu:"):
        return _handle_start_menu_callback(
            data, chat_id, message_id, state_path
        )
    if data.startswith("action:"):
        kind = data.split(":", 1)[1].strip()
        if kind in MENU_ACTION_KINDS:
            return {"action": kind}
        return None
    if data.startswith("quotefield:") or data == "quote:go":
        selected = _load_quote_fields(state_path)
        if data.startswith("quotefield:"):
            key = data.split(":", 1)[1].strip()
            if key not in QUOTE_FIELDS:
                return None
            if key in selected:
                selected = [item for item in selected if item != key]
            else:
                selected.append(key)
            selected = _quote_selected_fields(selected)
            _save_quote_fields(state_path, selected)
            _send_flow_message(
                state_path,
                MENU_INFO_TEXT,
                _quote_picker_buttons(selected),
            )
            return None
        if not selected:
            _send_flow_message(
                state_path,
                "⚠️ Seleziona almeno un campo, poi Mostra.",
                _quote_picker_buttons([]),
            )
            return None
        flow = _new_pending_flow("QUOTE")
        flow["quote_fields"] = selected
        _save_pending_flow(state_path, flow)
        shortcuts = _watchlist_tickers(wpath)
        _send_flow_message(
            state_path,
            "Di quale ticker vuoi le info?",
            _flow_ticker_buttons(shortcuts) if shortcuts else None,
        )
        return None
    flow = _pending_flow(load_state(state_path))
    if flow is None:
        return None
    step = flow.get("step")
    if data.startswith("flowticker:"):
        if step != "ticker":
            return None
        ticker = data.split(":", 1)[1].strip().upper()
        if not ticker:
            return None
        _advance_flow_after_ticker(flow, ticker, state_path, wpath)
        return None
    if data.startswith("strategy:") and step == "strategy":
        name = data.split(":", 1)[1].strip().lower()
        if name not in AUTO_STRATEGIES:
            return None
        flow["strategy"] = name
        _begin_strategy_params(flow, state_path)
        return None
    if data.startswith("days:") and step == "days":
        try:
            days = int(data.split(":", 1)[1])
        except ValueError:
            return None
        if days < 1 or days > 365:
            return None
        _save_pending_flow(state_path, None)
        apply_telegram_history(f"/storico {days}", state_path)
        return None
    if data.startswith("confirm:") and str(flow.get("type") or "") == "CLEAR":
        choice = data.split(":", 1)[1].strip().lower()
        if choice == "yes":
            _complete_clear_flow(wpath, state_path)
        elif choice == "no":
            _save_pending_flow(state_path, None)
            _show_named_menu(chat_id, message_id, state_path, "watchlist")
        return None
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
    confirmed, err = _confirm_order_replies_detail(result)
    if confirmed is None:
        return _order_not_confirmed(ticker, err)
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
    _preview_loading(state_path, "positions_message_id")
    positions = ibkr_get_positions()
    if positions is None:
        _send_replacing_message(
            state_path,
            "positions_message_id",
            "⚠️ Impossibile leggere le posizioni al momento.",
        )
        return True
    lines = ["📊 Posizioni aperte:", ""]
    for pos in _open_positions(positions):
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
    _preview_loading(state_path, "orders_message_id")
    orders = ibkr_get_active_orders()
    trail_lines = format_trail_status_lines(_auto_trails(load_state(state_path)))
    trail_note = ""
    if trail_lines:
        trail_note = "\n\nTrail:\n" + "\n".join(trail_lines)
    if orders is None:
        body = "⚠️ Impossibile leggere gli ordini al momento." + trail_note
    elif not orders:
        body = "📭 Nessun ordine attivo." + trail_note
    else:
        lines = [_fmt_order_line(o) for o in orders if isinstance(o, dict)]
        if not lines:
            body = "📭 Nessun ordine attivo." + trail_note
        else:
            body = "📋 Ordini attivi:\n\n" + "\n".join(lines) + trail_note
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


def apply_telegram_history(text: str, state_path: Path | None = None) -> bool:
    match = HISTORY_RE.match(text.strip())
    if not match:
        return False
    path = DEFAULT_STATE if state_path is None else state_path
    days = int(match.group(1))
    trades = ibkr_get_trades()
    if trades is None:
        _send_replacing_message(
            path, "history_message_id", "⚠️ Impossibile leggere lo storico ordini al momento."
        )
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
        _send_replacing_message(
            path,
            "history_message_id",
            f"📭 Nessun ordine eseguito negli ultimi {days} giorni.",
        )
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
    _send_replacing_message(path, "history_message_id", body)
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


def apply_order_status_updates(orders: list[Any], state_path: Path) -> None:
    """WebSocket e poll da 60s passano di qui: un fill, un solo ✅ ESEGUITO."""
    state = load_state(state_path)
    raw_known = state.get("known_order_status")
    known: dict[str, Any] = dict(raw_known) if isinstance(raw_known, dict) else {}
    for order in orders:
        if not isinstance(order, dict) or order.get("orderId") is None:
            continue
        order_id = str(order["orderId"])
        status = order.get("status")
        prev = known.get(order_id)
        if prev != "Filled" and status == "Filled":
            fee = _commission_from_trades(order, order_id)
            avg = order.get("avgPrice", order.get("price", "n/d"))
            _send_order_message(
                state_path,
                f"✅ ESEGUITO: {order.get('side')} {order.get('filledQuantity')} "
                f"{order.get('ticker')} @ {avg} · fee: {fee}",
            )
            _on_step_trail_fill(state_path, order, order_id, avg, fee)
            known[order_id] = status
            state = load_state(state_path)
            state["known_order_status"] = known
            save_state(state_path, state)
            commit_state_to_git()
        elif (
            prev != "Filled"
            and prev != status
            and str(status or "").lower() in _STEP_TRAIL_DEAD
        ):
            _on_step_trail_dead(state_path, order, order_id, status)
        known[order_id] = status
    state = load_state(state_path)
    state["known_order_status"] = known
    save_state(state_path, state)


def check_order_fills(state_path: Path) -> None:
    data = ibkr_get("/v1/api/iserver/account/orders")
    if data is None:
        return
    orders = data.get("orders") if isinstance(data, dict) else None
    if not isinstance(orders, list):
        return
    apply_order_status_updates(orders, state_path)


def ibkr_ws_url() -> str:
    base = IBKR_BASE_URL.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/v1/api/ws"
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/v1/api/ws"
    return base + "/v1/api/ws"


def ibkr_tickle() -> bool:
    return ibkr_get("/v1/api/tickle") is not None


def orders_from_ws_message(raw: Any) -> list[dict[str, Any]]:
    data: Any = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped or stripped in {"tic", "pong"}:
            return []
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        return [
            item
            for item in data
            if isinstance(item, dict) and item.get("orderId") is not None
        ]
    if not isinstance(data, dict):
        return []
    topic = str(data.get("topic") or "")
    if topic and not topic.startswith("sor"):
        return []
    args = data.get("args")
    if isinstance(args, list):
        return [
            item
            for item in args
            if isinstance(item, dict) and item.get("orderId") is not None
        ]
    if isinstance(args, dict):
        if args.get("orderId") is not None:
            return [args]
        inner = args.get("orders")
        if isinstance(inner, list):
            return [
                item
                for item in inner
                if isinstance(item, dict) and item.get("orderId") is not None
            ]
    if data.get("orderId") is not None:
        return [data]
    return []


def _parse_ws_payload(raw: Any) -> Any:
    data: Any = raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped or stripped in {"tic", "pong"}:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return data


def market_price_from_ws_message(raw: Any) -> tuple[str | None, float | None]:
    data = _parse_ws_payload(raw)
    if not isinstance(data, dict):
        return None, None
    topic = str(data.get("topic") or "")
    if topic and not topic.startswith("smd"):
        return None, None
    conid = str(data.get("conid") or data.get("conidEx") or "").strip()
    if not conid and topic.startswith("smd"):
        parts = topic.split("+")
        if len(parts) >= 2 and parts[1]:
            conid = parts[1].strip()
    raw_px = data.get("31", data.get("_price"))
    price = _float_or_none(raw_px)
    if price is None and raw_px is not None:
        match = _IBKR_PRICE_RE.search(str(raw_px).replace(",", "."))
        if match:
            try:
                price = float(match.group(0))
            except ValueError:
                price = None
    if not conid or price is None:
        return None, None
    return conid, price


def _ticker_for_conid(conid: str) -> str | None:
    needle = str(conid)
    for key, value in _CONID_CACHE.items():
        if str(value) == needle:
            return str(key).strip().upper()
    return None


def trail_md_wanted(state_path: Path) -> dict[str, str]:
    """conid IBKR → ticker, per Trail e entry in attesa."""
    wanted: dict[str, str] = {}
    for trail in _auto_trails(load_state(state_path)):
        if str(trail.get("status") or "") not in {"watching", "armed"}:
            continue
        ticker = str(trail.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        conid = ibkr_lookup_conid(ticker)
        if conid:
            wanted[str(conid)] = ticker
    for item in load_watchlist(DEFAULT_WATCHLIST):
        if str(item.get("status") or "") != "waiting":
            continue
        if not item.get("strategy"):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        conid = ibkr_lookup_conid(ticker)
        if conid:
            wanted[str(conid)] = ticker
    return wanted


def sync_trail_md_subs(
    sock: Any, subscribed: set[str], state_path: Path
) -> dict[str, str]:
    wanted = trail_md_wanted(state_path)
    for conid in list(subscribed - set(wanted)):
        try:
            sock.send(f"umd+{conid}+{{}}")
        except Exception:
            pass
        subscribed.discard(conid)
    for conid in wanted:
        if conid in subscribed:
            continue
        sock.send(f'smd+{conid}+{{"fields":["31"]}}')
        subscribed.add(conid)
    return wanted


def handle_ibkr_ws_message(
    raw: Any,
    state_path: Path,
    conid_tickers: dict[str, str] | None = None,
) -> None:
    orders = orders_from_ws_message(raw)
    if orders:
        apply_order_status_updates(orders, state_path)
        return
    conid, price = market_price_from_ws_message(raw)
    if conid is None or price is None:
        return
    ticker = None
    if conid_tickers:
        ticker = conid_tickers.get(str(conid))
    if not ticker:
        ticker = _ticker_for_conid(conid)
    if ticker:
        apply_step_trail_price(state_path, ticker, price)
        apply_watchlist_trigger_price(DEFAULT_WATCHLIST, state_path, ticker, price)


def _open_ibkr_ws() -> Any:
    try:
        import ssl

        import websocket
    except ImportError:
        return None
    sock = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
    sock.settimeout(30)
    sock.connect(ibkr_ws_url())
    return sock


def run_ibkr_order_socket(
    state_path: Path,
    *,
    opener: Any = None,
    stop: threading.Event | None = None,
    pause: float = 5.0,
    lock: threading.Lock | None = None,
) -> None:
    """WebSocket IBKR: fill ordini + tick prezzi per alzare i Trail."""
    held = lock if lock is not None else nullcontext()
    open_sock = opener if opener is not None else _open_ibkr_ws
    while stop is None or not stop.is_set():
        sock: Any = None
        try:
            ibkr_tickle()
            ibkr_get("/v1/api/iserver/account/orders")
            sock = open_sock()
            if sock is None:
                time.sleep(pause)
                continue
            sock.send("sor+{}")
            subscribed: set[str] = set()
            md_map: dict[str, str] = {}
            with held:
                md_map = sync_trail_md_subs(sock, subscribed, state_path)
            last_ping = time.monotonic()
            while stop is None or not stop.is_set():
                now = time.monotonic()
                if now - last_ping >= 50:
                    sock.send("tic")
                    ibkr_tickle()
                    last_ping = now
                    with held:
                        md_map = sync_trail_md_subs(sock, subscribed, state_path)
                raw = sock.recv()
                if raw in (None, "", b""):
                    break
                with held:
                    handle_ibkr_ws_message(raw, state_path, md_map)
                    md_map = sync_trail_md_subs(sock, subscribed, state_path)
        except Exception as exc:
            print(f"IBKR websocket: {exc}", file=sys.stderr)
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
        if stop is not None and stop.is_set():
            return
        time.sleep(pause)


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
            line = f"📢 {title}\n\n{body}"
        elif title:
            line = f"📢 {title}"
        elif body:
            line = f"📢 {body}"
        else:
            known.add(nid)
            continue
        if _pending_flow(load_state(state_path)) is None:
            deliver_text(state_path, line, with_nav=True)
        known.add(nid)
    state = load_state(state_path)
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


def apply_telegram_set(
    text: str, watchlist_path: Path, state_path: Path | None = None
) -> str | list[str] | None:
    """Livelli /set /settarget /setstop non esistono più."""
    del text, watchlist_path, state_path
    return None


def apply_telegram_set_field(
    text: str, watchlist_path: Path, state_path: Path | None = None
) -> str | list[str] | None:
    """I comandi /setbuy /settarget /setstop non scrivono più livelli."""
    del text, watchlist_path, state_path
    return None


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
    payload: dict[str, Any] = {"chat_id": chat_id, "text": clip_text(text)}
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


def edit_telegram_message(
    chat_id: Any,
    message_id: int,
    text: str,
    buttons: list[tuple[str, str]] | None = None,
) -> bool:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": clip_text(text),
        "reply_markup": {
            "inline_keyboard": [
                [{"text": label, "callback_data": data}] for label, data in (buttons or [])
            ]
        },
    }
    try:
        telegram_api("editMessageText", payload, timeout=12)
        return True
    except Exception as exc:
        return _is_not_modified(exc)


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
    if apply_telegram_start(text, state_path):
        pass
    elif apply_telegram_buy_flow_start(text, state_path):
        pass
    elif apply_telegram_sell_flow_start(text, state_path):
        pass
    elif process_pending_flow_text(text, state_path, watchlist_path):
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
    elif apply_telegram_trail(text, state_path, watchlist_path):
        pass
    elif apply_telegram_cancel_order(text, state_path):
        pass
    elif apply_telegram_modify_order(text, state_path):
        pass
    elif apply_telegram_positions(text, state_path):
        pass
    elif apply_telegram_orders(text, state_path):
        pass
    elif apply_telegram_history(text, state_path):
        pass
    else:
        cleared = apply_telegram_clear(text, watchlist_path)
        if cleared is not None:
            removed.extend(cleared)
        else:
            set_ticker = apply_telegram_set(text, watchlist_path, state_path)
            if set_ticker is not None:
                if isinstance(set_ticker, str):
                    added.append(set_ticker)
            else:
                field_ticker = apply_telegram_set_field(text, watchlist_path, state_path)
                if field_ticker is not None:
                    if isinstance(field_ticker, str):
                        added.append(field_ticker)
                else:
                    gone = apply_telegram_remove(text, watchlist_path)
                    if gone:
                        removed.append(gone)
                    elif not is_noise_text(text):
                        # I ticket Trader non finiscono più in watchlist.
                        pass
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
                    gone = apply_telegram_remove(text, watchlist_path)
                    if gone:
                        removed.append(gone)
                        items = load_watchlist(watchlist_path)
            if should_delete_chat_message(text) and isinstance(mid, int):
                delete_telegram_message(mid)
        if added or removed:
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
    return len(added) + len(removed)


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
    """Scadenza record alert. Non cancella l'unico messaggio del bot."""
    state = load_state(state_path)
    live_id = _bot_message_id(state)
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
            if isinstance(mid, int) and mid != live_id:
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
    _push_result_nav(state_path)
    mid = deliver_text(state_path, text, with_nav=True)
    if isinstance(mid, int):
        record_order_message(state_path, mid)


def _send_flow_message(
    state_path: Path,
    text: str,
    buttons: list[tuple[str, str]] | None = None,
) -> int | None:
    shown = list(buttons or [])
    shown.extend(MENU_NAV_BUTTONS)
    mid = deliver_text(state_path, text, shown)
    if isinstance(mid, int):
        record_order_message(state_path, mid, ttl=FLOW_MESSAGE_TTL)
    return mid


def expire_order_messages(state_path: Path, now: datetime | None = None) -> None:
    """Scadenza record. Non cancella l'unico messaggio del bot."""
    state = load_state(state_path)
    live_id = _bot_message_id(state)
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
            if isinstance(mid, int) and mid != live_id:
                delete_telegram_message(mid)
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
    """Gli alert Telegram di ingresso/stop/target non esistono più."""
    del item, kind, line, active, fired, state_path
    return


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


def _run_auto_strategy(
    ticker: str, item: dict[str, Any], state_path: Path
) -> str:
    strategy = str(item.get("strategy") or "").strip().lower()
    if strategy == "trail":
        qty = _share_qty(item.get("quantity"))
        delta = _float_or_none(item.get("delta"))
        if qty is None or delta is None:
            return f"⚠️ Trail incompleto per {ticker}."
        return start_step_trail(ticker, qty, delta, state_path)
    return f"⚠️ Strategia {strategy or '?'} non ancora disponibile."


def upsert_strategy_trigger(
    watchlist_path: Path,
    ticker: str,
    entry: float,
    strategy: str,
    quantity: int,
    delta: float,
) -> None:
    ticker = ticker.strip().upper()
    items = load_watchlist(watchlist_path)
    next_items = [
        item
        for item in items
        if str(item.get("ticker") or "").strip().upper() != ticker
    ]
    next_items.append(
        {
            "ticker": ticker,
            "entry": entry,
            "strategy": strategy,
            "quantity": quantity,
            "delta": delta,
            "params": {"quantity": quantity, "delta": delta},
            "status": "waiting",
        }
    )
    save_watchlist(watchlist_path, next_items)


def fire_watchlist_triggers(
    items: list[dict[str, Any]],
    prices: dict[str, float],
    state_path: Path,
    watchlist_path: Path | None = None,
) -> None:
    wpath = DEFAULT_WATCHLIST if watchlist_path is None else watchlist_path
    changed = False
    for item in items:
        if str(item.get("status") or "") != "waiting":
            continue
        strategy = str(item.get("strategy") or "").strip().lower()
        if strategy not in AUTO_STRATEGIES:
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        entry = _float_or_none(item.get("entry"))
        price = prices.get(ticker)
        if not ticker or entry is None or price is None:
            continue
        if price > entry + 1e-9:
            continue
        item["status"] = "fired"
        changed = True
        result = _run_auto_strategy(ticker, item, state_path)
        _send_order_message(
            state_path,
            f"🎯 {ticker} ha toccato entry {entry:g} @ {price:g}.\n{result}",
        )
    if changed:
        save_watchlist(wpath, items)


def apply_watchlist_trigger_price(
    watchlist_path: Path, state_path: Path, ticker: str, price: float
) -> None:
    ticker = ticker.strip().upper()
    items = load_watchlist(watchlist_path)
    fire_watchlist_triggers(items, {ticker: price}, state_path, watchlist_path)


def cycle(
    items: list[dict[str, Any]],
    fired: dict[tuple[str, str, str], str | None],
    state_path: Path,
    lock: threading.Lock | None = None,
    watchlist_path: Path | None = None,
) -> None:
    del fired
    tickers = list(dict.fromkeys(it["ticker"] for it in items if it.get("ticker")))
    prices = fetch_prices(tickers)
    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    held = lock if lock is not None else nullcontext()
    wpath = DEFAULT_WATCHLIST if watchlist_path is None else watchlist_path
    with held:
        for it in items:
            ticker = it.get("ticker") or "?"
            price = prices.get(str(ticker))
            px = f"{price:.2f}" if price is not None else "n/d"
            print(f"{now}  {ticker:<6} {px:>8}  {fmt_ticket_line(it)}", flush=True)
        fire_watchlist_triggers(items, prices, state_path, wpath)


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
            f"Telegram chat {telegram_chat_id()}: Set buy arma un entry. "
            "Quando il prezzo lo tocca parte Trail. "
            "Bot nel gruppo, Group Privacy OFF su @BotFather, un /start nel gruppo.",
            flush=True,
        )
    print(
        "Watchlist: entry sotto spot → Trail. Non è consulenza. Ctrl+C esce.",
        flush=True,
    )
    try:
        while True:
            ingest_telegram(path, state_path)
            ingest_telegram_userbot(path, state_path)
            expire_sent_alerts(state_path)
            items = load_watchlist(path)
            fired.update(load_fired(load_state(state_path)))
            if not items:
                print("Watchlist vuota. Usa Set buy per armare un entry.", flush=True)
            else:
                cycle(items, fired, state_path, watchlist_path=path)
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
            "Watchlist Telegram/IBKR: Set buy arma un entry sotto spot. "
            "Al tocco parte Trail. Non è consulenza finanziaria."
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
        help="Compatibilità: il ciclo entry gira sempre, 24/7",
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
