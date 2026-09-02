import { CART_SIZE, REDS_SIZE, type Analysis, type Cart, type CartRow } from "@/lib/types";
import { ratingRank } from "@/lib/score";

function toRow(a: Analysis, ceoMark: CartRow["ceoMark"] = "pending"): CartRow | null {
  if (!a.sighting.hasFivePanelChart || !a.sighting.chartImage) return null;
  if (a.score.bucket === "Morto") return null;
  return {
    analysisId: a.id,
    ticker: a.sighting.ticker,
    name: a.sighting.name,
    rating: a.score.rating,
    vote: a.score.vote,
    bucket: a.score.bucket,
    explanation: a.score.explanation,
    zone: a.score.zone,
    chartImage: a.sighting.chartImage,
    hasFivePanelChart: a.sighting.hasFivePanelChart,
    ceoMark,
  };
}

function byVote(a: CartRow, b: CartRow) {
  if (b.vote !== a.vote) return b.vote - a.vote;
  return ratingRank(a.rating) - ratingRank(b.rating);
}

function keepMarks(prev: Cart | null, rows: CartRow[]) {
  if (!prev) return rows;
  const marks = new Map(prev.rows.map((r) => [r.ticker, r.ceoMark]));
  return rows.map((row) => ({
    ...row,
    ceoMark: marks.get(row.ticker) ?? "pending",
  }));
}

export function buildCart(analyses: Analysis[], previous: Cart | null = null): Cart {
  const eligible = analyses
    .map((a) => toRow(a))
    .filter((row): row is CartRow => row != null);

  const buys = eligible
    .filter((r) => r.rating === "Strong Buy" || r.rating === "Buy")
    .sort(byVote);
  const holds = eligible.filter((r) => r.rating === "Hold").sort(byVote);
  const sells = eligible
    .filter((r) => r.rating === "Sell" || r.rating === "Sell Now")
    .sort(byVote);

  const rows: CartRow[] = [];
  for (const row of [...buys, ...holds]) {
    if (rows.length >= CART_SIZE) break;
    rows.push(row);
  }

  if (rows.length < CART_SIZE) {
    for (const row of sells) {
      if (rows.length >= CART_SIZE) break;
      rows.push(row);
    }
  }

  const reds = analyses
    .filter(
      (a) =>
        a.sighting.candle === "fresh_red_wm" &&
        (a.sighting.redAgeDays == null || a.sighting.redAgeDays < 5) &&
        a.sighting.hasFivePanelChart &&
        a.sighting.chartImage
    )
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
    .slice(0, REDS_SIZE)
    .map((a) => toRow(a))
    .filter((row): row is CartRow => row != null);

  const marked = keepMarks(previous, rows);
  const first = marked[0];
  const marketOfferingEntry = Boolean(
    first && (first.rating === "Strong Buy" || first.rating === "Buy") && first.vote >= 7
  );

  const headline = marketOfferingEntry
    ? `Carrello da ${marked.length}: in alto ${first?.ticker} ${first?.rating} ${first?.vote}.`
    : "Il mercato non sta offrendo un ingresso: il primo non è almeno Buy 7.";

  return {
    id: previous?.id ?? `cart-${Date.now()}`,
    builtAt: new Date().toISOString(),
    rows: marked,
    reds,
    marketOfferingEntry,
    headline,
    sentToCeoAt: previous?.sentToCeoAt ?? null,
    sentToSenderAt: null,
  };
}

export function formatCartForCeo(cart: Cart) {
  const lines = cart.rows.map((row, i) => {
    const zone = row.zone ? ` zona ${row.zone.low}-${row.zone.high}` : "";
    const mark =
      row.ceoMark === "valida"
        ? "Valida"
        : row.ceoMark === "non_valida"
          ? "Non valida"
          : "In attesa";
    const bucket = row.bucket ? ` [${row.bucket}]` : "";
    return `${i + 1}. ${row.ticker} — ${row.rating} ${row.vote}${bucket} — ${row.explanation}${zone} — ${mark}`;
  });
  const reds = cart.reds
    .map((r) => `${r.ticker} rossa ${r.vote}`)
    .join(", ");
  return [
    "BotSquad — carrello da 10 (solo CEO)",
    cart.headline,
    "",
    ...lines,
    "",
    `Ultime ${cart.reds.length} rosse: ${reds || "nessuna"}`,
    "",
    "Non tocca wallet. Non scrive su Telegram. In fondo a ogni riga: Valida o Non valida.",
  ].join("\n");
}

export function formatCartForTelegram(cart: Cart) {
  const rows = cart.rows.filter(
    (r) => r.ceoMark === "valida" && r.bucket !== "Morto"
  );
  const lines = rows.map((row, i) => {
    const zone = row.zone ? ` zona ${row.zone.low}-${row.zone.high}` : "";
    const bucket = row.bucket ? ` [${row.bucket}]` : "";
    return `${i + 1}. ${row.ticker} — ${row.rating} ${row.vote}${bucket}\n${row.explanation}${zone}`;
  });
  const reds = cart.reds
    .filter((r) => {
      const match = cart.rows.find((x) => x.ticker === r.ticker);
      return !match || match.ceoMark === "valida";
    })
    .map((r) => `${r.ticker} ${r.vote}`)
    .join(", ");
  return [
    "Carrello validato dal CEO",
    cart.headline,
    "",
    ...lines.flatMap((line, i) => (i === 0 ? [line] : ["", line])),
    "",
    `Ultime rosse: ${reds || "nessuna"}`,
    "",
    "Non è un consiglio di investimento. Size e wallet non passano da qui.",
  ].join("\n");
}
