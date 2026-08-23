import type { HypeResponse, HypeToken } from "@/lib/types";

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

function normalizeSymbol(symbol: string): string {
  return symbol.replace(/^\$/, "").trim().toUpperCase();
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
  priceChange24h: number | null;
  priceChange1h: number | null;
  buys24h: number;
  sells24h: number;
  buys5m: number;
  sells5m: number;
  liquidityUsd: number | null;
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
    priceChange24h: null,
    priceChange1h: null,
    buys24h: 0,
    sells24h: 0,
    buys5m: 0,
    sells5m: 0,
    liquidityUsd: null,
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
  draft.priceChange24h = num(change.h24) ?? draft.priceChange24h;
  draft.priceChange1h = num(change.h1) ?? draft.priceChange1h;
  draft.buys24h = num(h24.buys) ?? draft.buys24h;
  draft.sells24h = num(h24.sells) ?? draft.sells24h;
  draft.buys5m = num(m5.buys) ?? draft.buys5m;
  draft.sells5m = num(m5.sells) ?? draft.sells5m;
  draft.liquidityUsd = num(asRecord(pair.liquidity).usd) ?? draft.liquidityUsd;
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
    mergeDraft(draft, {
      name: str(tokenAttr.name) ?? draft.name,
      symbol,
      imageUrl: str(tokenAttr.image_url),
      priceUsd: num(attributes.base_token_price_usd),
      marketCap: num(attributes.market_cap_usd) ?? num(attributes.fdv_usd),
      volume24h: num(volume.h24),
      volume1h: num(volume.h1),
      priceChange24h: num(change.h24),
      priceChange1h: num(change.h1),
      geckoTerminalRank: rank,
    });
    byMint.set(mint, draft);
    bySymbol.set(normalizeSymbol(symbol), draft);
    if (rank >= 20) break;
  }

  return rank > 0;
}

async function loadBoosts(byMint: Map<string, Draft>, bySymbol: Map<string, Draft>) {
  const payload = await fetchJson<unknown>("https://api.dexscreener.com/token-boosts/top/v1");
  if (!payload) return false;
  let used = false;
  for (const row of asArray(payload)) {
    const item = asRecord(row);
    if (str(item.chainId) !== "solana") continue;
    const mint = str(item.tokenAddress);
    if (!mint) continue;
    const draft = byMint.get(mint) ?? emptyDraft(mint, mint.slice(0, 6), mint.slice(0, 6));
    mergeDraft(draft, {
      boostAmount: num(item.totalAmount) ?? 0,
      twitterUrl: asArray(item.links)
        .map((link) => asRecord(link))
        .find((link) => str(link.type) === "twitter" || str(link.url)?.includes("x.com"))
        ?.url as string | undefined,
      websiteUrl: asArray(item.links)
        .map((link) => asRecord(link))
        .find((link) => !str(link.type) && str(link.url) && !str(link.url)?.includes("t.me"))
        ?.url as string | undefined,
      imageUrl: str(item.icon) ? `https://cdn.dexscreener.com/cms/images/${str(item.icon)}` : null,
    });
    byMint.set(mint, draft);
    bySymbol.set(normalizeSymbol(draft.symbol), draft);
    used = true;
  }
  return used;
}

async function enrichDexScreener(byMint: Map<string, Draft>) {
  const mints = [...byMint.keys()].slice(0, 30);
  if (!mints.length) return false;
  const payload = await fetchJson<unknown>(
    `https://api.dexscreener.com/tokens/v1/solana/${mints.join(",")}`
  );
  const pairs = asArray(payload);
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
      if (normalizeSymbol(symbol) !== normalizeSymbol(coin.symbol)) return;
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
    if (draft) {
      draft.coinGeckoRank = rank;
      used = true;
    } else {
      missing.push({ rank, symbol, name });
    }
  });

  if (missing.length) {
    await searchMissingCoinGecko(byMint, bySymbol, missing);
    used = true;
  }

  return used;
}

function scoreDraft(draft: Draft): HypeToken {
  const socialScore = rankPoints(draft.coinGeckoRank, 15);
  const momentumScore = rankPoints(draft.geckoTerminalRank, 20);
  const volumeScore = logScale(draft.volume24h, 80_000_000);
  const txnScore = logScale(draft.buys24h + draft.sells24h, 250_000);
  const pressure =
    draft.buys5m + draft.sells5m > 0
      ? Math.min(100, (draft.buys5m / Math.max(draft.buys5m + draft.sells5m, 1)) * 100)
      : 40;
  const heatScore = volumeScore * 0.55 + txnScore * 0.25 + pressure * 0.2;
  const boostScore = Math.min(100, draft.boostAmount / 10);
  const hypeScore = Math.round(
    socialScore * 0.48 + momentumScore * 0.24 + heatScore * 0.22 + boostScore * 0.06
  );

  const reasons: string[] = [];
  if (draft.coinGeckoRank === 1) {
    reasons.push("Primo nel trending globale CoinGecko (proxy dell'attenzione social/search, vicino all'hype su X)");
  } else if (draft.coinGeckoRank) {
    reasons.push(`#${draft.coinGeckoRank} nel trending CoinGecko`);
  }
  if (draft.geckoTerminalRank === 1) {
    reasons.push("Primo nei pool Solana in tendenza su GeckoTerminal");
  } else if (draft.geckoTerminalRank) {
    reasons.push(`#${draft.geckoTerminalRank} nei trending pool Solana`);
  }
  if ((draft.volume24h ?? 0) >= 10_000_000) {
    reasons.push("Volume 24h sopra i 10 milioni di dollari");
  }
  if (draft.boostAmount >= 200) {
    reasons.push(`Boost DexScreener attivi: ${draft.boostAmount}`);
  }
  if ((draft.priceChange24h ?? 0) >= 100) {
    reasons.push(`Pump 24h: +${Math.round(draft.priceChange24h ?? 0)}%`);
  }

  return {
    ...draft,
    hypeScore,
    socialScore: Math.round(socialScore),
    momentumScore: Math.round(momentumScore),
    heatScore: Math.round(heatScore),
    reasons,
  };
}

export async function getHypeBoard(): Promise<HypeResponse> {
  const byMint = new Map<string, Draft>();
  const bySymbol = new Map<string, Draft>();

  const [geckoTerminal, boosts] = await Promise.all([
    loadGeckoTerminal(byMint, bySymbol),
    loadBoosts(byMint, bySymbol),
  ]);

  const dexScreener = await enrichDexScreener(byMint);
  const coinGecko = await loadCoinGecko(byMint, bySymbol);
  if (coinGecko) {
    await enrichDexScreener(byMint);
  }

  const tokens = [...byMint.values()]
    .map(scoreDraft)
    .sort((a, b) => b.hypeScore - a.hypeScore || (b.volume24h ?? 0) - (a.volume24h ?? 0))
    .slice(0, 12);

  return {
    generatedAt: new Date().toISOString(),
    winner: tokens[0] ?? null,
    tokens,
    sources: {
      coinGecko,
      geckoTerminal,
      dexScreener: dexScreener || boosts,
    },
    note: "La ricerca post su X non è disponibile su questo account. Il punteggio usa CoinGecko Trending come proxy di attenzione social, più momentum DEX su Solana.",
  };
}
