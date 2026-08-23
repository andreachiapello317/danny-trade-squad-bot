import { isBoardFresh, peekStoredBoard, readStoredBoard, stampBoard, writeStoredBoard } from "@/lib/board-store";
import { notifyTopTickers } from "@/lib/notify";
import type { Stock, StockBoard } from "@/lib/types";

const MIN_MCAP = 200_000_000;
const NASDAQ_HEADERS = {
  accept: "application/json",
  origin: "https://www.nasdaq.com",
  referer: "https://www.nasdaq.com/",
  "user-agent":
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
};

const SKIP_TYPES = /warrant|right|unit|preferred|etf|etn|fund|note|depositary/i;
const SKIP_SUFFIX = /(W|WW|WS|WR|R|U|P)$/;
const SKIP_SYMBOLS = new Set([
  "SPY",
  "QQQ",
  "IWM",
  "DIA",
  "TQQQ",
  "SQQQ",
  "SOXL",
  "SOXS",
  "IBIT",
  "BITO",
  "MSTU",
  "TSLL",
]);

type Json = Record<string, unknown>;

function asRecord(value: unknown): Json {
  return value && typeof value === "object" ? (value as Json) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function parseNum(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/[$,+%]/g, "").replace(/,/g, "").trim();
  if (!cleaned || cleaned === "N/A" || cleaned === "NA" || cleaned === "--") return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

async function nasdaqJson(url: string, timeoutMs = 10_000): Promise<Json | null> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: NASDAQ_HEADERS,
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return null;
    return (await response.json()) as Json;
  } catch {
    return null;
  }
}

type MoverHit = {
  symbol: string;
  name: string;
  priceUsd: number | null;
  changeUsd: number | null;
  volume: number | null;
  activeShareRank: number | null;
  activeDollarRank: number | null;
  gainerRank: number | null;
  nasdaq100Mover: boolean;
};

function moverRows(table: unknown): Json[] {
  return asArray(asRecord(asRecord(table).table).rows).map(asRecord);
}

function ingestMovers(list: unknown, kind: keyof Pick<MoverHit, "activeShareRank" | "activeDollarRank" | "gainerRank"> | "nasdaq100") {
  const hits = new Map<string, MoverHit>();
  moverRows(list).forEach((row, index) => {
    const symbol = str(row.symbol)?.toUpperCase();
    if (!symbol) return;
    const rank = index + 1;
    const current = hits.get(symbol) ?? {
      symbol,
      name: str(row.name) ?? symbol,
      priceUsd: parseNum(row.lastSalePrice),
      changeUsd: parseNum(row.lastSaleChange),
      volume: parseNum(row.change),
      activeShareRank: null,
      activeDollarRank: null,
      gainerRank: null,
      nasdaq100Mover: false,
    };
    if (kind === "nasdaq100") current.nasdaq100Mover = true;
    else current[kind] = rank;
    current.priceUsd = current.priceUsd ?? parseNum(row.lastSalePrice);
    current.changeUsd = current.changeUsd ?? parseNum(row.lastSaleChange);
    hits.set(symbol, current);
  });
  return hits;
}

function mergeHits(maps: Array<Map<string, MoverHit>>) {
  const out = new Map<string, MoverHit>();
  for (const map of maps) {
    for (const [symbol, hit] of map) {
      const current = out.get(symbol);
      if (!current) {
        out.set(symbol, { ...hit });
        continue;
      }
      current.activeShareRank = current.activeShareRank ?? hit.activeShareRank;
      current.activeDollarRank = current.activeDollarRank ?? hit.activeDollarRank;
      current.gainerRank = current.gainerRank ?? hit.gainerRank;
      current.nasdaq100Mover = current.nasdaq100Mover || hit.nasdaq100Mover;
      current.priceUsd = current.priceUsd ?? hit.priceUsd;
      current.changeUsd = current.changeUsd ?? hit.changeUsd;
      current.volume = Math.max(current.volume ?? 0, hit.volume ?? 0) || current.volume;
      if (hit.name && hit.name !== symbol) current.name = hit.name;
    }
  }
  return out;
}

async function quoteSymbol(symbol: string) {
  const [infoPayload, summaryPayload] = await Promise.all([
    nasdaqJson(`https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/info?assetclass=stocks`),
    nasdaqJson(`https://api.nasdaq.com/api/quote/${encodeURIComponent(symbol)}/summary?assetclass=stocks`),
  ]);
  const info = asRecord(asRecord(infoPayload).data);
  const summary = asRecord(asRecord(asRecord(summaryPayload).data).summaryData);
  const notifications = asArray(info.notifications).map(asRecord);
  const outOfCompliance = notifications.some((row) => {
    const headline = str(row.headline)?.toLowerCase() ?? "";
    return headline.includes("out of compliance") || headline.includes("noncompliant");
  });
  return {
    symbol,
    companyName: str(info.companyName),
    stockType: str(info.stockType) ?? "",
    exchange: str(info.exchange) ?? "",
    isNasdaqListed: info.isNasdaqListed === true,
    isNasdaq100: info.isNasdaq100 === true,
    outOfCompliance,
    priceUsd: parseNum(asRecord(info.primaryData).lastSalePrice),
    changeUsd: parseNum(asRecord(info.primaryData).netChange),
    changePct: parseNum(asRecord(info.primaryData).percentageChange),
    volume: parseNum(asRecord(info.primaryData).volume),
    marketCap: parseNum(asRecord(summary.MarketCap).value),
    sector: str(asRecord(summary.Sector).value),
  };
}

function isCommonStock(stockType: string) {
  const value = stockType.toLowerCase();
  return value.includes("common") || value.includes("ordinary");
}

