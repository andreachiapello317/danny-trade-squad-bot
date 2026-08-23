import type { HypeResponse, HypeToken, XPost } from "@/lib/types";
import { isBoardFresh, peekStoredBoard, readStoredBoard, stampBoard, writeStoredBoard } from "@/lib/board-store";
import { checkTokens } from "@/lib/legit";
import { notifyTopContracts } from "@/lib/notify";
import { BOARD_CACHE_MS } from "@/lib/timing";
import { loadCrowdTalks, twitterHandle } from "@/lib/x-signal";

const SKIP_SYMBOLS = new Set([
  "SOL",
  "WSOL",
  "USDC",
  "USDT",
  "USD1",
  "PYUSD",
  "USDS",
  "DAI",
  "WETH",
  "BTC",
  "ETH",
  "WBTC",
  "CBBTC",
  "MSOL",
  "JITOSOL",
  "BSOL",
  "JUPSOL",
  "BNSOL",
  "INF",
  "STSOL",
  "ZEC",
]);

const SKIP_NAME_RE = /wormhole|xstock|wrapped|bridged|staked |prestock/i;

const MIN_MCAP = 200_000;
const MAX_MCAP = 5_000_000_000;
const MIN_LIQ = 12_000;
const MIN_ORGANIC = 10;
const MIN_LAUNCH_HOURS = 0.5;
const SKIP_NAMES = new Set(["test", "testing", "asdf", "aaa"]);

const WSOL = "So11111111111111111111111111111111111111112";

const SKIP_MINTS = new Set([
  "98sMhvDwXj1RQi5c5Mndm3vPe9cBqPrbLaufMXFNMh5g", // wrapped Hyperliquid HYPE
]);

type Json = Record<string, unknown>;

