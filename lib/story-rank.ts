import { hasKnownStory } from "@/lib/pitch";
import type { HypeToken, XPost } from "@/lib/types";
import { isNoisePost } from "@/lib/x-noise";

const MEME_SUFFIXES = [
  "LEEK",
  "GTA",
  "CATS",
  "CAT",
  "KITTY",
  "INU",
  "PEPE",
  "DOGE",
  "DOGS",
  "DOG",
  "PUPPY",
  "FROG",
  "WOJAK",
  "ELON",
  "MOON",
];

const EXTREME_24H_PCT = 1000;
const LOW_ORGANIC = 80;
const CLOSE_SCORE = 8;
const REAL_FLOW_MCAP = 200_000;
const REAL_FLOW_MIN_AGE_HOURS = 0.5;
const REAL_FLOW_VOLUME_1H = 50_000;
const REAL_FLOW_VOLUME_24H = 500_000;

export type Rankable = {
  mint: string;
  name: string;
  symbol: string;
  verified: boolean;
  organicScore: number | null;
  marketCap: number | null;
  geckoTerminalRank: number | null;
  coinGeckoRank: number | null;
  priceChange24h: number | null;
  volume24h?: number | null;
  volume1h?: number | null;
  volume5m?: number | null;
  pairAgeHours?: number | null;
  pairCreatedAt?: number | null;
  xScore?: number;
  xPosts?: XPost[];
};

export function isPumpFunMint(mint: string) {
  return mint.toLowerCase().endsWith("pump");
}

