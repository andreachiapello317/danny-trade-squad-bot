import { describe, expect, it } from "vitest";

import { buildCart } from "@/lib/cart";
import { emptySighting, scoreSighting } from "@/lib/score";
import type { Analysis, Sighting } from "@/lib/types";

function sight(partial: Partial<Sighting>): Sighting {
  return emptySighting({
    ticker: "TEST",
    name: "Test",
    hasDaily: true,
    hasWeekly: true,
    hasFivePanelChart: true,
    chartImage: "/charts/test.svg",
    accelPrice: "100",
    invPrice: "90",
    zoneLow: "90",
    zoneHigh: "100",
    ...partial,
  });
}

function scored(partial: Partial<Sighting>) {
  const s = sight(partial);
  return { sighting: s, score: scoreSighting(s) };
}

describe("canone di voto", () => {
  it("parte da 0 e somma solo i pezzi visibili", () => {
    const { score } = scored({
      hasDaily: false,
      hasWeekly: false,
      hasFivePanelChart: false,
      chartImage: null,
      accelPrice: "",
      invPrice: "",
    });
    expect(score.vote).toBeGreaterThanOrEqual(1);
    expect(score.vote).toBeLessThanOrEqual(4);
    expect(score.rating).not.toBe("Buy");
    expect(score.rating).not.toBe("Strong Buy");
  });

  it("esempio canone con chase: voto alto, rating Hold, non Buy", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      redAgeDays: 2,
      whalePct: 82,
      whaleRising: true,
      chaseClose: true,
      closePrice: "154",
      zoneLow: "142",
      zoneHigh: "150",
      accelPrice: "150",
      invPrice: "142",
    });
    expect(score.vote).toBeGreaterThanOrEqual(7);
    expect(score.rating).toBe("Hold");
    expect(score.inCartAsBuy).toBe(false);
    expect(score.explanation).toContain("ribbon rossa");
    expect(score.explanation).toContain("whale 82%");
    expect(score.explanation).toContain("rossa W/M prima settimana");
    expect(score.explanation).toContain("chase");
    expect(score.explanation).toContain("zona 142-150");
  });

  it("Strong Buy solo con struttura completa", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      redAgeDays: 1,
      whalePct: 82,
      whaleRising: true,
      atSupport: true,
      chip: "above_support",
      panel2: "flip_green_red_widening",
    });
    expect(score.vote).toBeGreaterThanOrEqual(9);
    expect(score.rating).toBe("Strong Buy");
    expect(score.inCartAsBuy).toBe(true);
  });

  it("un 8 senza weekly non esiste", () => {
    const { score } = scored({
      hasWeekly: false,
      hasMonthly: true,
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 80,
      whaleRising: true,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(5);
    expect(score.rating).not.toBe("Buy");
    expect(score.rating).not.toBe("Strong Buy");
  });

  it("un 9 con whale a 40 non esiste", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 40,
      whaleRising: true,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(6);
    expect(score.rating).not.toBe("Buy");
    expect(score.rating).not.toBe("Strong Buy");
  });

  it("Strong Buy sotto ribbon blu non esiste", () => {
    const { score } = scored({
      ribbon: "thick_blue_above",
      candle: "fresh_red_wm",
      whalePct: 80,
      whaleRising: true,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(3);
    expect(score.rating).not.toBe("Buy");
    expect(score.rating).not.toBe("Strong Buy");
  });

  it("gialla monthly + whale in calo: ramo sell, non si somma", () => {
    const { score } = scored({
      candle: "yellow_monthly",
      whaleDeclining: true,
      dailyLooksGood: true,
      ribbon: "red_widening",
      whalePct: 80,
      whaleRising: false,
    });
    expect(score.sellBranch).toBe(true);
    expect(score.rating).toBe("Sell Now");
    expect(score.vote).toBeLessThanOrEqual(2);
    expect(score.inCartAsBuy).toBe(false);
  });

  it("hole bucato in giù: Sell Now", () => {
    const { score } = scored({
      hole: "close_below_low",
      ribbon: "red_widening",
      whalePct: 80,
      whaleRising: true,
    });
    expect(score.rating).toBe("Sell Now");
    expect(score.sellBranch).toBe(true);
  });

  it("sul breach alto dell'hole il colore non conta: gialla vale +2 accumulo", () => {
    const { score } = scored({
      hole: "close_above_high",
      candle: "yellow_weekly",
      ribbon: "red_widening",
      whalePct: 70,
      whaleRising: true,
      atSupport: true,
    });
    const hole = score.parts.find((p) => p.key === "hole");
    expect(hole?.points).toBe(2);
    expect(score.parts.some((p) => p.key === "candle")).toBe(false);
    expect(score.caps.some((c) => c.reason === "gialla weekly")).toBe(false);
  });

  it("gialla weekly: tetto 5, non è un buy", () => {
    const { score } = scored({
      candle: "yellow_weekly",
      ribbon: "red_widening",
      whalePct: 80,
      whaleRising: true,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(5);
    expect(score.rating).toBe("Hold");
    expect(score.inCartAsBuy).toBe(false);
  });

  it("whale sotto 35: tetto 4", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 20,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(4);
  });

  it("senza 5 pannelli: tetto 4, mai Buy, nessuna zona", () => {
    const { score } = scored({
      hasFivePanelChart: false,
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 80,
      whaleRising: true,
      atSupport: true,
    });
    expect(score.vote).toBeLessThanOrEqual(4);
    expect(score.zone).toBeNull();
    expect(score.inCartAsBuy).toBe(false);
  });

  it("mancano accel/inv: −1 e non è Buy", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 70,
      whaleRising: true,
      atSupport: true,
      accelPrice: "",
      invPrice: "",
    });
    expect(score.parts.some((p) => p.key === "prices" && p.points === -1)).toBe(true);
    expect(score.inCartAsBuy).toBe(false);
  });

  it("size della candela sul 1 non dà punti", () => {
    const a = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 70,
      whaleRising: true,
    });
    expect(a.score.parts.some((p) => /size/i.test(p.label))).toBe(false);
  });

  it("pannello 2 da solo non basta per un buy", () => {
    const { score } = scored({
      hasWeekly: true,
      panel2: "flip_green_red_widening",
      ribbon: "absent",
      candle: "absent",
      whalePct: 80,
      whaleRising: true,
    });
    expect(score.inCartAsBuy).toBe(false);
  });

  it("hole + blu discendente: +1 e non è buy pieno", () => {
    const { score } = scored({
      hole: "early_with_blue",
      ribbon: "thick_blue_above",
      whalePct: 60,
      whaleRising: true,
    });
    expect(score.notFullBuy || score.notBuy).toBe(true);
    expect(score.inCartAsBuy).toBe(false);
  });

  it("non flippa Strong Buy e Sell Now sullo stesso giro", () => {
    const buy = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 82,
      whaleRising: true,
      atSupport: true,
    });
    const sell = scored({
      hole: "close_below_low",
      ribbon: "red_widening",
      whalePct: 82,
      whaleRising: true,
      atSupport: true,
    });
    expect(buy.score.rating).not.toBe("Sell Now");
    expect(sell.score.rating).not.toBe("Strong Buy");
  });

  it("CHIP sotto come tetto: −2", () => {
    const { score } = scored({ chip: "below_resistance" });
    expect(score.parts.some((p) => p.key === "chip" && p.points === -2)).toBe(true);
  });

  it("MACD/RSI contraddicono solo se stavi per dire Buy", () => {
    const { score } = scored({
      ribbon: "red_widening",
      candle: "fresh_red_wm",
      whalePct: 70,
      whaleRising: true,
      atSupport: true,
      macdBearCrossBelowZero: true,
    });
    expect(score.parts.some((p) => p.key === "p45" && p.points === -1)).toBe(true);
  });
});