async function fetchJson<T>(url: string, timeoutMs = 9000): Promise<T | null> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: {
        accept: "application/json",
        "user-agent": "solana-hype-radar/1.0",
      },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function asRecord(value: unknown): Json {
  return value && typeof value === "object" ? (value as Json) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value.replace(/[$,]/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function rankPoints(rank: number | null, size: number): number {
  if (rank == null || rank < 1) return 0;
  return Math.max(8, Math.round(100 * (1 - (rank - 1) / Math.max(size, 1))));
}

function logScale(value: number | null, max: number): number {
  if (!value || value <= 0) return 0;
  return Math.min(100, (Math.log10(value + 1) / Math.log10(max + 1)) * 100);
}

function foldName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function normalizeSymbol(symbol: string): string {
  return symbol.replace(/^\$/, "").trim().toUpperCase();
}

function namesAlign(tokenName: string, tokenSymbol: string, coinName: string, coinSymbol: string) {
  if (normalizeSymbol(tokenSymbol) !== normalizeSymbol(coinSymbol)) return false;
  const token = foldName(tokenName);
  const coin = foldName(coinName);
  if (!token || !coin) return false;
  if (token === coin) return true;
  const tokenWords = new Set(token.split(" ").filter((word) => word.length >= 4));
  const coinWords = new Set(coin.split(" ").filter((word) => word.length >= 4));
  if ([...tokenWords].some((word) => coinWords.has(word))) return true;
  if (token.length >= 5 && (coin.includes(token) || token.includes(coin))) return true;
  return false;
}

type Draft = {
  mint: string;
  name: string;
  symbol: string;
  imageUrl: string | null;
  priceUsd: number | null;
  marketCap: number | null;
  volume24h: number | null;
  volume1h: number | null;
  volume5m: number | null;
  priceChange24h: number | null;
  priceChange1h: number | null;
  priceChange5m: number | null;
  buys24h: number;
  sells24h: number;
  buys5m: number;
  sells5m: number;
  liquidityUsd: number | null;
  pairCreatedAt: number | null;
  freshBoost: boolean;
  twitterUrl: string | null;
  telegramUrl: string | null;
  websiteUrl: string | null;
  dexScreenerUrl: string | null;
  boostAmount: number;
  coinGeckoRank: number | null;
  geckoTerminalRank: number | null;
  listed: boolean;
  verified: boolean;
  organicScore: number | null;
};

function emptyDraft(mint: string, name: string, symbol: string): Draft {
  return {
    mint,
    name,
    symbol,
    imageUrl: null,
    priceUsd: null,
    marketCap: null,
    volume24h: null,
    volume1h: null,
    volume5m: null,
    priceChange24h: null,
    priceChange1h: null,
    priceChange5m: null,
    buys24h: 0,
    sells24h: 0,
    buys5m: 0,
    sells5m: 0,
    liquidityUsd: null,
    pairCreatedAt: null,
    freshBoost: false,
    twitterUrl: null,
    telegramUrl: null,
    websiteUrl: null,
    dexScreenerUrl: `https://dexscreener.com/solana/${mint}`,
    boostAmount: 0,
    coinGeckoRank: null,
    geckoTerminalRank: null,
    listed: false,
    verified: false,
    organicScore: null,
  };
}

function pickDexPair(pairs: unknown[]): Json | null {
  const solana = pairs
    .map(asRecord)
    .filter((pair) => str(pair.chainId) === "solana");
  if (!solana.length) return null;
  return [...solana].sort((a, b) => {
    const liqA = num(asRecord(a.liquidity).usd) ?? 0;
    const liqB = num(asRecord(b.liquidity).usd) ?? 0;
    return liqB - liqA;
  })[0];
}

function applyDexPair(draft: Draft, pair: Json) {
  const info = asRecord(pair.info);
  const txns = asRecord(pair.txns);
  const h24 = asRecord(txns.h24);
  const m5 = asRecord(txns.m5);
  const volume = asRecord(pair.volume);
  const change = asRecord(pair.priceChange);
  const socials = asArray(info.socials);
  const websites = asArray(info.websites);

  let twitter: string | null = null;
  let telegram: string | null = null;
  for (const social of socials) {
    const row = asRecord(social);
    const url = str(row.url);
    const type = str(row.type)?.toLowerCase();
    if (!url) continue;
    if (type === "twitter" || url.includes("x.com") || url.includes("twitter.com")) {
      twitter = url;
    }
    if (type === "telegram" || url.includes("t.me")) {
      telegram = url;
    }
  }

  draft.imageUrl = str(info.imageUrl) ?? draft.imageUrl;
  draft.priceUsd = num(pair.priceUsd) ?? draft.priceUsd;
  draft.volume24h = num(volume.h24) ?? draft.volume24h;
  draft.volume1h = num(volume.h1) ?? draft.volume1h;
  draft.volume5m = num(volume.m5) ?? draft.volume5m;
  draft.priceChange24h = num(change.h24) ?? draft.priceChange24h;
  draft.priceChange1h = num(change.h1) ?? draft.priceChange1h;
  draft.priceChange5m = num(change.m5) ?? draft.priceChange5m;
  draft.buys24h = num(h24.buys) ?? draft.buys24h;
  draft.sells24h = num(h24.sells) ?? draft.sells24h;
  draft.buys5m = num(m5.buys) ?? draft.buys5m;
  draft.sells5m = num(m5.sells) ?? draft.sells5m;
  const pairLiq = num(asRecord(pair.liquidity).usd);
  if (pairLiq != null) {
    draft.liquidityUsd = Math.max(draft.liquidityUsd ?? 0, pairLiq);
  }
  const created = num(pair.pairCreatedAt);
  if (created != null) {
    draft.pairCreatedAt = draft.pairCreatedAt == null ? created : Math.min(draft.pairCreatedAt, created);
  }
  draft.twitterUrl = twitter ?? draft.twitterUrl;
  draft.telegramUrl = telegram ?? draft.telegramUrl;
  draft.websiteUrl = str(asRecord(websites[0]).url) ?? draft.websiteUrl;
  draft.dexScreenerUrl = str(pair.url) ?? draft.dexScreenerUrl;
  draft.boostAmount = Math.max(draft.boostAmount, num(asRecord(pair.boosts).active) ?? 0);
}

let jupiterCache: { at: number; rows: Json[] } | null = null;

async function loadJupiterVerified(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  let rows: Json[] = [];
  if (jupiterCache && Date.now() - jupiterCache.at < BOARD_CACHE_MS) {
    rows = jupiterCache.rows;
  } else {
    const payload = await fetchJson<unknown>(
      "https://lite-api.jup.ag/tokens/v2/tag?query=verified",
      12_000
    );
    rows = asArray(payload).map(asRecord);
    if (rows.length) jupiterCache = { at: Date.now(), rows };
  }
  if (!rows.length) return false;

  let used = 0;
  for (const row of rows) {
    if (applyJupiterToken(byMint, bySymbol, asRecord(row), true)) used += 1;
  }

  return used > 0;
}

function applyJupiterToken(
  byMint: Map<string, Draft>,
  bySymbol: Map<string, Draft>,
  item: Json,
  requireVerified: boolean,
) {
  const tags = asArray(item.tags).map((tag) => String(tag).toLowerCase());
  const verified = item.isVerified === true || tags.includes("verified");
  if (requireVerified && !verified) return false;
  const mint = str(item.id);
  const symbol = str(item.symbol) ?? "";
  const name = str(item.name) ?? symbol;
  const marketCap = num(item.mcap);
  const liquidityUsd = num(item.liquidity);
  const organicScore = num(item.organicScore);
  if (!mint || mint === WSOL || SKIP_MINTS.has(mint)) return false;
  if (SKIP_SYMBOLS.has(normalizeSymbol(symbol))) return false;
  if (SKIP_NAME_RE.test(name)) return false;
  if (marketCap == null || marketCap < MIN_MCAP || marketCap > MAX_MCAP) return false;
  if ((liquidityUsd ?? 0) < MIN_LIQ) return false;
  if (requireVerified && organicScore != null && organicScore < MIN_ORGANIC && marketCap < 4_000_000) {
    return false;
  }

  const stats5m = asRecord(item.stats5m);
  const stats1h = asRecord(item.stats1h);
  const stats24h = asRecord(item.stats24h);
  const draft = byMint.get(mint) ?? emptyDraft(mint, name, symbol);
  draft.name = name || draft.name;
  draft.symbol = symbol || draft.symbol;
  draft.imageUrl = str(item.icon) ?? draft.imageUrl;
  draft.priceUsd = num(item.usdPrice) ?? draft.priceUsd;
  draft.marketCap = marketCap ?? draft.marketCap;
  draft.liquidityUsd = liquidityUsd ?? draft.liquidityUsd;
  draft.volume5m = (num(stats5m.buyVolume) ?? 0) + (num(stats5m.sellVolume) ?? 0) || draft.volume5m;
  draft.volume1h = (num(stats1h.buyVolume) ?? 0) + (num(stats1h.sellVolume) ?? 0) || draft.volume1h;
  draft.volume24h = (num(stats24h.buyVolume) ?? 0) + (num(stats24h.sellVolume) ?? 0) || draft.volume24h;
  draft.priceChange5m = num(stats5m.priceChange) ?? draft.priceChange5m;
  draft.priceChange1h = num(stats1h.priceChange) ?? draft.priceChange1h;
  draft.priceChange24h = num(stats24h.priceChange) ?? draft.priceChange24h;
  draft.buys5m = num(stats5m.numBuys) ?? draft.buys5m;
  draft.sells5m = num(stats5m.numSells) ?? draft.sells5m;
  draft.buys24h = num(stats24h.numBuys) ?? draft.buys24h;
  draft.sells24h = num(stats24h.numSells) ?? draft.sells24h;
  const created = str(asRecord(item.firstPool).createdAt);
  if (created) draft.pairCreatedAt = Date.parse(created);
  draft.listed = true;
  draft.verified = verified || draft.verified;
  draft.organicScore = organicScore ?? draft.organicScore;
  byMint.set(mint, draft);
  bySymbol.set(normalizeSymbol(draft.symbol), draft);
  return true;
}

async function hydrateTrendingFromJupiter(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const missing = [...byMint.values()]
    .filter((draft) => draft.geckoTerminalRank != null)
    .slice(0, 20);
  await Promise.all(
    missing.map(async (draft) => {
      const payload = await fetchJson<unknown>(
        `https://lite-api.jup.ag/tokens/v2/search?query=${encodeURIComponent(draft.mint)}`,
      );
      const row = asArray(payload)
        .map(asRecord)
        .find((item) => str(item.id) === draft.mint);
      if (row) applyJupiterToken(byMint, bySymbol, row, false);
    }),
  );
}

function ingestGeckoPool(
  byMint: Map<string, Draft>,
  bySymbol: Map<string, Draft>,
  pool: Json,
  included: Map<string, Json>,
  rank: number | null
) {
  const attributes = asRecord(pool.attributes);
  const rel = asRecord(asRecord(asRecord(pool.relationships).base_token).data);
  const tokenAttr = asRecord(asRecord(included.get(str(rel.id) ?? "") ?? {}).attributes);
  const mint = str(tokenAttr.address);
  const symbol = str(tokenAttr.symbol) ?? str(attributes.name)?.split("/")[0]?.trim() ?? "";
  const name = str(tokenAttr.name) ?? symbol;
  if (!mint || mint === WSOL || SKIP_MINTS.has(mint)) return false;
  if (SKIP_SYMBOLS.has(normalizeSymbol(symbol)) || SKIP_NAMES.has(foldName(name))) return false;
  if (SKIP_NAME_RE.test(name)) return false;

  const created = str(attributes.pool_created_at);
  const createdMs = created ? Date.parse(created) : NaN;
  const ageHours = Number.isFinite(createdMs) ? (Date.now() - createdMs) / 3_600_000 : null;
  if (ageHours != null && ageHours < MIN_LAUNCH_HOURS) return false;

  const draft = byMint.get(mint) ?? emptyDraft(mint, name, symbol);
  const volume = asRecord(attributes.volume_usd);
  const change = asRecord(attributes.price_change_percentage);
  if (!draft.verified) {
    draft.name = name;
    draft.symbol = symbol;
  }
  draft.imageUrl = draft.imageUrl ?? str(tokenAttr.image_url);
  draft.priceUsd = num(attributes.base_token_price_usd) ?? draft.priceUsd;
  draft.marketCap = num(attributes.market_cap_usd) ?? num(attributes.fdv_usd) ?? draft.marketCap;
  draft.volume24h = num(volume.h24) ?? draft.volume24h;
  draft.volume1h = num(volume.h1) ?? draft.volume1h;
  draft.volume5m = num(volume.m5) ?? draft.volume5m;
  draft.priceChange24h = num(change.h24) ?? draft.priceChange24h;
  draft.priceChange1h = num(change.h1) ?? draft.priceChange1h;
  draft.priceChange5m = num(change.m5) ?? draft.priceChange5m;
  if (Number.isFinite(createdMs)) {
    draft.pairCreatedAt =
      draft.pairCreatedAt == null ? createdMs : Math.min(draft.pairCreatedAt, createdMs);
  }
  if (rank != null) draft.geckoTerminalRank = rank;
  byMint.set(mint, draft);
  bySymbol.set(normalizeSymbol(symbol), draft);
  return true;
}

function geckoIncluded(payload: Json) {
  const included = new Map<string, Json>();
  for (const row of asArray(payload.included)) {
    const item = asRecord(row);
    const id = str(item.id);
    if (id) included.set(id, item);
  }
  return included;
}

async function loadGeckoTerminal(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<Json>(
    "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?include=base_token&page=1"
  );
  if (!payload) return false;
  const included = geckoIncluded(payload);
  let rank = 0;
  let used = false;
  for (const row of asArray(payload.data)) {
    rank += 1;
    if (ingestGeckoPool(byMint, bySymbol, asRecord(row), included, rank)) used = true;
    if (rank >= 20) break;
  }
  return used;
}

async function loadNewPools(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<Json>(
    "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?include=base_token&page=1"
  );
  if (!payload) return false;
  const included = geckoIncluded(payload);
  let used = false;
  for (const row of asArray(payload.data)) {
    const attributes = asRecord(asRecord(row).attributes);
    const volume = asRecord(attributes.volume_usd);
    if ((num(volume.h1) ?? 0) < 1500 && (num(volume.m5) ?? 0) < 400) continue;
    if (ingestGeckoPool(byMint, bySymbol, asRecord(row), included, null)) used = true;
  }
  return used;
}

async function loadDexSearch(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<Json>("https://api.dexscreener.com/latest/dex/search?q=solana");
  const pairs = asArray(payload?.pairs);
  if (!pairs.length) return false;
  let used = false;
  for (const row of pairs) {
    const pair = asRecord(row);
    if (str(pair.chainId) !== "solana") continue;
    const base = asRecord(pair.baseToken);
    const mint = str(base.address);
    const symbol = str(base.symbol) ?? "";
    const name = str(base.name) ?? symbol;
    if (!mint || mint === WSOL || SKIP_MINTS.has(mint)) continue;
    if (SKIP_SYMBOLS.has(normalizeSymbol(symbol)) || SKIP_NAMES.has(foldName(name))) continue;
    const created = num(pair.pairCreatedAt);
    if (created != null && (Date.now() - created) / 3_600_000 < MIN_LAUNCH_HOURS) continue;
    const draft = byMint.get(mint);
    if (!draft) continue;
    applyDexPair(draft, pair);
    used = true;
  }
  return used;
}

async function enrichDexScreener(byMint: Map<string, Draft>, mints: string[]) {
  const unique = [...new Set(mints.filter(Boolean))].slice(0, 60);
  if (!unique.length) return false;
  const chunks: string[][] = [];
  for (let i = 0; i < unique.length; i += 30) chunks.push(unique.slice(i, i + 30));
  const payloads = await Promise.all(
    chunks.map((chunk) =>
      fetchJson<unknown>(`https://api.dexscreener.com/tokens/v1/solana/${chunk.join(",")}`)
    )
  );
  const pairs = payloads.flatMap((payload) => asArray(payload));
  if (!pairs.length) return false;

  const grouped = new Map<string, Json[]>();
  for (const row of pairs) {
    const pair = asRecord(row);
    const mint = str(asRecord(pair.baseToken).address);
    if (!mint) continue;
    const list = grouped.get(mint) ?? [];
    list.push(pair);
    grouped.set(mint, list);
  }

  for (const [mint, mintPairs] of grouped) {
    const pair = pickDexPair(mintPairs);
    const draft = byMint.get(mint);
    if (!pair || !draft) continue;
    applyDexPair(draft, pair);
  }
  return true;
}

async function attachCoinGecko(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const [trending, markets] = await Promise.all([
    fetchJson<Json>("https://api.coingecko.com/api/v3/search/trending"),
    fetchJson<
      {
        id: string;
        symbol: string;
        name: string;
        image?: string;
        current_price?: number;
        market_cap?: number;
        total_volume?: number;
        price_change_percentage_1h_in_currency?: number;
        price_change_percentage_24h?: number;
      }[]
    >(
      "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=solana-ecosystem&order=volume_desc&per_page=80&price_change_percentage=1h,24h"
    ),
  ]);

  let used = false;
  asArray(trending?.coins).forEach((row, index) => {
    const item = asRecord(asRecord(row).item);
    const symbol = str(item.symbol);
    const name = str(item.name);
    if (!symbol || !name) return;
    const draft = bySymbol.get(normalizeSymbol(symbol));
    if (!draft || !namesAlign(draft.name, draft.symbol, name, symbol)) return;
    draft.coinGeckoRank = index + 1;
    used = true;
  });

  for (const coin of markets ?? []) {
    const draft = bySymbol.get(normalizeSymbol(coin.symbol));
    if (!draft || !namesAlign(draft.name, draft.symbol, coin.name, coin.symbol)) continue;
    draft.listed = true;
    draft.imageUrl = draft.imageUrl ?? coin.image ?? null;
    draft.priceUsd = draft.priceUsd ?? coin.current_price ?? null;
    used = true;
  }

  return used;
}

type XInfo = {
  xScore: number;
  handle: string;
  followers: number | null;
  tweetCount: number | null;
  posts: XPost[];
  authors: number;
  crowd: boolean;
};

function pairAgeHours(draft: Draft): number | null {
  if (!draft.pairCreatedAt) return null;
  return Math.max(0, (Date.now() - draft.pairCreatedAt) / 3_600_000);
}

function buyPressure(draft: Draft): number | null {
  const total = draft.buys5m + draft.sells5m;
  if (!total) return null;
  return draft.buys5m / total;
}

function trendingRank(draft: Draft) {
  const gecko = draft.geckoTerminalRank ?? 99;
  const coin = draft.coinGeckoRank ?? 99;
  return Math.min(gecko, coin);
}

function isTrending(draft: Draft) {
  return (
    draft.geckoTerminalRank != null ||
    draft.coinGeckoRank != null ||
    (draft.volume1h ?? 0) >= 25_000 ||
    ((draft.volume24h ?? 0) >= 250_000 && (draft.priceChange1h ?? 0) >= 1.5)
  );
}

function isUniverse(draft: Draft): boolean {
  const strongTrend = draft.geckoTerminalRank != null && draft.geckoTerminalRank <= 20;
  if (!draft.verified && !strongTrend) return false;
  if (SKIP_SYMBOLS.has(normalizeSymbol(draft.symbol))) return false;
  if (SKIP_NAMES.has(foldName(draft.name)) || SKIP_NAME_RE.test(draft.name)) return false;
  const mcap = draft.marketCap ?? 0;
  if (mcap < MIN_MCAP || mcap > MAX_MCAP) return false;
  if ((draft.liquidityUsd ?? 0) < MIN_LIQ && !strongTrend) return false;
  const age = pairAgeHours(draft);
  if (age != null && age < MIN_LAUNCH_HOURS) return false;
  return true;
}

function isHeating(draft: Draft): boolean {
  if (!isUniverse(draft)) return false;
  return isTrending(draft) || (draft.volume1h ?? 0) >= 80_000 || (draft.volume24h ?? 0) >= 1_000_000;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function pickTopContracts(tokens: HypeToken[], winner: HypeToken | null, count = 4) {
  const out: HypeToken[] = [];
  const seen = new Set<string>();
  const push = (token: HypeToken | null | undefined) => {
    if (!token?.mint || seen.has(token.mint)) return;
    if (!token.verified && token.geckoTerminalRank == null) return;
    if (token.check?.verdict === "danger") return;
    seen.add(token.mint);
    out.push(token);
  };

  push(winner);
  for (const token of tokens) {
    if (out.length >= count) break;
    push(token);
  }
  return out.slice(0, count);
}

function scoreDraft(draft: Draft, x?: XInfo): HypeToken {
  const socialScore = rankPoints(draft.coinGeckoRank, 15);
  const momentumScore = rankPoints(draft.geckoTerminalRank, 20);
  const volumeScore = logScale(draft.volume24h ?? draft.volume1h, 40_000_000);
  const whaleScore = logScale(draft.volume1h, 3_000_000);
  const txnScore = logScale(draft.buys5m + draft.sells5m, 8_000);
  const pressure = buyPressure(draft);
  const pressureScore = pressure == null ? 45 : pressure * 100;
  const heatScore = volumeScore * 0.45 + whaleScore * 0.35 + txnScore * 0.2;
  const xScore = x?.xScore ?? 0;
  const age = pairAgeHours(draft);
  const change1h = draft.priceChange1h ?? 0;
  const change24h = draft.priceChange24h ?? 0;

  const reasons: string[] = [];
  const trendScore = Math.max(momentumScore, socialScore);
  const heat1h = clamp(Math.abs(change1h) * 2.2 + Math.max(change1h, 0), 0, 100);
  const orgScore = draft.organicScore ?? 40;
  const liveX = x?.crowd ? x.xScore : 0;
  const hypeScore = Math.round(
    clamp(
      volumeScore * 0.34 +
        whaleScore * 0.2 +
        trendScore * 0.24 +
        heat1h * 0.08 +
        orgScore * 0.06 +
        liveX * 0.08,
      0,
      100,
    ),
  );

  if (draft.geckoTerminalRank) {
    reasons.push(`#${draft.geckoTerminalRank} trending GeckoTerminal`);
  }
  if (draft.coinGeckoRank) reasons.push(`#${draft.coinGeckoRank} trending CoinGecko`);
  if ((draft.volume24h ?? 0) >= 1_000_000) {
    reasons.push(`Soldi forti: ${((draft.volume24h ?? 0) / 1_000_000).toFixed(1)}M$ di volume 24h`);
  } else if ((draft.volume1h ?? 0) >= 80_000) {
    reasons.push(`Flusso sull’ora: $${Math.round((draft.volume1h ?? 0) / 1000)}k`);
  }
  if (change24h >= 40) {
    reasons.push(`Ha già corso +${change24h.toFixed(0)}% e il volume c’è ancora`);
  } else if (change1h >= 0.8) {
    reasons.push(`In accelerazione sull’ora: ${change1h >= 0 ? "+" : ""}${change1h.toFixed(1)}%`);
  }
  if (x?.crowd && (x.authors > 0 || x.posts.length > 0)) {
    reasons.push(
      x.authors > 1
        ? `${x.authors} persone stanno postando $${draft.symbol.replace(/^\$/, "")} su X — non è l’account ufficiale`
        : `Gente che posta $${draft.symbol.replace(/^\$/, "")} su X, fuori dal profilo ufficiale`,
    );
  }
  if ((draft.marketCap ?? 0) >= 1_000_000) {
    reasons.push(`Market cap ${((draft.marketCap ?? 0) / 1_000_000).toFixed(1)}M`);
  } else if ((draft.marketCap ?? 0) >= MIN_MCAP) {
    reasons.push(`Market cap $${Math.round((draft.marketCap ?? 0) / 1000)}k — sopra i 200k`);
  }
  if (draft.verified) reasons.push("Jupiter verified");
  if ((draft.organicScore ?? 0) >= 80) {
    reasons.push(`Flusso organico alto su Jupiter (${Math.round(draft.organicScore ?? 0)})`);
  }
  if (pressure != null && pressure >= 0.56) {
    reasons.push(`Pressione d’acquisto 5m: ${Math.round(pressure * 100)}% buy`);
  }
  if (!reasons.length) {
    reasons.push("Volume e trending in corso");
  }

  return {
    mint: draft.mint,
    name: draft.name,
    symbol: draft.symbol.replace(/^\$/, ""),
    imageUrl: draft.imageUrl,
    priceUsd: draft.priceUsd,
    marketCap: draft.marketCap,
    volume24h: draft.volume24h,
    volume1h: draft.volume1h,
    volume5m: draft.volume5m,
    priceChange24h: draft.priceChange24h,
    priceChange1h: draft.priceChange1h,
    priceChange5m: draft.priceChange5m,
    buys24h: draft.buys24h,
    sells24h: draft.sells24h,
    buys5m: draft.buys5m,
    sells5m: draft.sells5m,
    buyPressure5m: pressure,
    liquidityUsd: draft.liquidityUsd,
    pairAgeHours: age,
    freshBoost: draft.freshBoost,
    twitterUrl: draft.twitterUrl,
    telegramUrl: draft.telegramUrl,
    websiteUrl: draft.websiteUrl,
    dexScreenerUrl: draft.dexScreenerUrl,
    boostAmount: draft.boostAmount,
    coinGeckoRank: draft.coinGeckoRank,
    geckoTerminalRank: draft.geckoTerminalRank,
    listed: draft.listed,
    verified: draft.verified,
    organicScore: draft.organicScore,
    hypeScore,
    socialScore: Math.round(socialScore),
    momentumScore: Math.round(momentumScore),
    heatScore: Math.round(heatScore),
    xScore: Math.round(xScore),
    xHandle: twitterHandle(draft.twitterUrl),
    xFollowers: x?.crowd ? x.authors : x?.followers ?? null,
    xTweetCount: x?.tweetCount ?? null,
    xPosts: x?.crowd ? x.posts : [],
    reasons,
    check: null,
  };
}

let computing: Promise<HypeResponse> | null = null;

export async function peekHypeBoard() {
  return peekStoredBoard();
}

export async function getHypeBoard(options?: {
  skipNotify?: boolean;
  fresh?: boolean;
}): Promise<HypeResponse> {
  const stored = await readStoredBoard();
  if (!options?.fresh && stored && isBoardFresh(stored)) {
    return stampBoard(stored.board, stored.at);
  }
  if (!options?.fresh && computing) {
    return computing;
  }

  const run = computeHypeBoard(options, stored);
  if (!options?.fresh) computing = run.finally(() => {
    computing = null;
  });
  return run;
}

async function computeHypeBoard(
  options: { skipNotify?: boolean; fresh?: boolean } | undefined,
  stored: Awaited<ReturnType<typeof readStoredBoard>>,
): Promise<HypeResponse> {
  try {
  const byMint = new Map<string, Draft>();
  const bySymbol = new Map<string, Draft>();

  const jupiter = await loadJupiterVerified(byMint, bySymbol);
  const geckoTerminal = await loadGeckoTerminal(byMint, bySymbol);
  await hydrateTrendingFromJupiter(byMint, bySymbol);
  const dexSearch = await loadDexSearch(byMint, bySymbol);

  const preUniverse = [...byMint.values()];
  const enrichTargets = [...preUniverse]
    .filter((draft) => draft.verified || draft.geckoTerminalRank != null)
    .sort((a, b) => {
      const vol = (b.volume24h ?? 0) - (a.volume24h ?? 0);
      if (Math.abs(vol) > 50_000) return vol;
      const trend = trendingRank(a) - trendingRank(b);
      if (trend !== 0) return trend;
      return (b.volume1h ?? 0) - (a.volume1h ?? 0);
    })
    .slice(0, 40)
    .map((draft) => draft.mint);
  const dexScreener = (await enrichDexScreener(byMint, enrichTargets)) || dexSearch;
  const coinGecko = await attachCoinGecko(byMint, bySymbol);

  const universe = [...byMint.values()].filter(isUniverse);

  let heatingDrafts = universe.filter(isHeating);
  if (heatingDrafts.length < 10) {
    const extra = universe
      .filter((draft) => !heatingDrafts.includes(draft))
      .sort((a, b) => (b.volume24h ?? 0) - (a.volume24h ?? 0));
    heatingDrafts = [...heatingDrafts, ...extra].slice(0, 10);
  }

  const crowdTalks = await loadCrowdTalks(
    [...heatingDrafts]
      .sort((a, b) => (b.volume1h ?? b.volume24h ?? 0) - (a.volume1h ?? a.volume24h ?? 0))
      .slice(0, 4)
      .map((draft) => ({
        symbol: draft.symbol,
        name: draft.name,
        twitterUrl: draft.twitterUrl,
      }))
  );

  const heating = heatingDrafts
    .map((draft) => scoreDraft(draft, crowdTalks.get(normalizeSymbol(draft.symbol))))
    .sort((a, b) => b.hypeScore - a.hypeScore || (b.volume24h ?? 0) - (a.volume24h ?? 0))
    .slice(0, 12);

  const checks = await checkTokens(
    heating.slice(0, 4).map((token) => ({
      mint: token.mint,
      pairAgeHours: token.pairAgeHours,
    }))
  );

  const withCheck = (token: HypeToken): HypeToken => ({
    ...token,
    check: checks.get(token.mint) ?? token.check,
  });

  const checkedHeating = heating.map(withCheck);
  const winner =
    checkedHeating.find((token) => token.check?.verdict !== "danger") ?? checkedHeating[0] ?? null;
  const topContracts = pickTopContracts(checkedHeating, winner, 4);
  const board: HypeResponse = {
    generatedAt: new Date().toISOString(),
    winner,
    tokens: checkedHeating,
    topContracts,
    established: [],
    sources: {
      coinGecko,
      geckoTerminal,
      dexScreener,
      x: [...crowdTalks.values()].some((signal) => signal.posts.length > 0),
      rugcheck: checks.size > 0,
      jupiter,
    },
    note: "Seguiamo i soldi: trending + volume. Chi ha già pompato resta in lista. Verified quando c’è, i pezzi forti come i #1 trending non li perdiamo. Ricerca ogni 2 ore.",
  };

  const saved = await writeStoredBoard(board);
  if (!options?.skipNotify) {
    void notifyTopContracts(topContracts).catch(() => undefined);
  }
  return stampBoard(saved.board, saved.at);
  } catch (error) {
    if (stored) return stampBoard(stored.board, stored.at);
    throw error;
  }
}
