import type {
  CandleSight,
  Rating,
  ScorePart,
  ScoreResult,
  Sighting,
} from "@/lib/types";

function clampVote(n: number) {
  return Math.max(1, Math.min(10, Math.round(n)));
}

function ratingFromVote(vote: number): Rating {
  if (vote >= 9) return "Strong Buy";
  if (vote >= 7) return "Buy";
  if (vote >= 5) return "Hold";
  if (vote >= 3) return "Sell";
  return "Sell Now";
}

function hasTwoPrices(s: Sighting) {
  return Boolean(
    s.accelPrice.trim() && s.invPrice.trim() && !s.pricesCopiedFromCandle
  );
}

function zoneOf(s: Sighting): { low: string; high: string } | null {
  if (!s.hasFivePanelChart) return null;
  const low = s.zoneLow.trim();
  const high = s.zoneHigh.trim();
  if (!low || !high) return null;
  return { low, high };
}

function isFreshRed(s: Sighting) {
  if (s.candle !== "fresh_red_wm") return false;
  if (s.redAgeDays == null) return true;
  return s.redAgeDays < 5;
}

function isStaleRed(s: Sighting) {
  if (s.candle !== "fresh_red_wm" && s.candle !== "absent") {
    return false;
  }
  if (s.candle === "fresh_red_wm" && s.redAgeDays != null && s.redAgeDays >= 5) {
    return true;
  }
  return false;
}

function monthlyBroken(s: Sighting) {
  return s.candle === "yellow_monthly" && s.whaleDeclining && s.dailyLooksGood;
}

function bearishHigherTf(s: Sighting) {
  return s.candle === "yellow_weekly" || s.candle === "yellow_monthly";
}

function holeOverridesCandleColor(s: Sighting) {
  return s.hole === "close_above_high";
}

function formatZone(zone: { low: string; high: string } | null) {
  if (!zone) return "";
  return `, zona ${zone.low}-${zone.high}`;
}

function formatClose(s: Sighting) {
  const close = s.closePrice.trim();
  return close ? ` ${close}` : "";
}

function whaleLabel(pct: number | null) {
  if (pct == null) return "whale";
  return `whale ${Math.round(pct)}%`;
}

function strongBuyStructure(s: Sighting) {
  const whaleOk =
    s.whalePct != null && s.whalePct >= 75 && s.whaleRising && !s.whaleDeclining;
  return (
    isFreshRed(s) &&
    s.ribbon === "red_widening" &&
    whaleOk &&
    s.atSupport &&
    !s.chaseClose &&
    hasTwoPrices(s) &&
    s.hasDaily &&
    s.hasWeekly
  );
}

function applyCap(vote: number, caps: { limit: number; reason: string }[]) {
  const limit = caps.reduce((m, c) => Math.min(m, c.limit), 10);
  return Math.min(vote, limit);
}

function forceNotBuy(rating: Rating): Rating {
  if (rating === "Strong Buy" || rating === "Buy") return "Hold";
  return rating;
}

function sellResult(
  s: Sighting,
  vote: number,
  rating: Rating,
  reason: string,
  sellNow: boolean
): ScoreResult {
  const zone = zoneOf(s);
  const parts: ScorePart[] = [{ key: "ramo_sell", label: reason, points: 0 }];
  return {
    sum: vote,
    vote,
    rating,
    parts,
    caps: [],
    sellBranch: true,
    sellNow,
    notBuy: true,
    notFullBuy: true,
    inCartAsBuy: false,
    zone,
    explanation: `${vote} = ${reason}${formatZone(zone)}`,
    warnings: sellNow
      ? ["Ramo sell: non si somma, uscita."]
      : ["Ramo sell: non si somma, non è un buy."],
  };
}

export function emptySighting(partial: Partial<Sighting> = {}): Sighting {
  return {
    ticker: "",
    name: "",
    hasDaily: false,
    hasWeekly: false,
    hasMonthly: false,
    hasFivePanelChart: false,
    chartImage: null,
    dailyLooksGood: false,
    ribbon: "absent",
    ribbonExtension: false,
    candle: "absent",
    redAgeDays: null,
    chip: "absent",
    hole: "absent",
    panel2: "absent",
    whalePct: null,
    whaleRising: false,
    whaleDeclining: false,
    retailDominant: false,
    macdBearCrossBelowZero: false,
    rsiBelow50StackedWrong: false,
    atSupport: false,
    chaseClose: false,
    closePrice: "",
    accelPrice: "",
    invPrice: "",
    pricesCopiedFromCandle: false,
    zoneLow: "",
    zoneHigh: "",
    postId: null,
    notes: "",
    ...partial,
  };
}