export function compactTicker(value: string) {
  return value.replace(/^\$/, "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function stripMemeSuffix(value: string) {
  const ordered = [...MEME_SUFFIXES].sort((a, b) => b.length - a.length);
  for (const suffix of ordered) {
    if (value.endsWith(suffix) && value.length - suffix.length >= 4) {
      return value.slice(0, -suffix.length);
    }
  }
  return value;
}

function stemOf(value: string) {
  return stripMemeSuffix(compactTicker(value));
}

function sharedPrefixLen(a: string, b: string) {
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
  return i;
}

function extraMemeSuffix(full: string, leader: string) {
  if (!full.startsWith(leader) || full.length <= leader.length) return false;
  const extra = full.slice(leader.length);
  return MEME_SUFFIXES.some((suffix) => extra === suffix || extra.startsWith(suffix) || extra.endsWith(suffix));
}

/** CYBERCAT vs CYBERLEEK, BONKCAT vs BONK, extra CAT/LEEK/GTA on a leader. */
export function looksLikeClone(a: Rankable, b: Rankable) {
  if (a.mint === b.mint) return false;
  const as = compactTicker(a.symbol);
  const bs = compactTicker(b.symbol);
  const an = compactTicker(a.name);
  const bn = compactTicker(b.name);
  if (!as || !bs) return false;

  if (extraMemeSuffix(as, bs) || extraMemeSuffix(an, bn)) return true;
  if (extraMemeSuffix(bs, as) || extraMemeSuffix(bn, an)) return true;

  const aStem = stemOf(a.symbol);
  const bStem = stemOf(b.symbol);
  if (aStem.length >= 4 && aStem === bStem && as !== bs) return true;

  const aNameStem = stemOf(a.name);
  const bNameStem = stemOf(b.name);
  if (aNameStem.length >= 5 && aNameStem === bNameStem && an !== bn) return true;

  if (as.length >= 6 && bs.length >= 6 && sharedPrefixLen(as, bs) >= 5 && as !== bs) {
    const aRest = as.slice(sharedPrefixLen(as, bs));
    const bRest = bs.slice(sharedPrefixLen(as, bs));
    if (
      MEME_SUFFIXES.includes(aRest) ||
      MEME_SUFFIXES.includes(bRest) ||
      MEME_SUFFIXES.some((suffix) => aRest.endsWith(suffix) || bRest.endsWith(suffix))
    ) {
      return true;
    }
  }

  return false;
}

function ageHours(token: Rankable): number | null {
  if (token.pairAgeHours != null) return token.pairAgeHours;
  if (token.pairCreatedAt) return Math.max(0, (Date.now() - token.pairCreatedAt) / 3_600_000);
  return null;
}

/** Real story / listing quality. Explicitly ignores 5m volume so lookalikes cannot buy rank. */
export function authenticity(token: Rankable): number {
  let score = 0;
  if (token.verified) score += 50;
  if (hasKnownStory(token)) score += 30;
  if (token.coinGeckoRank != null) score += Math.max(0, 22 - token.coinGeckoRank);
  if (token.geckoTerminalRank != null) score += Math.max(0, 16 - token.geckoTerminalRank);
  score += (token.organicScore ?? 0) * 0.25;
  if ((token.marketCap ?? 0) > 0) {
    score += Math.min(20, Math.log10(token.marketCap ?? 1) * 2);
  }
  const age = ageHours(token);
  if (age != null && age >= 48) score += 8;
  else if (age != null && age >= 12) score += 3;
  return score;
}

export function hasRealXStory(token: Rankable) {
  if (hasKnownStory(token)) return true;
  const posts = (token.xPosts ?? []).filter((post) => post.text && !isNoisePost(post.text));
  if (posts.length < 2) return false;
  return (token.xScore ?? 0) >= 40;
}

/** GeckoTerminal trending + volume + mcap + age: soldi veri, anche su pump.fun. */
export function hasRealMoneyFlow(token: Rankable) {
  const age = ageHours(token);
  if (age != null && age < REAL_FLOW_MIN_AGE_HOURS) return false;
  if ((token.marketCap ?? 0) < REAL_FLOW_MCAP) return false;
  if (token.geckoTerminalRank == null || token.geckoTerminalRank < 1) return false;
  return (token.volume1h ?? 0) >= REAL_FLOW_VOLUME_1H || (token.volume24h ?? 0) >= REAL_FLOW_VOLUME_24H;
}

/** Thin pump.fun rugs. Strong-flow pumps stay eligible even at thousands of %. */
export function isScamTier(token: Rankable) {
  if (!isPumpFunMint(token.mint)) return false;
  if ((token.priceChange24h ?? 0) < EXTREME_24H_PCT) return false;
  if (hasRealMoneyFlow(token)) return false;
  return (token.organicScore ?? 0) < LOW_ORGANIC || !hasRealXStory(token);
}

export function findCopycatMints(tokens: Rankable[]): Set<string> {
  const copycats = new Set<string>();
  for (let i = 0; i < tokens.length; i++) {
    for (let j = i + 1; j < tokens.length; j++) {
      const a = tokens[i];
      const b = tokens[j];
      if (!looksLikeClone(a, b)) continue;
      const authA = authenticity(a);
      const authB = authenticity(b);
      if (authA === authB) continue;
      copycats.add(authA > authB ? b.mint : a.mint);
    }
  }
  return copycats;
}

export function eligibleForTop(token: HypeToken, copycats: Set<string>) {
  if (!token.mint) return false;
  if (token.check?.verdict === "danger") return false;
  if (copycats.has(token.mint)) return false;
  if (isScamTier(token)) return false;
  return true;
}

export function compareForTop(a: HypeToken, b: HypeToken, copycats: Set<string>) {
  const elig = Number(eligibleForTop(b, copycats)) - Number(eligibleForTop(a, copycats));
  if (elig) return elig;
  const score = b.hypeScore - a.hypeScore;
  if (Math.abs(score) >= CLOSE_SCORE) return score;
  return authenticity(b) - authenticity(a) || score;
}

export function applyStoryPenalties<T extends HypeToken>(tokens: T[], copycats: Set<string>): T[] {
  return tokens.map((token) => {
    let penalty = 0;
    const reasons = [...token.reasons];
    if (copycats.has(token.mint)) {
      penalty += 36;
      reasons.push("Clone di un nome già più caldo sulla stessa board — non è la storia vera");
    }
    if (isScamTier(token)) {
      penalty += 40;
      reasons.push("Pump.fun da migliaia di % senza trending/volume veri: rug sottile, non soldi forti");
    }
    return {
      ...token,
      hypeScore: Math.max(0, Math.min(100, token.hypeScore - penalty)),
      reasons,
    };
  });
}
