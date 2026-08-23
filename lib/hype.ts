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
]);

const SKIP_NAMES = new Set(["test", "testing", "asdf", "aaa"]);

const ESTABLISHED_SYMBOLS = new Set(["PUMP", "TRUMP", "PENGU", "BONK", "WIF", "JUP", "JTO", "HYPE"]);

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
  };
}

function mergeDraft(target: Draft, patch: Partial<Draft>) {
  for (const [key, value] of Object.entries(patch) as [keyof Draft, Draft[keyof Draft]][]) {
    if (value == null || value === "" || value === 0) continue;
    const current = target[key];
    if (current == null || current === "" || current === 0) {
      (target[key] as Draft[keyof Draft]) = value;
    }
  }
  if ((patch.boostAmount ?? 0) > target.boostAmount) {
    target.boostAmount = patch.boostAmount ?? 0;
  }
  if (patch.coinGeckoRank != null) target.coinGeckoRank = patch.coinGeckoRank;
  if (patch.geckoTerminalRank != null) target.geckoTerminalRank = patch.geckoTerminalRank;
  if (patch.freshBoost) target.freshBoost = true;
  if (patch.pairCreatedAt != null) target.pairCreatedAt = patch.pairCreatedAt;
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
  const base = asRecord(pair.baseToken);
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

  draft.name = str(base.name) ?? draft.name;
  draft.symbol = str(base.symbol) ?? draft.symbol;
  draft.imageUrl = str(info.imageUrl) ?? draft.imageUrl;
  draft.priceUsd = num(pair.priceUsd) ?? draft.priceUsd;
  draft.marketCap = num(pair.marketCap) ?? num(pair.fdv) ?? draft.marketCap;
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

async function loadGeckoTerminal(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
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
  for (const row of asArray(payload.data)) {
    const pool = asRecord(row);
    const attributes = asRecord(pool.attributes);
    const rel = asRecord(asRecord(asRecord(pool.relationships).base_token).data);
    const token = included.get(str(rel.id) ?? "") ?? {};
    const tokenAttr = asRecord(asRecord(token).attributes);
    const mint = str(tokenAttr.address);
    const symbol = str(tokenAttr.symbol) ?? str(attributes.name)?.split("/")[0]?.trim() ?? "";
    if (!mint || SKIP_SYMBOLS.has(normalizeSymbol(symbol)) || mint === WSOL) continue;
    rank += 1;
    const draft = byMint.get(mint) ?? emptyDraft(mint, str(tokenAttr.name) ?? symbol, symbol);
    const volume = asRecord(attributes.volume_usd);
    const change = asRecord(attributes.price_change_percentage);
    const created = str(attributes.pool_created_at);
    mergeDraft(draft, {
      name: str(tokenAttr.name) ?? draft.name,
      symbol,
      imageUrl: str(tokenAttr.image_url),
      priceUsd: num(attributes.base_token_price_usd),
      marketCap: num(attributes.market_cap_usd) ?? num(attributes.fdv_usd),
      volume24h: num(volume.h24),
      volume1h: num(volume.h1),
      volume5m: num(volume.m5),
      priceChange24h: num(change.h24),
      priceChange1h: num(change.h1),
      priceChange5m: num(change.m5),
      pairCreatedAt: created ? Date.parse(created) : null,
      geckoTerminalRank: rank,
    });
    byMint.set(mint, draft);
    bySymbol.set(normalizeSymbol(symbol), draft);
    if (rank >= 20) break;
  }

  return rank > 0;
}

function applyBoostRow(
  byMint: Map<string, Draft>,
  bySymbol: Map<string, Draft>,
  item: Json,
  fresh: boolean
) {
  if (str(item.chainId) !== "solana") return false;
  const mint = str(item.tokenAddress);
  if (!mint) return false;
  const draft = byMint.get(mint) ?? emptyDraft(mint, mint.slice(0, 6), mint.slice(0, 6));
  const twitter = asArray(item.links)
    .map((link) => asRecord(link))
    .find((link) => str(link.type) === "twitter" || str(link.url)?.includes("x.com"));
  const website = asArray(item.links)
    .map((link) => asRecord(link))
    .find((link) => !str(link.type) && str(link.url) && !str(link.url)?.includes("t.me"));
  mergeDraft(draft, {
    boostAmount: num(item.totalAmount) ?? 0,
    twitterUrl: str(twitter?.url),
    websiteUrl: str(website?.url),
    imageUrl: str(item.icon) ? `https://cdn.dexscreener.com/cms/images/${str(item.icon)}` : null,
    freshBoost: fresh,
  });
  if (str(item.description) && draft.name === draft.mint.slice(0, 6)) {
    draft.name = str(item.description)?.split("\n")[0]?.slice(0, 48) ?? draft.name;
  }
  byMint.set(mint, draft);
  bySymbol.set(normalizeSymbol(draft.symbol), draft);
  return true;
}

async function loadBoosts(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const [top, latest] = await Promise.all([
    fetchJson<unknown>("https://api.dexscreener.com/token-boosts/top/v1"),
    fetchJson<unknown>("https://api.dexscreener.com/token-boosts/latest/v1"),
  ]);
  let used = false;
  for (const row of asArray(top)) {
    if (applyBoostRow(byMint, bySymbol, asRecord(row), false)) used = true;
  }
  for (const row of asArray(latest)) {
    if (applyBoostRow(byMint, bySymbol, asRecord(row), true)) used = true;
  }
  return used;
}

async function loadNewPools(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<Json>(
    "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?include=base_token&page=1"
  );
  if (!payload) return false;
  const included = new Map<string, Json>();
  for (const row of asArray(payload.included)) {
    const item = asRecord(row);
    const id = str(item.id);
    if (id) included.set(id, item);
  }
  let used = false;
  for (const row of asArray(payload.data)) {
    const pool = asRecord(row);
    const attributes = asRecord(pool.attributes);
    const rel = asRecord(asRecord(asRecord(pool.relationships).base_token).data);
    const tokenAttr = asRecord(asRecord(included.get(str(rel.id) ?? "") ?? {}).attributes);
    const mint = str(tokenAttr.address);
    const symbol = str(tokenAttr.symbol) ?? str(attributes.name)?.split("/")[0]?.trim() ?? "";
    const name = str(tokenAttr.name) ?? symbol;
    if (!mint || SKIP_SYMBOLS.has(normalizeSymbol(symbol)) || SKIP_NAMES.has(foldName(name))) continue;
    const volume = asRecord(attributes.volume_usd);
    if ((num(volume.h1) ?? 0) < 1500 && (num(volume.m5) ?? 0) < 400) continue;
    const created = str(attributes.pool_created_at);
    const draft = byMint.get(mint) ?? emptyDraft(mint, name, symbol);
    mergeDraft(draft, {
      name,
      symbol,
      imageUrl: str(tokenAttr.image_url),
      priceUsd: num(attributes.base_token_price_usd),
      marketCap: num(attributes.market_cap_usd) ?? num(attributes.fdv_usd),
      volume24h: num(volume.h24),
      volume1h: num(volume.h1),
      volume5m: num(volume.m5),
      priceChange24h: num(asRecord(attributes.price_change_percentage).h24),
      priceChange1h: num(asRecord(attributes.price_change_percentage).h1),
      priceChange5m: num(asRecord(attributes.price_change_percentage).m5),
      pairCreatedAt: created ? Date.parse(created) : null,
    });
    byMint.set(mint, draft);
    bySymbol.set(normalizeSymbol(symbol), draft);
    used = true;
  }
  return used;
}

async function enrichDexScreener(byMint: Map<string, Draft>) {
  const mints = [...byMint.keys()];
  if (!mints.length) return false;
  const chunks: string[][] = [];
  for (let i = 0; i < Math.min(mints.length, 60); i += 30) {
    chunks.push(mints.slice(i, i + 30));
  }
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
    if (!pair) continue;
    const draft = byMint.get(mint) ?? emptyDraft(mint, mint.slice(0, 6), mint.slice(0, 6));
    applyDexPair(draft, pair);
    if (SKIP_SYMBOLS.has(normalizeSymbol(draft.symbol))) {
      byMint.delete(mint);
      continue;
    }
    byMint.set(mint, draft);
  }
  return true;
}

