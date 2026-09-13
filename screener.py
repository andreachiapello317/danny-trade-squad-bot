#!/usr/bin/env python3
"""Screener tecnico parallelo ai ticket Danny. Non piazza ordini."""

from __future__ import annotations

from typing import Any

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

SCREENER_CHAT_ID = "-1004469913987"


def to_yahoo_style(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def compute_metrics(ticker: str) -> dict[str, Any] | None:
    if yf is None or pd is None:
        return None
    try:
        hist = yf.Ticker(to_yahoo_style(ticker)).history(period="3mo", interval="1d")
    except Exception:
        return None
    if hist is None or getattr(hist, "empty", True) or len(hist) < 20:
        return None
    needed = {"High", "Low", "Close", "Volume"}
    if not needed.issubset(hist.columns):
        return None

    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    volume = hist["Volume"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr14 = true_range.rolling(14).mean()
    close_now = float(close.iloc[-1])
    atr_now = atr14.iloc[-1]
    if pd.isna(atr_now) or close_now == 0:
        return None
    atr_pct = float(atr_now) / close_now * 100.0

    vol_sma20 = volume.rolling(20).mean().iloc[-1]
    vol_today = float(volume.iloc[-1])
    if pd.isna(vol_sma20) or float(vol_sma20) == 0:
        return None
    volume_ratio = vol_today / float(vol_sma20)

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi_oggi = rsi.iloc[-1]
    rsi_ieri = rsi.iloc[-2]
    if pd.isna(rsi_oggi) or pd.isna(rsi_ieri):
        return None

    max10 = float(high.iloc[-10:].max())
    if max10 == 0:
        return None
    dist_da_max10 = (close_now - max10) / max10 * 100.0

    return {
        "ticker": ticker.strip().upper(),
        "close": close_now,
        "atr_pct": atr_pct,
        "volume_ratio": volume_ratio,
        "rsi_oggi": float(rsi_oggi),
        "rsi_ieri": float(rsi_ieri),
        "dist_da_max10": dist_da_max10,
    }


def score_ticker(metrics: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    atr = metrics.get("atr_pct")
    if isinstance(atr, (int, float)) and 3 <= atr <= 15:
        score += 1
        reasons.append("ATR% 3-15")
    vol = metrics.get("volume_ratio")
    if isinstance(vol, (int, float)) and vol > 1.3:
        score += 1
        reasons.append("volume > 1.3x")
    rsi_oggi = metrics.get("rsi_oggi")
    rsi_ieri = metrics.get("rsi_ieri")
    if (
        isinstance(rsi_oggi, (int, float))
        and isinstance(rsi_ieri, (int, float))
        and 40 <= rsi_oggi <= 65
        and rsi_oggi > rsi_ieri
    ):
        score += 1
        reasons.append("RSI 40-65 in salita")
    dist = metrics.get("dist_da_max10")
    if isinstance(dist, (int, float)) and dist >= -5:
        score += 1
        reasons.append("entro 5% da max10")
    return score, reasons


def _score_emoji(score: int) -> str:
    if score >= 3:
        return "✅"
    if score >= 1:
        return "⚠️"
    return "❌"


def _rsi_label(metrics: dict[str, Any]) -> str:
    oggi = float(metrics["rsi_oggi"])
    ieri = float(metrics["rsi_ieri"])
    arrow = "↑" if oggi > ieri else "↓"
    return f"RSI {oggi:.0f}{arrow}"


def format_screener_message(tickers: list[str]) -> str:
    ranked: list[tuple[int, str]] = []
    missing: list[str] = []
    for raw in tickers:
        ticker = str(raw).strip().upper()
        if not ticker:
            continue
        metrics = compute_metrics(ticker)
        if metrics is None:
            missing.append(f"{ticker}: dati non disponibili")
            continue
        score, _reasons = score_ticker(metrics)
        ranked.append(
            (
                score,
                (
                    f"{_score_emoji(score)} {ticker}  ({score}/4)  "
                    f"ATR {metrics['atr_pct']:.1f}%  "
                    f"vol {metrics['volume_ratio']:.1f}x  "
                    f"{_rsi_label(metrics)}  "
                    f"{metrics['dist_da_max10']:+.1f}% da max10"
                ),
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    lines = ["📊 Screener tecnico"]
    if not ranked and not missing:
        lines.append("Watchlist vuota.")
    else:
        lines.extend(line for _score, line in ranked)
        lines.extend(missing)
    return "\n".join(lines)
