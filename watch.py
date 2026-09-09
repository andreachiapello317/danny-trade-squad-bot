#!/usr/bin/env python3
"""Ticket Trader → watchlist automatica da Telegram. Prezzo Yahoo vs livelli.

Non piazza ordini. Non è consulenza finanziaria.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

DEFAULT_WATCHLIST = Path("watchlist.json")
DEFAULT_STATE = Path("watch_state.json")
DEFAULT_INTERVAL = 60
DEFAULT_CHAT_ID = "-1003929227957"
SINGLE_TOUCH_PCT = 0.0015
WATCH_TZ = ZoneInfo("Europe/Rome")
WATCH_HOUR_START = 15
WATCH_HOUR_END = 22  # inclusivo: 15:00–22:59 ora italiana
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


def parse_num(raw: str) -> float:
    return float(raw.strip().replace(",", "."))


def to_yahoo(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


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
    tf = item.get("tf") or "—"
    motivo = (item.get("motivo") or "").strip()
    extra = f"  {motivo}" if motivo else ""
    return (
        f"{item['ticker']:<6} {tf:<9}  "
        f"ing {fmt_ingresso(item):<12} "
        f"stop {fmt_level(item.get('stop')):<8} "
        f"tgt {fmt_level(item.get('target'))}{extra}"
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


def telegram_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


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


def load_fired(state: dict[str, Any]) -> dict[tuple[str, str, str], bool]:
    raw = state.get("fired")
    if not isinstance(raw, dict):
        return {}
    out: dict[tuple[str, str, str], bool] = {}
    for k, v in raw.items():
        if not v or not isinstance(k, str):
            continue
        parts = k.split("|")
        if len(parts) == 3:
            out[(parts[0], parts[1], parts[2])] = True
    return out


def dump_fired(fired: dict[tuple[str, str, str], bool]) -> dict[str, bool]:
    return {fired_key_str(k): True for k, v in fired.items() if v}


def persist_fired(state_path: Path, fired: dict[tuple[str, str, str], bool]) -> None:
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


def in_ingresso(price: float, low: float | None, high: float | None) -> bool:
    if low is None:
        return False
    if high is None or high == low:
        tol = max(0.01, abs(low) * SINGLE_TOUCH_PCT)
        return abs(price - low) <= tol
    return low <= price <= high


def fetch_price(ticker: str) -> float | None:
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


def fetch_prices(tickers: list[str]) -> dict[str, float | None]:
    return {t: fetch_price(t) for t in tickers}


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


def send_telegram(text: str) -> None:
    if not telegram_token():
        return
    try:
        telegram_api("sendMessage", {"chat_id": telegram_chat_id(), "text": text}, timeout=12)
    except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
        print(f"Telegram: invio fallito ({exc})", file=sys.stderr)


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
    tickets, max_id = tickets_from_updates(updates, telegram_chat_id())
    if max_id is not None:
        state["telegram_offset"] = max_id + 1
        save_state(state_path, state)
    if not tickets:
        return 0
    items = load_watchlist(watchlist_path)
    for ticket in tickets:
        items = upsert(items, ticket)
        print(f"Ticket  {fmt_ticket_line(ticket)}", flush=True)
    save_watchlist(watchlist_path, items)
    return len(tickets)


def alert_key(item: dict[str, Any], kind: str) -> tuple[str, str, str]:
    return (item.get("ticker") or "", item.get("tf") or "", kind)


def maybe_alert(
    item: dict[str, Any],
    kind: str,
    line: str,
    active: bool,
    fired: dict[tuple[str, str, str], bool],
) -> None:
    key = alert_key(item, kind)
    if active:
        if not fired.get(key):
            print(line, flush=True)
            send_telegram(line)
            fired[key] = True
    else:
        fired[key] = False


def cycle(items: list[dict[str, Any]], fired: dict[tuple[str, str, str], bool]) -> None:
    tickers = list(dict.fromkeys(it["ticker"] for it in items if it.get("ticker")))
    prices = fetch_prices(tickers)
    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    for it in items:
        ticker = it["ticker"]
        price = prices.get(ticker)
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
        in_band = in_ingresso(price, lo, hi)
        maybe_alert(
            it,
            "ingresso",
            f"ALERT {ticker} ingresso {price:.2f} ({fmt_ingresso(it)}){suffix}",
            in_band,
            fired,
        )

        stop = it.get("stop")
        if stop is not None:
            maybe_alert(
                it,
                "stop",
                f"ALERT {ticker} stop {price:.2f} (<= {fmt_level(stop)}){suffix}",
                price <= float(stop),
                fired,
            )

        target = it.get("target")
        if target is not None:
            maybe_alert(
                it,
                "target",
                f"ALERT {ticker} target {price:.2f} (>= {fmt_level(target)}){suffix}",
                price >= float(target),
                fired,
            )


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
            items = load_watchlist(path)
            if not items:
                print("Watchlist vuota. In attesa dei ticket Trader su Telegram.", flush=True)
            else:
                cycle(items, fired)
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