function scoreStock(hit: MoverHit, quote: Awaited<ReturnType<typeof quoteSymbol>>): Stock {
  const reasons: string[] = ["Listata sul NASDAQ"];
  const activeDollar = hit.activeDollarRank;
  const activeShare = hit.activeShareRank;
  const gainer = hit.gainerRank;
  const nasdaq100 = quote.isNasdaq100 || hit.nasdaq100Mover;
  const changePct = quote.changePct;
  const volume = quote.volume ?? hit.volume;
  const marketCap = quote.marketCap;

  let score = 20;
  if (nasdaq100) {
    score += 28;
    reasons.push("Nasdaq-100");
  }
  if (activeDollar != null) {
    score += Math.max(6, 32 - activeDollar * 3);
    reasons.push(`#${activeDollar} per volume in dollari`);
  }
  if (activeShare != null) {
    score += Math.max(4, 18 - activeShare * 2);
    reasons.push(`#${activeShare} per pezzi scambiati`);
  }
  if (gainer != null) {
    score += Math.max(4, 22 - gainer * 2);
    reasons.push(`#${gainer} tra le più in rialzo`);
  }
  if (changePct != null && changePct >= 2) {
    score += Math.min(18, changePct);
    reasons.push(`Giornata ${changePct >= 0 ? "+" : ""}${changePct.toFixed(1)}%`);
  } else if (changePct != null) {
    reasons.push(`Variazione ${changePct >= 0 ? "+" : ""}${changePct.toFixed(1)}%`);
  }
  if ((volume ?? 0) >= 20_000_000) {
    score += 8;
    reasons.push("Volume alto");
  }
  if ((marketCap ?? 0) >= 50_000_000_000) {
    score += 6;
    reasons.push("Large cap");
  }
  if (quote.sector) reasons.push(quote.sector);

  const symbol = quote.symbol;
  return {
    symbol,
    name: quote.companyName ?? hit.name,
    priceUsd: quote.priceUsd ?? hit.priceUsd,
    changeUsd: quote.changeUsd ?? hit.changeUsd,
    changePct,
    volume,
    marketCap,
    exchange: quote.exchange || "NASDAQ",
    sector: quote.sector,
    nasdaq100,
    score: Math.round(Math.min(100, score)),
    reasons,
    xUrl: `https://x.com/search?q=${encodeURIComponent(`$${symbol} stock OR nasdaq`)}&src=typed_query&f=live`,
    chartUrl: `https://www.tradingview.com/symbols/NASDAQ-${encodeURIComponent(symbol)}/`,
    nasdaqUrl: `https://www.nasdaq.com/market-activity/stocks/${symbol.toLowerCase()}`,
  };
}

let computing: Promise<StockBoard> | null = null;

export async function peekStockBoard() {
  return peekStoredBoard();
}

export async function getStockBoard(options?: { skipNotify?: boolean; fresh?: boolean }): Promise<StockBoard> {
  const stored = await readStoredBoard();
  if (!options?.fresh && stored && isBoardFresh(stored)) {
    return stampBoard(stored.board, stored.at);
  }
  if (!options?.fresh && computing) return computing;

  const run = computeStockBoard(options, stored);
  if (!options?.fresh) {
    computing = run.finally(() => {
      computing = null;
    });
  }
  return run;
}

async function computeStockBoard(
  options: { skipNotify?: boolean; fresh?: boolean } | undefined,
  stored: Awaited<ReturnType<typeof readStoredBoard>>,
): Promise<StockBoard> {
  try {
    const movers = await nasdaqJson("https://api.nasdaq.com/api/marketmovers", 12_000);
    const stocks = asRecord(asRecord(movers).data).STOCKS;
    const pack = asRecord(stocks);
    const hits = mergeHits([
      ingestMovers(pack.MostActiveByDollarVolume, "activeDollarRank"),
      ingestMovers(pack.MostActiveByShareVolume, "activeShareRank"),
      ingestMovers(pack.MostAdvanced, "gainerRank"),
      ingestMovers(pack.Nasdaq100Movers, "nasdaq100"),
    ]);

    const quotes = await Promise.all(
      [...hits.keys()].slice(0, 36).map((symbol) => quoteSymbol(symbol)),
    );

    const scored = quotes
      .map((quote) => {
        const hit = hits.get(quote.symbol);
        if (!hit) return null;
        if (SKIP_SYMBOLS.has(quote.symbol) || SKIP_SUFFIX.test(quote.symbol)) return null;
        if (!quote.isNasdaqListed) return null;
        if (!isCommonStock(quote.stockType) || SKIP_TYPES.test(quote.stockType)) return null;
        if (quote.outOfCompliance) return null;
        if ((quote.marketCap ?? 0) > 0 && (quote.marketCap ?? 0) < MIN_MCAP) return null;
        return scoreStock(hit, quote);
      })
      .filter((row): row is Stock => Boolean(row))
      .sort((a, b) => b.score - a.score || (b.volume ?? 0) - (a.volume ?? 0))
      .slice(0, 12);

    const topTickers = scored.slice(0, 4);
    const board: StockBoard = {
      generatedAt: new Date().toISOString(),
      winner: scored[0] ?? null,
      stocks: scored,
      topTickers,
      sources: {
        nasdaqMovers: Boolean(movers),
        nasdaqQuotes: quotes.some((row) => row.isNasdaqListed),
      },
      note: "Solo azioni comuni listate sul NASDAQ, le più in trending. Ricerca ogni 2 ore.",
    };

    const saved = await writeStoredBoard(board);
    if (!options?.skipNotify) {
      void notifyTopTickers(topTickers).catch(() => undefined);
    }
    return stampBoard(saved.board, saved.at);
  } catch (error) {
    if (stored) return stampBoard(stored.board, stored.at);
    throw error;
  }
}
