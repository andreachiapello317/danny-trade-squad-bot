#!/usr/bin/env python3
"""Test screener tecnico (senza rete)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import screener
import watch


def _metrics(**overrides: object) -> dict:
    base: dict = {
        "ticker": "AMD",
        "close": 140.0,
        "atr_abs": 11.48,
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
        self.assertIn("atr_abs", metrics)
        self.assertAlmostEqual(metrics["atr_abs"], metrics["atr_pct"] * metrics["close"] / 100.0)


class ComputeLevelsTests(unittest.TestCase):
    def test_levels_from_close_and_atr(self) -> None:
        levels = screener.compute_levels(_metrics())
        self.assertEqual(levels["ingresso_low"], 134.26)
        self.assertEqual(levels["ingresso_high"], 142.3)
        self.assertEqual(levels["stop"], 122.78)
        self.assertEqual(levels["target"], 162.96)

    def test_target_pct_clamped_between_5_and_20(self) -> None:
        low = screener.compute_levels(_metrics(atr_pct=1.0, atr_abs=1.4))
        self.assertEqual(low["target"], 147.0)
        high = screener.compute_levels(_metrics(atr_pct=12.0, atr_abs=16.8))
        self.assertEqual(high["target"], 168.0)


class RunScreenerTests(unittest.TestCase):
    def test_updates_watchlist_and_skips_missing(self) -> None:
        def fake_metrics(ticker: str):
            if ticker == "HOOD":
                return None
            return _metrics(ticker=ticker)

        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            wpath.write_text(
                json.dumps(
                    [
                        {
                            "ticker": "AMD",
                            "tf": "daily",
                            "ingresso_low": 1,
                            "ingresso_high": 2,
                            "stop": 0,
                            "target": 3,
                            "motivo": "old",
                        },
                        {
                            "ticker": "HOOD",
                            "tf": "weekly",
                            "ingresso_low": 10,
                            "stop": 9,
                            "target": 12,
                            "motivo": "keep",
                        },
                    ]
                ),
                encoding="utf-8",
            )
            with (
                patch.object(screener, "compute_metrics", side_effect=fake_metrics),
                patch.object(watch, "refresh_watchlist_summary") as refresh,
            ):
                self.assertIsNone(screener.run_screener(wpath, spath))
            refresh.assert_called_once_with(wpath, spath)
            items = json.loads(wpath.read_text(encoding="utf-8"))
            amd = next(it for it in items if it["ticker"] == "AMD")
            hood = next(it for it in items if it["ticker"] == "HOOD")
            self.assertEqual(amd["ingresso_low"], 134.26)
            self.assertEqual(amd["ingresso_high"], 142.3)
            self.assertEqual(amd["stop"], 122.78)
            self.assertEqual(amd["target"], 162.96)
            self.assertEqual(
                amd["motivo"],
                "Screener automatico (4/4 ✅) — ATR% 3-15, volume > 1.3x, RSI 40-65 in salita, entro 5% da max10",
            )
            self.assertEqual(hood["ingresso_low"], 10)
            self.assertEqual(hood["motivo"], "keep")
            state = json.loads(spath.read_text(encoding="utf-8"))
            self.assertTrue(state["fired"]["AMD|daily|ingresso"])
            self.assertNotIn("AMD|daily|stop", state["fired"])
            self.assertNotIn("AMD|daily|target", state["fired"])
            self.assertNotIn("HOOD|weekly|ingresso", state["fired"])

    def test_cycle_skips_ingresso_after_screener(self) -> None:
        item = {
            "ticker": "AMD",
            "tf": "daily",
            "ingresso_low": 134.26,
            "ingresso_high": 142.3,
            "stop": 122.78,
            "target": 162.96,
            "motivo": "",
        }
        with tempfile.TemporaryDirectory() as tmp:
            wpath = Path(tmp) / "watchlist.json"
            spath = Path(tmp) / "watch_state.json"
            wpath.write_text(json.dumps([item]), encoding="utf-8")
            with patch.object(screener, "compute_metrics", return_value=_metrics(ticker="AMD")):
                screener.run_screener(wpath, spath)
            fired = watch.load_fired(watch.load_state(spath))
            with (
                patch.object(watch, "fetch_prices", return_value={"AMD": 140.0}),
                patch.object(watch, "fetch_day_ranges", return_value={"AMD": None}),
                patch.object(watch, "send_telegram") as send,
                patch.object(watch, "expire_sent_alerts"),
            ):
                watch.cycle([item], fired, spath)
            texts = [call[0][0] for call in send.call_args_list]
            self.assertFalse(any("ingresso" in t for t in texts))
            self.assertFalse(any("stop" in t for t in texts))
            self.assertFalse(any("target" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
