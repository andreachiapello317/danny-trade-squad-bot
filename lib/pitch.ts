import type { HypeToken, XPost } from "@/lib/types";

const KNOWN_STORIES: Array<{
  symbols?: string[];
  names?: RegExp;
  story: string;
}> = [
  {
    symbols: ["CYBERLEEK"],
    names: /cyber\s*leek/i,
    story:
      "Cyberleek gira per l’hype del leak GTA: è il meme di un momento culturale, il porro cyberpunk di cui si parla, non un progetto da manuale.",
  },
  {
    symbols: ["PENGU"],
    names: /pudgy\s*penguin/i,
    story:
      "PENGU è Pudgy Penguins: un nome che su Solana già conoscono, i pinguini NFT e il merch, non un ticker uscito ieri.",
  },
  {
    symbols: ["PUMP"],
    names: /^pump$/i,
    story:
      "PUMP è il gettone di pump.fun, la piazza dei meme su Solana: quando si muove, è la piattaforma di nuovo al centro della chiacchiera.",
  },
];

function ticker(token: HypeToken) {
  return `$${token.symbol.replace(/^\$/, "")}`;
}

function symbolKey(token: HypeToken) {
  return token.symbol.replace(/^\$/, "").toUpperCase();
}

function officialHandle(token: HypeToken) {
  const raw = token.xHandle?.replace(/^@/, "").trim();
  if (!raw) return null;
  if (!/^[A-Za-z0-9_]{1,15}$/.test(raw)) return null;
  return raw;
}

function crowdAuthors(token: HypeToken): string[] {
  const official = officialHandle(token)?.toLowerCase() ?? "";
  const seen = new Set<string>();
  const authors: string[] = [];
  for (const post of token.xPosts) {
    const handle = post.author?.replace(/^@/, "").trim();
    if (!handle || !/^[A-Za-z0-9_]{1,15}$/.test(handle)) continue;
    const key = handle.toLowerCase();
    if (key === official || seen.has(key)) continue;
    seen.add(key);
    authors.push(handle);
    if (authors.length >= 3) break;
  }
  return authors;
}

function knownStory(token: HypeToken): string | null {
  const key = symbolKey(token);
  const name = token.name ?? "";
  for (const row of KNOWN_STORIES) {
    if (row.symbols?.includes(key)) return row.story;
    if (row.names?.test(name)) return row.story;
  }
  return null;
}

function liveStoryFromPosts(token: HypeToken, posts: XPost[]): string | null {
  if (knownStory(token)) return null;
  const blob = posts
    .map((post) => post.text)
    .join(" ")
    .toLowerCase();
  if (!blob.trim()) return null;
  const name = ticker(token);
  if (/\bgta\b|grand theft auto/.test(blob)) {
    return `${name} sta girando sul leak GTA: un momento culturale, non un progetto da scheda tecnica.`;
  }
  if (/\bpudgy|penguin/.test(blob) && !/\bpengu/.test(symbolKey(token).toLowerCase())) {
    return `${name} torna in chiacchiera con i pinguini: un nome già noto, non un lancio sconosciuto.`;
  }
  return null;
}

function crowdLine(token: HypeToken, authors: string[]): string | null {
  if (!authors.length) return null;
  const name = ticker(token);
  if (authors.length === 1) {
    return `Twittato da @${authors[0]}: la gente sta postando ${name}.`;
  }
  if (authors.length === 2) {
    return `Twittato da @${authors[0]} e @${authors[1]}: la gente sta postando ${name}.`;
  }
  return `Twittato da @${authors[0]}, @${authors[1]} e @${authors[2]}: la gente sta postando ${name}.`;
}

function officialContext(token: HypeToken, hasCrowd: boolean): string | null {
  const handle = officialHandle(token);
  if (hasCrowd) {
    return handle
      ? `Il profilo @${handle} resta solo contesto: il radar ascolta la gente, non l’account ufficiale.`
      : null;
  }
  if (handle) {
    return `Non abbiamo tweet della gente da citare adesso; @${handle} c’è, ma vale solo come contesto, non come prova.`;
  }
  return null;
}

function heatColor(token: HypeToken): string | null {
  const gecko = token.geckoTerminalRank;
  const coin = token.coinGeckoRank;
  const veryHot = (gecko != null && gecko <= 3) || (coin != null && coin <= 3);
  const listed = gecko != null || coin != null;
  if (veryHot) return "Resta il nome del giorno sulle liste Solana.";
  if (listed) return "Sta girando nelle liste del giorno, senza essere l’unica storia.";
  if ((token.organicScore ?? 0) >= 80) {
    return "Il flusso sulla chain c’è, anche se la storia su X è sottile.";
  }
  return null;
}

function alreadyRan(token: HypeToken): string | null {
  if ((token.priceChange24h ?? 0) >= 80) {
    return "Ha già corso forte: il hype può essere in coda, non all’inizio.";
  }
  if ((token.priceChange1h ?? 0) <= -10) {
    return "Sull’ora il chiasso si è un po’ spento.";
  }
  return null;
}

function noStoryLine(token: HypeToken, hasCrowd: boolean) {
  if (hasCrowd) {
    return "Manca una storia chiara oltre al chiasso su X, il segnale è solo flusso.";
  }
  return `Manca una storia chiara su ${ticker(token)}, il segnale è solo flusso.`;
}

/** 2–4 frasi italiane: hype, chi parla su X, colore delle liste. Mai “sicuro da comprare”. */
export function tokenPitch(token: HypeToken): string {
  const authors = crowdAuthors(token);
  const narrative = knownStory(token) ?? liveStoryFromPosts(token, token.xPosts);
  const sentences: string[] = [];

  if (narrative) sentences.push(narrative);
  const crowd = crowdLine(token, authors);
  if (crowd) sentences.push(crowd);
  if (!narrative) sentences.push(noStoryLine(token, authors.length > 0));

  const official = officialContext(token, authors.length > 0);
  if (official && sentences.length < 4) sentences.push(official);

  const ran = alreadyRan(token);
  if (ran && sentences.length < 4) sentences.push(ran);

  const heat = heatColor(token);
  if (heat && sentences.length < 4) sentences.push(heat);

  return sentences.slice(0, 4).join(" ");
}