async function searchMissingCoinGecko(
  byMint: Map<string, Draft>,
  bySymbol: Map<string, Draft>,
  missing: { rank: number; symbol: string; name: string }[]
) {
  await Promise.all(
    missing.slice(0, 4).map(async (coin) => {
      const payload = await fetchJson<Json>(
        `https://api.dexscreener.com/latest/dex/search?q=${encodeURIComponent(coin.symbol)}`
      );
      const pair = pickDexPair(asArray(payload?.pairs));
      if (!pair) return;
      const mint = str(asRecord(pair.baseToken).address);
      const symbol = str(asRecord(pair.baseToken).symbol);
      if (!mint || !symbol || SKIP_SYMBOLS.has(normalizeSymbol(symbol))) return;
      if (!namesAlign(str(asRecord(pair.baseToken).name) ?? symbol, symbol, coin.name, coin.symbol)) {
        return;
      }
      const draft = byMint.get(mint) ?? emptyDraft(mint, coin.name, symbol);
      applyDexPair(draft, pair);
      draft.coinGeckoRank = coin.rank;
      byMint.set(mint, draft);
      bySymbol.set(normalizeSymbol(symbol), draft);
    })
  );
}

async function loadCoinGecko(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<Json>("https://api.coingecko.com/api/v3/search/trending");
  if (!payload) return false;
  const missing: { rank: number; symbol: string; name: string }[] = [];
  let used = false;

  asArray(payload.coins).forEach((row, index) => {
    const item = asRecord(asRecord(row).item);
    const symbol = str(item.symbol);
    const name = str(item.name);
    if (!symbol || !name) return;
    const rank = index + 1;
    const draft = bySymbol.get(normalizeSymbol(symbol));
    const marketCapText = str(asRecord(item.data).market_cap);
    const marketCap = num(marketCapText);
    if (draft && namesAlign(draft.name, draft.symbol, name, symbol)) {
      draft.coinGeckoRank = rank;
      used = true;
    } else if (!draft && (marketCap == null || marketCap < 250_000_000)) {
      missing.push({ rank, symbol, name });
    }
  });

  if (missing.length) {
    await searchMissingCoinGecko(byMint, bySymbol, missing);
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

function isEstablished(draft: Draft): boolean {
  const mcap = draft.marketCap ?? 0;
  if (ESTABLISHED_SYMBOLS.has(normalizeSymbol(draft.symbol))) return true;
  if (mcap >= 12_000_000) return true;
  if ((draft.priceChange24h ?? 0) >= 2000 && mcap >= 4_000_000) return true;
  return false;
}

function isImminentCandidate(draft: Draft): boolean {
  if (SKIP_NAMES.has(foldName(draft.name)) || SKIP_SYMBOLS.has(normalizeSymbol(draft.symbol))) {
    return false;
  }
  if (isEstablished(draft)) return false;
  const mcap = draft.marketCap;
  if (mcap != null && (mcap < 12_000 || mcap > 12_000_000)) return false;
  if ((draft.liquidityUsd ?? 0) < 4_000 && (draft.volume1h ?? 0) < 8_000) return false;
  if ((draft.priceChange5m ?? 0) <= -35) return false;
  const age = pairAgeHours(draft);
  if (age != null && age < 0.2 && ((draft.liquidityUsd ?? 0) < 8_000 || (draft.volume1h ?? 0) < 8_000)) {
    return false;
  }
  const activity = draft.buys5m + draft.sells5m;
  return (
    activity >= 6 ||
    (draft.volume5m ?? 0) >= 800 ||
    (draft.volume1h ?? 0) >= 15_000 ||
    draft.freshBoost ||
    (age != null && age <= 18 && (draft.volume1h ?? 0) >= 3_000)
  );
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function scoreDraft(draft: Draft, x?: XInfo, mode: "imminent" | "established" = "established"): HypeToken {
  const socialScore = rankPoints(draft.coinGeckoRank, 15);
  const momentumScore = rankPoints(draft.geckoTerminalRank, 20);
  const volumeScore = logScale(draft.volume24h, 80_000_000);
  const txnScore = logScale(draft.buys24h + draft.sells24h, 250_000);
  const pressure = buyPressure(draft);
  const pressureScore = pressure == null ? 40 : pressure * 100;
  const heatScore = volumeScore * 0.55 + txnScore * 0.25 + pressureScore * 0.2;
  const boostScore = Math.min(100, draft.boostAmount / 10);
  const xScore = x?.xScore ?? 0;
  const age = pairAgeHours(draft);

  let hypeScore: number;
  const reasons: string[] = [];

  if (mode === "imminent") {
    const activityScore = logScale(draft.buys5m + draft.sells5m, 500);
    const expectedHourly = (draft.volume24h ?? 0) / 24;
    const accel = expectedHourly > 200 ? (draft.volume1h ?? 0) / expectedHourly : (draft.volume1h ?? 0) / 8_000;
    const accelScore = clamp(accel * 28, 0, 100);
    const freshScore =
      age == null ? 25 : age <= 3 ? 100 : age <= 12 ? 82 : age <= 36 ? 55 : age <= 72 ? 28 : 8;
    const mcap = draft.marketCap ?? 400_000;
    const sizeScore = mcap < 50_000 ? 55 : mcap <= 2_000_000 ? 100 : mcap <= 5_000_000 ? 68 : 32;
    const green5m = clamp(((draft.priceChange5m ?? 0) + 15) * 1.4, 0, 100);
    const green1h = clamp(((draft.priceChange1h ?? 0) + 10) * 0.9, 0, 100);
    const alreadyPumped = (draft.priceChange24h ?? 0) > 1200 ? 35 : (draft.priceChange24h ?? 0) > 400 ? 12 : 0;
    const boostBonus = draft.freshBoost ? 22 : Math.min(12, draft.boostAmount / 40);
    const xEarly =
      x && (x.followers ?? 0) < 2500 && x.posts.length > 0 ? 28 : x && x.xScore >= 15 ? 12 : draft.twitterUrl ? 6 : 0;
    hypeScore = Math.round(
      clamp(
        pressureScore * 0.2 +
          activityScore * 0.14 +
          accelScore * 0.18 +
          freshScore * 0.14 +
          sizeScore * 0.1 +
          green5m * 0.08 +
          green1h * 0.06 +
          boostBonus * 0.05 +
          xEarly * 0.05 -
          alreadyPumped,
        0,
        100
      )
    );

    if (pressure != null && pressure >= 0.58) {
      reasons.push(`Pressione d'acquisto 5m: ${Math.round(pressure * 100)}% buy`);
    }
    if ((draft.volume5m ?? 0) >= 800) {
      reasons.push(`Volume ultimi 5 minuti: $${Math.round(draft.volume5m ?? 0).toLocaleString("it-IT")}`);
    }
    if (accel >= 2) {
      reasons.push(`Volume 1h ${accel.toFixed(1)}× più veloce della media giornaliera`);
    }
    if (age != null && age <= 36) {
      reasons.push(age < 1 ? "Pool nato da pochi minuti" : `Pool giovane: ${age < 10 ? age.toFixed(1) : Math.round(age)} ore`);
    }
    if (draft.freshBoost) {
      reasons.push("Boost DexScreener appena attivato: sta comprando visibilità adesso");
    }
    if ((draft.priceChange5m ?? 0) >= 8) {
      reasons.push(`Già verde sui 5 minuti: +${Math.round(draft.priceChange5m ?? 0)}%`);
    }
    if (x && x.posts.length) {
      reasons.push(`X @${x.handle} ha post freschi, account ancora piccolo`);
    }
    if (!reasons.length) {
      reasons.push("Attività in crescita, market cap ancora sotto i 12M");
    }
  } else {
    hypeScore = Math.round(
      xScore * 0.4 + socialScore * 0.28 + momentumScore * 0.18 + heatScore * 0.1 + boostScore * 0.04
    );
    if (x && x.xScore >= 20) {
      reasons.push(`X @${x.handle} già sopra i radar`);
    }
    if (draft.coinGeckoRank) reasons.push(`#${draft.coinGeckoRank} trending CoinGecko`);
    if (draft.geckoTerminalRank) reasons.push(`#${draft.geckoTerminalRank} pool Solana in tendenza`);
    if ((draft.volume24h ?? 0) >= 10_000_000) reasons.push("Volume 24h sopra i 10M");
  }

  return {
    mint: draft.mint,
    name: draft.name,
    symbol: draft.symbol,
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

  const [geckoTerminal, boosts, newPools] = await Promise.all([
    loadGeckoTerminal(byMint, bySymbol),
    loadBoosts(byMint, bySymbol),
    loadNewPools(byMint, bySymbol),
  ]);

  const dexScreener = await enrichDexScreener(byMint);
  const coinGecko = await loadCoinGecko(byMint, bySymbol);
  if (coinGecko) {
    await enrichDexScreener(byMint);
  }

  const drafts = [...byMint.values()];
  const imminentDrafts = drafts.filter(isImminentCandidate);
  const establishedDrafts = drafts.filter(isEstablished);

  const xSignals = await loadXSignals(
    [...imminentDrafts]
      .sort((a, b) => (b.volume1h ?? 0) - (a.volume1h ?? 0))
      .concat(establishedDrafts)
      .map((draft) => draft.twitterUrl)
  );

  const attach = (draft: Draft, mode: "imminent" | "established") => {
    const handle = twitterHandle(draft.twitterUrl)?.toLowerCase();
    return scoreDraft(draft, handle ? xSignals.get(handle) : undefined, mode);
  };

  const tokens = imminentDrafts
    .map((draft) => attach(draft, "imminent"))
    .sort((a, b) => b.hypeScore - a.hypeScore || (b.volume5m ?? 0) - (a.volume5m ?? 0))
    .slice(0, 12);

  const established = establishedDrafts
    .map((draft) => attach(draft, "established"))
    .sort((a, b) => b.hypeScore - a.hypeScore)
    .slice(0, 6);

  const checks = await checkTokens(
    await Promise.all(
      [...tokens.slice(0, 6), ...established.slice(0, 2)].map(async (token) => {
        const handle = twitterHandle(token.twitterUrl)?.toLowerCase();
        const x =
          (handle ? xSignals.get(handle) : null) ?? (await loadXSignal(token.twitterUrl));
        return { mint: token.mint, x, pairAgeHours: token.pairAgeHours };
      })
    )
  );

  const withCheck = (token: HypeToken): HypeToken => ({
    ...token,
    check: checks.get(token.mint) ?? token.check,
  });

  const checkedTokens = tokens.map(withCheck);
  const checkedEstablished = established.map(withCheck);

  return {
    generatedAt: new Date().toISOString(),
    winner: checkedTokens[0] ?? null,
    tokens: checkedTokens,
    established: checkedEstablished,
    sources: {
      coinGecko,
      geckoTerminal: geckoTerminal || newPools,
      dexScreener: dexScreener || boosts,
      x: xSignals.size > 0,
      rugcheck: checks.size > 0,
    },
    note: "Questa classifica cerca token ancora piccoli in accelerazione e li passa su RugCheck più i post X per vedere se il mint torna.",
  };
}