describe("carrello", () => {
  it("non mette in carrello un titolo senza foto 5 pannelli", () => {
    const analyses: Analysis[] = [
      {
        id: "1",
        updatedAt: new Date().toISOString(),
        sighting: sight({ ticker: "NOPE", hasFivePanelChart: false, chartImage: null }),
        score: scoreSighting(sight({ ticker: "NOPE", hasFivePanelChart: false })),
      },
      {
        id: "2",
        updatedAt: new Date().toISOString(),
        sighting: sight({ ticker: "OK", ribbon: "red_widening", atSupport: true }),
        score: scoreSighting(sight({ ticker: "OK", ribbon: "red_widening", atSupport: true })),
      },
    ];
    const cart = buildCart(analyses);
    expect(cart.rows.some((r) => r.ticker === "NOPE")).toBe(false);
    expect(cart.rows.some((r) => r.ticker === "OK")).toBe(true);
  });

  it("se il primo non è Buy 7, lo scrive così", () => {
    const s = sight({
      ticker: "HOLD1",
      candle: "yellow_weekly",
      ribbon: "red_widening",
      whalePct: 80,
      whaleRising: true,
    });
    const cart = buildCart([
      {
        id: "1",
        updatedAt: new Date().toISOString(),
        sighting: s,
        score: scoreSighting(s),
      },
    ]);
    expect(cart.marketOfferingEntry).toBe(false);
    expect(cart.headline).toContain("non sta offrendo un ingresso");
  });
});
