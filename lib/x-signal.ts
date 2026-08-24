import type { XPost } from "@/lib/types";
import { CHECK_CACHE_MS } from "@/lib/timing";
import { isNoisePost } from "@/lib/x-noise";

export type XSignal = {
  handle: string;
  followers: number | null;
  tweetCount: number | null;
  verified: boolean;
  posts: XPost[];
  engagement: number;
  xScore: number;
  description: string | null;
  joinedAt: string | null;
  accountAgeHours: number | null;
  authors: number;
  crowd: boolean;
};

type Json = Record<string, unknown>;

const officialCache = new Map<string, { at: number; value: XSignal }>();
const crowdCache = new Map<string, { at: number; value: XSignal }>();
const TTL_MS = CHECK_CACHE_MS;

function asRecord(value: unknown): Json {
  return value && typeof value === "object" ? (value as Json) : {};
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function logScale(value: number | null, max: number): number {
  if (!value || value <= 0) return 0;
  return Math.min(100, (Math.log10(value + 1) / Math.log10(max + 1)) * 100);
}

export function twitterHandle(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "").toLowerCase();
    if (host !== "x.com" && host !== "twitter.com") return null;
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (!parts.length) return null;
    const first = parts[0];
    const blocked = new Set([
      "i",
      "intent",
      "search",
      "home",
      "explore",
      "hashtag",
      "share",
      "compose",
      "messages",
      "notifications",
      "settings",
    ]);
    if (blocked.has(first.toLowerCase())) return null;
    return first.replace(/^@/, "");
  } catch {
    return null;
  }
}

async function fetchText(url: string, timeoutMs = 7000): Promise<string | null> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      headers: {
        accept: "text/html,application/xhtml+xml",
        "user-agent":
          "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
      },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) return null;
    return await response.text();
  } catch {
    return null;
  }
}

