import type { TokenCheck, XPost } from "@/lib/types";
import type { XSignal } from "@/lib/x-signal";

type Json = Record<string, unknown>;

function asRecord(value: unknown): Json {
  return value && typeof value === "object" ? (value as Json) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

const cache = new Map<string, { at: number; value: TokenCheck }>();
const TTL_MS = 90_000;

function mentionsMint(mint: string, texts: Array<string | null | undefined>) {
  const full = mint.toLowerCase();
  const tail = mint.slice(-8).toLowerCase();
  return texts.some((text) => {
    const value = (text ?? "").toLowerCase();
    return value.includes(full) || (tail.length >= 8 && value.includes(tail));
  });
}

async function fetchRugReport(mint: string): Promise<Json | null> {
  try {
    const response = await fetch(`https://api.rugcheck.xyz/v1/tokens/${mint}/report`, {
      cache: "no-store",
      headers: {
        accept: "application/json",
        "user-agent": "solana-hype-radar/1.0",
      },
      signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) return null;
    return (await response.json()) as Json;
  } catch {
    return null;
  }
}

export function textMentionsMint(mint: string, posts: XPost[], extra: Array<string | null> = []) {
  return mentionsMint(mint, [...posts.map((post) => post.text), ...extra]);
}

export async function checkToken(
  mint: string,
  x?: XSignal | null,
  pairAgeHours?: number | null
): Promise<TokenCheck> {
  const cacheKey = `${mint}:${x?.handle ?? "nox"}`;
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.value;

  const report = await fetchRugReport(mint);
  const notes: string[] = [];
  if (!report) {
    const fallback: TokenCheck = {
      verdict: "unknown",
      label: "Check non disponibile",
      rugScore: null,
      mintRevoked: null,
      freezeRevoked: null,
      lpLockedPct: null,
      topHolderPct: null,
      holders: null,
      rugged: false,
      xMintInPosts: x ? textMentionsMint(mint, x.posts, [x.description]) : null,
      xAccountAgeHours: x?.accountAgeHours ?? null,
      notes: ["RugCheck non ha risposto. Non dare per buono il contratto."],
    };
    return fallback;
  }

  const token = asRecord(report.token);
  const mintAuthority = str(token.mintAuthority) ?? str(report.mintAuthority);
  const freezeAuthority = str(token.freezeAuthority) ?? str(report.freezeAuthority);
  const mintRevoked = !mintAuthority || mintAuthority.startsWith("11111111");
  const freezeRevoked = !freezeAuthority || freezeAuthority.startsWith("11111111");
  const rugged = Boolean(report.rugged);
  const rugScore = num(report.score_normalised) ?? num(report.score);
  const lpLockedPct = num(report.lpLockedPct);
  const holders = num(report.totalHolders);
  const topHolders = asArray(report.topHolders).map(asRecord);
  const topHolderPct = num(topHolders[0]?.pct);
  const risks = asArray(report.risks).map(asRecord);
  const dangerRisks = risks.filter((risk) => {
    const level = str(risk.level)?.toLowerCase();
    return level === "danger" || level === "critical" || (num(risk.score) ?? 0) >= 5000;
  });
  const warnRisks = risks.filter((risk) => str(risk.level)?.toLowerCase() === "warn");

  const xMintInPosts = x ? textMentionsMint(mint, x.posts, [x.description]) : null;
  const xAccountAgeHours = x?.accountAgeHours ?? null;

  if (rugged) notes.push("RugCheck lo segna come già rugged.");
  if (!mintRevoked) notes.push("Mint authority ancora attiva: possono stampare token.");
  if (!freezeRevoked) notes.push("Freeze authority attiva: possono bloccare i wallet.");
  if (lpLockedPct != null && lpLockedPct < 80) {
    notes.push(`LP locked solo al ${Math.round(lpLockedPct)}%.`);
  } else if (lpLockedPct != null && lpLockedPct >= 95) {
    notes.push(`LP locked al ${lpLockedPct.toFixed(1)}%.`);
  }
  if (topHolderPct != null && topHolderPct >= 20) {
    notes.push(`Il primo holder ha il ${topHolderPct.toFixed(1)}% (esclusa spesso la pool).`);
  }
  if (holders != null) notes.push(`${holders.toLocaleString("it-IT")} holder on-chain.`);
  for (const risk of [...dangerRisks, ...warnRisks].slice(0, 3)) {
    const name = str(risk.name) ?? "Rischio";
    const detail = str(risk.description);
    notes.push(detail ? `${name}: ${detail}` : name);
  }

  if (xMintInPosts) {
    notes.push(`Su X @${x?.handle} il mint compare nei post o nella bio.`);
  } else if (x && x.posts.length) {
    notes.push(`Su X @${x.handle} i post recenti non citano questo mint. Potrebbe essere un account copiato.`);
  } else if (!x) {
    notes.push("Nessun profilo X ufficiale da confrontare col mint.");
  }

  if (xAccountAgeHours != null && pairAgeHours != null && xAccountAgeHours < 6 && pairAgeHours < 6) {
    notes.push("Account X e pool nati quasi insieme: tipico dei launch, zero storia.");
  } else if (xAccountAgeHours != null && xAccountAgeHours < 12) {
    notes.push(`Account X creato ${xAccountAgeHours < 1 ? "da meno di un'ora" : `${xAccountAgeHours.toFixed(1)} ore fa`}.`);
  }

  let verdict: TokenCheck["verdict"] = "pass";
  let label = "Check base ok";
  if (rugged || !mintRevoked || !freezeRevoked || dangerRisks.length) {
    verdict = "danger";
    label = "Rischio alto";
  } else if (
    (rugScore ?? 0) >= 25 ||
    warnRisks.length > 0 ||
    (topHolderPct ?? 0) >= 25 ||
    xMintInPosts === false ||
    (xAccountAgeHours != null && xAccountAgeHours < 12)
  ) {
    verdict = "caution";
    label = "Attenzione";
  } else if (xMintInPosts) {
    label = "Check ok + mint su X";
  }

  const result: TokenCheck = {
    verdict,
    label,
    rugScore,
    mintRevoked,
    freezeRevoked,
    lpLockedPct,
    topHolderPct,
    holders,
    rugged,
    xMintInPosts,
    xAccountAgeHours,
    notes,
  };
  cache.set(cacheKey, { at: Date.now(), value: result });
  return result;
}

export async function checkTokens(
  items: Array<{ mint: string; x?: XSignal | null; pairAgeHours?: number | null }>
): Promise<Map<string, TokenCheck>> {
  const unique = items.slice(0, 8);
  const rows = await Promise.all(
    unique.map(async (item) => [item.mint, await checkToken(item.mint, item.x, item.pairAgeHours)] as const)
  );
  return new Map(rows);
}
