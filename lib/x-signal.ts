import type { XPost } from "@/lib/types";

export type XSignal = {
  handle: string;
  followers: number | null;
  tweetCount: number | null;
  verified: boolean;
  posts: XPost[];
  engagement: number;
  xScore: number;
};

type Json = Record<string, unknown>;

const cache = new Map<string, { at: number; value: XSignal }>();
const TTL_MS = 60_000;

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
  const pattern = new RegExp(
    `(?:x|twitter)\\.com/${handle}/status/(\\d{15,})`,
    "gi"
  );
  for (const match of html.matchAll(pattern)) {
    ids.add(match[1]);
  }
  if (!ids.size) {
    for (const match of html.matchAll(/status\/(\d{15,})/g)) {
      ids.add(match[1]);
    }
  }
  return [...ids].sort((a, b) => (a < b ? 1 : -1)).slice(0, 4);
}

function scoreSignal(signal: Omit<XSignal, "xScore" | "engagement">): XSignal {
  const views = signal.posts.reduce((sum, post) => sum + post.views, 0);
  const likes = signal.posts.reduce((sum, post) => sum + post.likes, 0);
  const replies = signal.posts.reduce((sum, post) => sum + post.replies, 0);
  const engagement = views + likes * 12 + replies * 18 + signal.posts.reduce((sum, post) => sum + post.retweets, 0) * 20;
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
  const cached = cache.get(handle.toLowerCase());
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
        } satisfies XPost;
      })
    )
  ).filter((post): post is XPost => Boolean(post));

  if (!user.screen_name && !posts.length && !ids.length) return null;

  const signal = scoreSignal({
    handle: str(user.screen_name) ?? handle,
    followers: num(user.followers),
    tweetCount: num(user.tweets),
    verified: Boolean(asRecord(user.verification).verified),
    posts,
  });
  cache.set(handle.toLowerCase(), { at: Date.now(), value: signal });
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
