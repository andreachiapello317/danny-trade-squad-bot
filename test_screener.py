#!/usr/bin/env python3
"""Test screener tecnico (senza rete)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

import screener


def _metrics(**overrides: object) -> dict:
    base: dict = {
        "ticker": "AMD",
        "close": 140.0,
        "atr_pct": 8.2,
        "volume_ratio": 1.6,
        "rsi_oggi": 55.0,
        "rsi_ieri": 50.0,
        "dist_da_max10": -2.1,
    }
    base.update(overrides)
    return base


class ScoreTickerTests(unittest.TestCase):
    def test_all_four_rules(self) -> None:
        score, reasons = screener.score_ticker(_metrics())
        self.assertEqual(score, 4)
        self.assertEqual(len(reasons), 4)

    def test_each_rule_can_fail(self) -> None:
        self.assertEqual(screener.score_ticker(_metrics(atr_pct=2.9))[0], 3)
        self.assertEqual(screener.score_ticker(_metrics(atr_pct=15.1))[0], 3)
        self.assertEqual(screener.score_ticker(_metrics(volume_ratio=1.3))[0], 3)
        self.assertEqual(screener.score_ticker(_metrics(rsi_oggi=39.9))[0], 3)
        self.assertEqual(screener.score_ticker(_metrics(rsi_oggi=50.0, rsi_ieri=50.0))[0], 3)
        self.assertEqual(screener.score_ticker(_metrics(dist_da_max10=-5.1))[0], 3)

    def test_zero_score(self) -> None:
        score, reasons = screener.score_ticker(
            _metrics(atr_pct=1.0, volume_ratio=0.5, rsi_oggi=20.0, rsi_ieri=30.0, dist_da_max10=-20.0)
        )
        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])


class FormatScreenerTests(unittest.TestCase):
    def test_sorts_and_marks_missing(self) -> None:
        def fake_metrics(ticker: str):
            if ticker == "HOOD":
                return None
            if ticker == "AMD":
                return _metrics(ticker="AMD")
            return _metrics(
                ticker="NVDA",
                atr_pct=1.0,
                volume_ratio=0.5,
                rsi_oggi=20.0,
                rsi_ieri=30.0,
                dist_da_max10=-20.0,
            )

        with patch.object(screener, "compute_metrics", side_effect=fake_metrics):
            body = screener.format_screener_message(["NVDA", "AMD", "HOOD"])
        lines = body.splitlines()
        self.assertEqual(lines[0], "📊 Screener tecnico")
        self.assertIn("✅ AMD  (4/4)", lines[1])
        self.assertIn("ATR 8.2%", lines[1])
        self.assertIn("vol 1.6x", lines[1])
        self.assertIn("RSI 55↑", lines[1])
        self.assertIn("-2.1% da max10", lines[1])
        self.assertIn("❌ NVDA  (0/4)", lines[2])
        self.assertEqual(lines[3], "HOOD: dati non disponibili")

    def test_empty_watchlist_line(self) -> None:
        self.assertEqual(
            screener.format_screener_message([]),
            "📊 Screener tecnico\nWatchlist vuota.",
        )


class ComputeMetricsTests(unittest.TestCase):
    def test_none_when_history_short(self) -> None:
        hist = pd.DataFrame(
            {
                "High": [11.0] * 10,
                "Low": [9.0] * 10,
                "Close": [10.0] * 10,
                "Volume": [1000.0] * 10,
            }
        )

        class FakeTicker:
            def history(self, **kwargs: object) -> pd.DataFrame:
                return hist

        with patch.object(screener, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker()
            self.assertIsNone(screener.compute_metrics("AMD"))

    def test_computes_from_daily_bars(self) -> None:
        n = 25
        close = pd.Series([100.0 + i * 0.2 for i in range(n)])
        hist = pd.DataFrame(
            {
                "High": close + 2.0,
                "Low": close - 2.0,
                "Close": close,
                "Volume": [1000.0] * (n - 1) + [2500.0],
            }
        )

        class FakeTicker:
            def history(self, **kwargs: object) -> pd.DataFrame:
                return hist

        with patch.object(screener, "yf") as yf_mod:
            yf_mod.Ticker.return_value = FakeTicker()
            metrics = screener.compute_metrics("brk.b")
        assert metrics is not None
        self.assertEqual(metrics["ticker"], "BRK.B")
        self.assertAlmostEqual(metrics["close"], float(close.iloc[-1]))
        self.assertGreater(metrics["atr_pct"], 0)
        self.assertGreater(metrics["volume_ratio"], 1.3)
        self.assertLessEqual(metrics["dist_da_max10"], 0)


if __name__ == "__main__":
    unittest.main()
