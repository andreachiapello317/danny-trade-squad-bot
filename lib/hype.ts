import type { HypeResponse, HypeToken, XPost } from "@/lib/types";
import { checkTokens } from "@/lib/legit";
import { loadXSignal, loadXSignals, twitterHandle } from "@/lib/x-signal";

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
]);

const SKIP_NAME_RE = /wormhole|xstock|wrapped|bridged|staked /i;

const MIN_MCAP = 15_000_000;
const MAX_MCAP = 5_000_000_000;
const MIN_LIQ = 800_000;
const MIN_ORGANIC = 45;
const ALREADY_PUMPED_24H = 80;

const WSOL = "So11111111111111111111111111111111111111112";

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
  draft.liquidityUsd = num(asRecord(pair.liquidity).usd) ?? draft.liquidityUsd;
  draft.pairCreatedAt = num(pair.pairCreatedAt) ?? draft.pairCreatedAt;
  draft.twitterUrl = twitter ?? draft.twitterUrl;
  draft.telegramUrl = telegram ?? draft.telegramUrl;
  draft.websiteUrl = str(asRecord(websites[0]).url) ?? draft.websiteUrl;
  draft.dexScreenerUrl = str(pair.url) ?? draft.dexScreenerUrl;
  draft.boostAmount = Math.max(draft.boostAmount, num(asRecord(pair.boosts).active) ?? 0);
}

let jupiterCache: { at: number; rows: Json[] } | null = null;

async function loadJupiterVerified(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  let rows: Json[] = [];
  if (jupiterCache && Date.now() - jupiterCache.at < 60_000) {
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
    const item = asRecord(row);
    if (item.isVerified !== true) continue;
    const mint = str(item.id);
    const symbol = str(item.symbol) ?? "";
    const name = str(item.name) ?? symbol;
    const marketCap = num(item.mcap);
    const liquidityUsd = num(item.liquidity);
    const organicScore = num(item.organicScore);
    if (!mint || mint === WSOL) continue;
    if (SKIP_SYMBOLS.has(normalizeSymbol(symbol))) continue;
    if (SKIP_NAME_RE.test(name)) continue;
    if (marketCap == null || marketCap < MIN_MCAP || marketCap > MAX_MCAP) continue;
    if ((liquidityUsd ?? 0) < MIN_LIQ) continue;
    if ((organicScore ?? 0) < MIN_ORGANIC) continue;

    const stats5m = asRecord(item.stats5m);
    const stats1h = asRecord(item.stats1h);
    const stats24h = asRecord(item.stats24h);
    const draft = byMint.get(mint) ?? emptyDraft(mint, name, symbol);
    draft.name = name;
    draft.symbol = symbol;
    draft.imageUrl = str(item.icon) ?? draft.imageUrl;
    draft.priceUsd = num(item.usdPrice) ?? draft.priceUsd;
    draft.marketCap = marketCap;
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
    draft.pairCreatedAt = created ? Date.parse(created) : draft.pairCreatedAt;
    draft.listed = true;
    draft.verified = true;
    draft.organicScore = organicScore;
    byMint.set(mint, draft);
    bySymbol.set(normalizeSymbol(symbol), draft);
    used += 1;
  }

  return used > 0;
}