async function fetchJson<T>(url: string, timeoutMs = 7000): Promise<T | null> {
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

function extractStatusIds(html: string, handle: string): string[] {
  const ids = new Set<string>();
  const pattern = new RegExp(`(?:x|twitter)\\.com/${handle}/status/(\\d{15,})`, "gi");
  for (const match of html.matchAll(pattern)) ids.add(match[1]);
  if (!ids.size) {
    for (const match of html.matchAll(/status\/(\d{15,})/g)) ids.add(match[1]);
  }
  return [...ids].sort((a, b) => (a < b ? 1 : -1)).slice(0, 4);
}

function extractStatusLinks(html: string): Array<{ handle: string; id: string }> {
  const decoded = html
    .replace(/&amp;/g, "&")
    .replace(/\\\//g, "/")
    .replace(/%2F/gi, "/")
    .replace(/%3A/gi, ":");
  const found: Array<{ handle: string; id: string }> = [];
  const seen = new Set<string>();
  const pattern = /(?:x|twitter)\.com\/([A-Za-z0-9_]{1,15})\/status\/(\d{15,})/gi;
  for (const match of decoded.matchAll(pattern)) {
    const handle = match[1];
    const id = match[2];
    if (seen.has(id)) continue;
    if (["i", "intent", "search", "home", "explore"].includes(handle.toLowerCase())) continue;
    seen.add(id);
    found.push({ handle, id });
  }
  return found;
}

function mentionsToken(text: string, symbol: string, name: string) {
  const value = text.toLowerCase();
  const ticker = symbol.replace(/^\$/, "").toLowerCase();
  if (ticker.length >= 2 && (value.includes(`$${ticker}`) || value.includes(ticker))) return true;
  const folded = name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  return folded.length >= 4 && value.includes(folded);
}

function scoreCrowd(posts: XPost[], official: string | null): Omit<XSignal, "xScore" | "engagement"> & { engagement: number } {
  const people = posts.filter((post) => {
    const author = post.author?.toLowerCase();
    if (official && author && author === official) return false;
    if (isNoisePost(post.text)) return false;
    return true;
  });
  const authors = new Set(people.map((post) => post.author?.toLowerCase()).filter(Boolean));
  const views = people.reduce((sum, post) => sum + post.views, 0);
  const likes = people.reduce((sum, post) => sum + post.likes, 0);
  const replies = people.reduce((sum, post) => sum + post.replies, 0);
  const retweets = people.reduce((sum, post) => sum + post.retweets, 0);
  const engagement = views + likes * 12 + replies * 18 + retweets * 20;
  return {
    handle: "crowd",
    followers: authors.size,
    tweetCount: people.length,
    verified: false,
    posts: people.slice(0, 4),
    engagement,
    description: null,
    joinedAt: null,
    accountAgeHours: null,
    authors: authors.size,
    crowd: true,
  };
}

function finishCrowd(base: ReturnType<typeof scoreCrowd>): XSignal {
  const authorScore = logScale(base.authors, 20);
  const postScore = logScale(base.posts.length, 12);
  const engagementScore = logScale(base.engagement, 40_000);
  const xScore = Math.min(
    100,
    Math.round(authorScore * 0.5 + postScore * 0.2 + engagementScore * 0.3)
  );
  return { ...base, xScore };
}

async function hydratePosts(links: Array<{ handle: string; id: string }>, symbol: string, name: string) {
  const posts = (
    await Promise.all(
      links.slice(0, 5).map(async (link) => {
        const payload = await fetchJson<Json>(`https://api.fxtwitter.com/${link.handle}/status/${link.id}`);
        const tweet = asRecord(asRecord(payload).tweet);
        if (!str(tweet.id)) return null;
        const author = str(asRecord(tweet.author).screen_name) ?? link.handle;
        const text = (str(tweet.text) ?? "").replace(/\s+/g, " ").trim();
        if (text && !mentionsToken(text, symbol, name) && !mentionsToken(link.handle, symbol, name)) {
          if (!text.toLowerCase().includes("solana") && !text.toLowerCase().includes("pump")) return null;
        }
        return {
          id: str(tweet.id) ?? link.id,
          url: str(tweet.url) ?? `https://x.com/${author}/status/${link.id}`,
          text,
          likes: num(tweet.likes) ?? 0,
          views: num(tweet.views) ?? 0,
          replies: num(tweet.replies) ?? 0,
          retweets: num(tweet.retweets) ?? 0,
          createdAt: str(tweet.created_at),
          author,
        } satisfies XPost;
      })
    )
  ).filter((post): post is NonNullable<typeof post> => Boolean(post));
  return posts;
}

async function searchCrowdLinks(symbol: string, name: string) {
  const ticker = symbol.replace(/^\$/, "");
  const query = `$${ticker} ${name} solana`;
  const encoded = encodeURIComponent(query);
  const pages = await Promise.all([
    fetchText(`https://search.brave.com/search?q=${encoded}`),
    fetchText(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(`${query} site:x.com`)}`),
  ]);
  const links: Array<{ handle: string; id: string }> = [];
  const seen = new Set<string>();
  for (const page of pages) {
    if (!page) continue;
    for (const link of extractStatusLinks(page)) {
      if (seen.has(link.id)) continue;
      seen.add(link.id);
      links.push(link);
    }
  }
  return links;
}

export async function loadCrowdTalk(
  symbol: string,
  name: string,
  officialHandle: string | null
): Promise<XSignal | null> {
  const key = symbol.replace(/^\$/, "").toUpperCase();
  const cached = crowdCache.get(key);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.value;

  const official = officialHandle?.replace(/^@/, "").toLowerCase() ?? null;
  const links = (await searchCrowdLinks(symbol, name)).filter(
    (link) => link.handle.toLowerCase() !== official
  );
  const posts = await hydratePosts(links, symbol, name);
  const signal = finishCrowd(scoreCrowd(posts, official));
  crowdCache.set(key, { at: Date.now(), value: signal });
  return signal;
}

export async function loadCrowdTalks(
  tokens: Array<{ symbol: string; name: string; twitterUrl: string | null }>
): Promise<Map<string, XSignal>> {
  const unique = tokens.slice(0, 4);
  const rows = await Promise.all(
    unique.map(async (token) => {
      const signal = await loadCrowdTalk(token.symbol, token.name, twitterHandle(token.twitterUrl));
      return [token.symbol.replace(/^\$/, "").toUpperCase(), signal] as const;
    })
  );
  const map = new Map<string, XSignal>();
  for (const [symbol, signal] of rows) {
    if (signal) map.set(symbol, signal);
  }
  return map;
}

function scoreOfficial(signal: Omit<XSignal, "xScore" | "engagement">): XSignal {
  const views = signal.posts.reduce((sum, post) => sum + post.views, 0);
  const likes = signal.posts.reduce((sum, post) => sum + post.likes, 0);
  const replies = signal.posts.reduce((sum, post) => sum + post.replies, 0);
  const engagement =
    views + likes * 12 + replies * 18 + signal.posts.reduce((sum, post) => sum + post.retweets, 0) * 20;
  const followerScore = logScale(signal.followers, 80_000);
  const postScore = logScale(signal.posts.length * 20 + (signal.tweetCount ?? 0), 400);
  const engagementScore = logScale(engagement, 80_000);
  const verifiedBonus = signal.verified ? 8 : 0;
  const xScore = Math.min(
    100,
    Math.round(followerScore * 0.34 + engagementScore * 0.46 + postScore * 0.12 + verifiedBonus)
  );
  return { ...signal, engagement, xScore };
}

export async function loadXSignal(url: string | null): Promise<XSignal | null> {
  const handle = twitterHandle(url);
  if (!handle) return null;
  const cached = officialCache.get(handle.toLowerCase());
  if (cached && Date.now() - cached.at < TTL_MS) return cached.value;

  const [profileHtml, userPayload] = await Promise.all([
    fetchText(`https://x.com/${handle}`),
    fetchJson<Json>(`https://api.fxtwitter.com/${handle}`),
  ]);

  const user = asRecord(asRecord(userPayload).user);
  const ids = profileHtml ? extractStatusIds(profileHtml, handle) : [];
  const posts = (
    await Promise.all(
      ids.slice(0, 3).map(async (id) => {
        const payload = await fetchJson<Json>(`https://api.fxtwitter.com/${handle}/status/${id}`);
        const tweet = asRecord(asRecord(payload).tweet);
        if (!str(tweet.id)) return null;
        return {
          id: str(tweet.id) ?? id,
          url: str(tweet.url) ?? `https://x.com/${handle}/status/${id}`,
          text: (str(tweet.text) ?? "").replace(/\s+/g, " ").trim(),
          likes: num(tweet.likes) ?? 0,
          views: num(tweet.views) ?? 0,
          replies: num(tweet.replies) ?? 0,
          retweets: num(tweet.retweets) ?? 0,
          createdAt: str(tweet.created_at),
          author: str(asRecord(tweet.author).screen_name) ?? handle,
        } satisfies XPost;
      })
    )
  ).filter((post): post is NonNullable<typeof post> => Boolean(post));

  if (!user.screen_name && !posts.length && !ids.length) return null;

  const joinedAt = str(user.joined);
  const joinedMs = joinedAt ? Date.parse(joinedAt) : NaN;
  const signal = scoreOfficial({
    handle: str(user.screen_name) ?? handle,
    followers: num(user.followers),
    tweetCount: num(user.tweets),
    verified: Boolean(asRecord(user.verification).verified),
    posts,
    description: str(user.description),
    joinedAt,
    accountAgeHours: Number.isFinite(joinedMs)
      ? Math.max(0, (Date.now() - joinedMs) / 3_600_000)
      : null,
    authors: 1,
    crowd: false,
  });
  officialCache.set(handle.toLowerCase(), { at: Date.now(), value: signal });
  return signal;
}

export async function loadXSignals(
  urls: Array<string | null>
): Promise<Map<string, XSignal>> {
  const unique = [...new Set(urls.map(twitterHandle).filter((handle): handle is string => Boolean(handle)))];
  const results = await Promise.all(
    unique.slice(0, 8).map(async (handle) => {
      const signal = await loadXSignal(`https://x.com/${handle}`);
      return [handle.toLowerCase(), signal] as const;
    })
  );
  const map = new Map<string, XSignal>();
  for (const [handle, signal] of results) {
    if (signal) map.set(handle, signal);
  }
  return map;
}
