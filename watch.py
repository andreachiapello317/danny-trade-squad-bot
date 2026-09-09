#!/usr/bin/env python3
"""Ticket Trader → watchlist. Confronta il prezzo Yahoo con i livelli già sul ticket.

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

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

DEFAULT_WATCHLIST = Path("watchlist.json")
DEFAULT_INTERVAL = 60
DEFAULT_CHAT_ID = "-1003929227957"
SINGLE_TOUCH_PCT = 0.0015

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


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID).strip() or DEFAULT_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"Telegram: invio fallito ({exc})", file=sys.stderr)


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
    fired: dict[tuple[str, str, str], bool] = {}
    print(
        "Prezzi vs livelli del ticket. Non è consulenza. Ctrl+C esce.",
        flush=True,
    )
    try:
        while True:
            items = load_watchlist(path)
            if not items:
                print("Watchlist vuota. python watch.py add", flush=True)
            else:
                cycle(items, fired)
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
            "Ticket Trader (Telegram) → watchlist. "
            "Controlla il prezzo vs ingresso/stop/target. "
            "Non piazza ordini. Non è consulenza finanziaria."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", parents=[common], help="Aggiungi ticket: stdin o file")
    add_p.add_argument("files", nargs="*", help="File testo. Vuoto = stdin")
    add_p.set_defaults(func=cmd_add)

    list_p = sub.add_parser("list", parents=[common], help="Mostra la watchlist")
    list_p.set_defaults(func=cmd_list)

    rm_p = sub.add_parser("remove", parents=[common], help="Togli un ticker (es. AMD)")
    rm_p.add_argument("ticker", help="Ticker, es. AMD")
    rm_p.set_defaults(func=cmd_remove)

    run_p = sub.add_parser("run", parents=[common], help="Osserva i prezzi fino a Ctrl+C")
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
    run_p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