export function scoreSighting(s: Sighting): ScoreResult {
  if (monthlyBroken(s)) {
    return sellResult(
      s,
      2,
      "Sell Now",
      "gialla monthly + whale in calo (daily bello, monthly rotto)",
      true
    );
  }

  if (s.hole === "close_below_low") {
    return sellResult(s, 1, "Sell Now", "hole bucato in giù, close sotto il bordo basso", true);
  }

  if (s.ribbon === "red_thinning" && bearishHigherTf(s)) {
    return sellResult(
      s,
      2,
      "Sell Now",
      "ribbon rossa che si stringe con bearish W/M",
      true
    );
  }

  if (s.candle === "yellow_monthly" && !holeOverridesCandleColor(s)) {
    return sellResult(s, 4, "Sell", "gialla monthly: non è un buy", false);
  }

  const parts: ScorePart[] = [];
  const caps: { limit: number; reason: string }[] = [];
  const warnings: string[] = [];
  let notBuy = false;
  let notFullBuy = false;

  if (s.hasWeekly || s.hasMonthly) {
    parts.push({
      key: "tf",
      label: s.hasWeekly ? "weekly presente" : "monthly presente",
      points: 2,
    });
  } else if (s.hasDaily) {
    parts.push({ key: "tf", label: "solo daily", points: 0 });
  }

  if (!s.hasWeekly) {
    caps.push({ limit: 5, reason: "senza weekly" });
  }

  if (s.ribbon === "red_widening") {
    parts.push({ key: "ribbon", label: "ribbon rossa che si allarga", points: 2 });
  } else if (s.ribbon === "red_thinning") {
    parts.push({ key: "ribbon", label: "ribbon rossa che si assottiglia", points: 1 });
  } else if (s.ribbon === "thick_blue_above") {
    parts.push({ key: "ribbon", label: "ribbon blu spessa sopra il prezzo", points: 0 });
    caps.push({ limit: 3, reason: "rossa sotto ribbon blu spessa" });
    notBuy = true;
    warnings.push("Blu spessa sopra il prezzo: non è un buy.");
  }

  if (s.ribbonExtension) {
    parts.push({ key: "extension", label: "prezzo troppo lontano dalla ribbon", points: -1 });
  }

  if (holeOverridesCandleColor(s)) {
    parts.push({
      key: "hole",
      label: "close sopra il bordo alto dell'hole (accumulo)",
      points: 2,
    });
  } else {
    const candle: CandleSight = s.candle;
    if (candle === "fresh_red_wm" && isFreshRed(s)) {
      parts.push({
        key: "candle",
        label: "rossa W/M prima settimana",
        points: 2,
      });
    } else if (candle === "dark_blue_continuation") {
      parts.push({
        key: "candle",
        label: "blu scure di continuazione su ribbon rossa",
        points: 1,
      });
    } else if (candle === "yellow_weekly") {
      parts.push({ key: "candle", label: "gialla weekly", points: 0 });
      caps.push({ limit: 5, reason: "gialla weekly" });
      notBuy = true;
      warnings.push("Gialla weekly: non è un buy, watch remoto.");
    }

    if (s.hole === "early_with_blue") {
      parts.push({
        key: "hole",
        label: "hole + ribbon blu discendente (prima accumulazione)",
        points: 1,
      });
      notFullBuy = true;
      warnings.push("Hole + blu: non è ancora un buy pieno.");
    } else if (s.hole === "close_in_middle") {
      parts.push({
        key: "hole",
        label: "close in mezzo all'hole, nessun bordo bucato",
        points: 0,
      });
      warnings.push("Senza close fuori dal bordo non si scommette la direzione.");
    }
  }

  if (s.chip === "above_support") {
    parts.push({ key: "chip", label: "prezzo sopra il CHIP usato come supporto", points: 1 });
  } else if (s.chip === "below_resistance") {
    parts.push({
      key: "chip",
      label: "prezzo sotto il CHIP usato come tetto",
      points: -2,
    });
  } else if (s.chip === "flipped_res_to_sup") {
    parts.push({
      key: "chip",
      label: "CHIP girato da resistenza a supporto",
      points: 1,
    });
  }

  if (s.panel2 === "flip_green_red_widening") {
    parts.push({
      key: "p2",
      label: "pannello 2 flip verde→rosso, barre che si allargano",
      points: 1,
    });
  } else if (s.panel2 === "off_or_red_to_green") {
    parts.push({
      key: "p2",
      label: "pannello 2 già spento o rosso→verde",
      points: -1,
    });
  }

  if (s.whalePct != null) {
    const pct = s.whalePct;
    if (pct >= 75 && s.whaleRising) {
      parts.push({ key: "whale", label: `${whaleLabel(pct)} in salita`, points: 3 });
    } else if (pct >= 50 && s.whaleRising) {
      parts.push({ key: "whale", label: `${whaleLabel(pct)} in salita`, points: 2 });
    } else if (pct >= 35 && pct < 50) {
      parts.push({ key: "whale", label: whaleLabel(pct), points: 1 });
    } else if (pct < 35) {
      parts.push({ key: "whale", label: `${whaleLabel(pct)} sotto 35%`, points: 0 });
      caps.push({ limit: 4, reason: "whale sotto 35" });
    } else {
      parts.push({
        key: "whale",
        label: `${whaleLabel(pct)} non in salita`,
        points: 0,
      });
    }

    if (pct < 50) {
      caps.push({ limit: 6, reason: "whale sotto 50" });
      notBuy = true;
      warnings.push("Sotto 50% whale il voto non entra in carrello come Buy.");
    }
  }

  if (s.whaleDeclining) {
    parts.push({ key: "whale_down", label: "whale in calo", points: -1 });
  }
  if (s.retailDominant) {
    parts.push({ key: "retail", label: "retail dominante (verde alto)", points: -1 });
  }

  if (s.atSupport && !s.chaseClose) {
    parts.push({ key: "pos", label: "a supporto (ribbon / CHIP / POC)", points: 2 });
  }
  if (s.chaseClose) {
    parts.push({
      key: "chase",
      label: `close${formatClose(s)} chase sopra la zona`,
      points: -2,
    });
    notBuy = true;
    warnings.push("Close già sopra la zona: non è Buy, non si allarga la zona.");
  }
  if (isStaleRed(s)) {
    parts.push({
      key: "stale",
      label: "rossa con più di 5 giorni / oltre la prima settimana",
      points: -2,
    });
  }

  if (hasTwoPrices(s)) {
    parts.push({ key: "prices", label: "accel e inv scritti", points: 1 });
  } else {
    parts.push({ key: "prices", label: "mancano accel/inv", points: -1 });
    notBuy = true;
    warnings.push("Senza due prezzi non è Buy.");
  }

  if (!s.hasFivePanelChart) {
    caps.push({ limit: 4, reason: "manca il grafico 5 pannelli" });
    notBuy = true;
    warnings.push("Senza 5 pannelli: mai Buy, nessuna zona inventata.");
  }

  let sum = parts.reduce((n, p) => n + p.points, 0);
  let vote = clampVote(applyCap(sum, caps));
  let rating = ratingFromVote(vote);

  const contradict = s.macdBearCrossBelowZero || s.rsiBelow50StackedWrong;
  if (contradict && (rating === "Buy" || rating === "Strong Buy")) {
    parts.push({
      key: "p45",
      label: s.macdBearCrossBelowZero
        ? "MACD sotto zero in croce bear"
        : "RSI sotto 50 impilato al contrario",
      points: -1,
    });
    sum -= 1;
    vote = clampVote(applyCap(sum, caps));
    rating = ratingFromVote(vote);
    warnings.push("Pannello 4/5 contraddice: non si spara su MACD o RSI.");
  }

  const hasPrimarySetup =
    s.ribbon === "red_widening" ||
    s.ribbon === "red_thinning" ||
    holeOverridesCandleColor(s) ||
    (s.candle === "fresh_red_wm" && isFreshRed(s)) ||
    s.candle === "dark_blue_continuation";
  if (s.panel2 === "flip_green_red_widening" && !hasPrimarySetup) {
    notBuy = true;
    warnings.push("Pannello 2 non basta da solo per un buy.");
  }

  if (notFullBuy) {
    notBuy = true;
  }

  if (rating === "Strong Buy" && !strongBuyStructure(s)) {
    rating = "Buy";
    vote = Math.min(vote, 8);
  }

  if (notBuy) {
    rating = forceNotBuy(rating);
  }

  vote = clampVote(vote);

  const zone = zoneOf(s);
  const shown = parts.filter((p) => p.points !== 0);
  const body =
    shown.length === 0
      ? "nessun pezzo visibile sul grafico"
      : shown
          .map((p) => `${p.label} ${p.points > 0 ? `+${p.points}` : p.points}`)
          .join(", ");
  const capNote =
    caps.length && applyCap(sum, caps) < sum
      ? ` (tetto ${Math.min(...caps.map((c) => c.limit))}: ${caps.map((c) => c.reason).join(", ")})`
      : "";

  const inCartAsBuy = rating === "Strong Buy" || rating === "Buy";

  return {
    sum,
    vote,
    rating,
    parts,
    caps,
    sellBranch: false,
    sellNow: rating === "Sell Now",
    notBuy,
    notFullBuy,
    inCartAsBuy,
    zone,
    explanation: `${vote} = ${body}${formatZone(zone)}${capNote}`,
    warnings,
  };
}

export function ratingRank(rating: Rating) {
  switch (rating) {
    case "Strong Buy":
      return 0;
    case "Buy":
      return 1;
    case "Hold":
      return 2;
    case "Sell":
      return 3;
    case "Sell Now":
      return 4;
  }
}