async function attachGeckoTerminalRanks(byMint: Map<string, Draft>) {
  const payload = await fetchJson<Json>(
    "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools?include=base_token&page=1"
  );
  if (!payload) return false;

  const included = new Map<string, Json>();
  for (const row of asArray(payload.included)) {
    const item = asRecord(row);
    const id = str(item.id);
    if (id) included.set(id, item);
  }

  let rank = 0;
  let used = false;
  for (const row of asArray(payload.data)) {
    const pool = asRecord(row);
    const rel = asRecord(asRecord(asRecord(pool.relationships).base_token).data);
    const tokenAttr = asRecord(asRecord(included.get(str(rel.id) ?? "") ?? {}).attributes);
    const mint = str(tokenAttr.address);
    rank += 1;
    const draft = mint ? byMint.get(mint) : undefined;
    if (draft) {
      draft.geckoTerminalRank = rank;
      used = true;
    }
    if (rank >= 20) break;
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

function isUniverse(draft: Draft): boolean {
  if (SKIP_SYMBOLS.has(normalizeSymbol(draft.symbol))) return false;
  if (SKIP_NAME_RE.test(draft.name)) return false;
  if (!draft.verified && !draft.listed) return false;
  const mcap = draft.marketCap ?? 0;
  if (mcap < MIN_MCAP || mcap > MAX_MCAP) return false;
  if ((draft.liquidityUsd ?? 0) < MIN_LIQ) return false;
  return true;
}

function isAlreadyPumped(draft: Draft): boolean {
  return (draft.priceChange24h ?? 0) >= ALREADY_PUMPED_24H;
}

function isHeating(draft: Draft): boolean {
  if (!isUniverse(draft) || isAlreadyPumped(draft)) return false;
  const change1h = draft.priceChange1h ?? 0;
  const change24h = draft.priceChange24h ?? 0;
  if (change1h <= -8) return false;
  return (
    change1h >= 0.45 ||
    (change24h >= 6 && change24h < ALREADY_PUMPED_24H && change1h >= 0) ||
    ((draft.volume1h ?? 0) > 0 && (draft.volume24h ?? 0) > 0 && (draft.volume1h ?? 0) >= (draft.volume24h ?? 0) / 16)
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function scoreDraft(draft: Draft, x?: XInfo, mode: "heating" | "pumped" = "heating"): HypeToken {
  const socialScore = rankPoints(draft.coinGeckoRank, 15);
  const momentumScore = rankPoints(draft.geckoTerminalRank, 20);
  const volumeScore = logScale(draft.volume1h ?? draft.volume24h, 8_000_000);
  const txnScore = logScale(draft.buys5m + draft.sells5m, 8_000);
  const pressure = buyPressure(draft);
  const pressureScore = pressure == null ? 45 : pressure * 100;
  const heatScore = volumeScore * 0.55 + txnScore * 0.25 + pressureScore * 0.2;
  const xScore = x?.xScore ?? 0;
  const age = pairAgeHours(draft);
  const change1h = draft.priceChange1h ?? 0;
  const change24h = draft.priceChange24h ?? 0;

  const reasons: string[] = [];
  let hypeScore: number;

  if (mode === "heating") {
    const heat1h = clamp(change1h * 11, 0, 100);
    const confirm24 =
      change24h >= 6 && change24h <= 45 ? clamp(change24h * 1.35, 0, 60) : change24h > 0 && change24h < 6 ? change24h * 3 : 0;
    const latePenalty = change24h >= 70 ? 36 : change24h >= 50 ? 16 : 0;
    const dumpPenalty = change24h <= -40 ? 26 : change24h <= -22 ? 12 : 0;
    const orgScore = draft.organicScore ?? 50;
    const sizeScore = logScale(draft.marketCap, 3_000_000_000);
    const xEstablished =
      x && (x.followers ?? 0) >= 20_000 ? 22 : x && (x.followers ?? 0) >= 5_000 ? 12 : draft.twitterUrl ? 5 : 0;
    hypeScore = Math.round(
      clamp(
        heat1h * 0.3 +
          confirm24 * 0.12 +
          volumeScore * 0.12 +
          orgScore * 0.1 +
          sizeScore * 0.1 +
          pressureScore * 0.08 +
          socialScore * 0.08 +
          xEstablished * 0.1 -
          latePenalty -
          dumpPenalty,
        0,
        100
      )
    );

    if (change1h >= 0.8) {
      reasons.push(`In accelerazione sull’ora: ${change1h >= 0 ? "+" : ""}${change1h.toFixed(1)}%`);
    }
    if (change24h >= 6 && change24h < 50) {
      reasons.push(`Giornata già verde (+${change24h.toFixed(1)}%) senza essere esplosa`);
    }
    if ((draft.marketCap ?? 0) >= 50_000_000) {
      reasons.push(`Market cap ${((draft.marketCap ?? 0) / 1_000_000).toFixed(0)}M: non è un launch da un’ora`);
    }
    if (draft.verified) reasons.push("Presente nella lista Jupiter verified");
    if ((draft.organicScore ?? 0) >= 80) {
      reasons.push(`Flusso organico alto su Jupiter (${Math.round(draft.organicScore ?? 0)})`);
    }
    if (draft.coinGeckoRank) reasons.push(`#${draft.coinGeckoRank} trending CoinGecko`);
    if (x && (x.followers ?? 0) >= 10_000) {
      reasons.push(`X @${x.handle} ha ${(x.followers ?? 0).toLocaleString("it-IT")} follower`);
    }
    if (pressure != null && pressure >= 0.56) {
      reasons.push(`Pressione d’acquisto 5m: ${Math.round(pressure * 100)}% buy`);
    }
    if (!reasons.length) {
      reasons.push("Token già listato e in lieve accelerazione");
    }
  } else {
    hypeScore = Math.round(
      clamp(change24h / 4 + volumeScore * 0.25 + socialScore * 0.15 + (draft.organicScore ?? 40) * 0.15, 0, 100)
    );
    reasons.push(`Ha già corso: +${change24h.toFixed(0)}% sulle 24 ore`);
    if (change1h < 0) reasons.push("Sull’ora è già in raffreddamento");
    if (draft.verified) reasons.push("È listato, ma il pump grosso è già successo");
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
    xHandle: x?.handle ?? twitterHandle(draft.twitterUrl),
    xFollowers: x?.followers ?? null,
    xTweetCount: x?.tweetCount ?? null,
    xPosts: x?.posts ?? [],
    reasons,
    check: null,
  };
}

export async function getHypeBoard(): Promise<HypeResponse> {
  const byMint = new Map<string, Draft>();
  const bySymbol = new Map<string, Draft>();

  const jupiter = await loadJupiterVerified(byMint, bySymbol);
  const [geckoTerminal, coinGecko] = await Promise.all([
    attachGeckoTerminalRanks(byMint),
    attachCoinGecko(byMint, bySymbol),
  ]);

  const universe = [...byMint.values()].filter(isUniverse);
  const heatingDrafts = universe.filter(isHeating);
  const pumpedDrafts = universe.filter(isAlreadyPumped);

  const enrichTargets = [...heatingDrafts, ...pumpedDrafts]
    .sort((a, b) => (b.priceChange1h ?? 0) - (a.priceChange1h ?? 0))
    .slice(0, 36)
    .map((draft) => draft.mint);
  const dexScreener = await enrichDexScreener(byMint, enrichTargets);

  const xSignals = await loadXSignals(
    [...heatingDrafts]
      .sort((a, b) => (b.volume1h ?? 0) - (a.volume1h ?? 0))
      .slice(0, 8)
      .map((draft) => draft.twitterUrl)
  );

  const attach = (draft: Draft, mode: "heating" | "pumped") => {
    const handle = twitterHandle(draft.twitterUrl)?.toLowerCase();
    return scoreDraft(draft, handle ? xSignals.get(handle) : undefined, mode);
  };

  const heating = heatingDrafts
    .map((draft) => attach(draft, "heating"))
    .sort((a, b) => b.hypeScore - a.hypeScore || (b.priceChange1h ?? 0) - (a.priceChange1h ?? 0))
    .slice(0, 12);

  const pumped = pumpedDrafts
    .map((draft) => attach(draft, "pumped"))
    .sort((a, b) => (b.priceChange24h ?? 0) - (a.priceChange24h ?? 0))
    .slice(0, 6);

  const checks = await checkTokens(
    await Promise.all(
      [...heating.slice(0, 6), ...pumped.slice(0, 2)].map(async (token) => {
        const handle = twitterHandle(token.twitterUrl)?.toLowerCase();
        const x = (handle ? xSignals.get(handle) : null) ?? (await loadXSignal(token.twitterUrl));
        return { mint: token.mint, x, pairAgeHours: token.pairAgeHours };
      })
    )
  );

  const withCheck = (token: HypeToken): HypeToken => ({
    ...token,
    check: checks.get(token.mint) ?? token.check,
  });

  const checkedHeating = heating.map(withCheck).filter((token) => token.check?.verdict !== "danger");
  const checkedPumped = pumped.map(withCheck);

  return {
    generatedAt: new Date().toISOString(),
    winner: checkedHeating[0] ?? null,
    tokens: checkedHeating,
    established: checkedPumped,
    sources: {
      coinGecko,
      geckoTerminal,
      dexScreener,
      x: xSignals.size > 0,
      rugcheck: checks.size > 0,
      jupiter,
    },
    note: "Solo token Jupiter verified con market cap da 15M in su e liquidità reale. Cerchiamo l’accelerazione a 1 ora, non i launch da un’ora e non quelli già +80% oggi.",
  };
}
