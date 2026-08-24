import type { HypeToken } from "@/lib/types";

function usdShort(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M$`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}k$`;
  return `${Math.round(value)}$`;
}

/** 1–2 motivi italiani dal ranking. Mai “sicuro” o profitto garantito. */
export function pumpWhy(token: HypeToken): string {
  const picked = token.reasons.map((reason) => reason.trim()).filter(Boolean).slice(0, 2);
  if (picked.length) return picked.join(". ");

  const bits: string[] = [];
  if ((token.volume1h ?? 0) > 0) bits.push(`volume 1h ${usdShort(token.volume1h!)}`);
  else if ((token.volume24h ?? 0) > 0) bits.push(`volume 24h ${usdShort(token.volume24h!)}`);
  if (token.geckoTerminalRank) bits.push(`ancora in trending GeckoTerminal (#${token.geckoTerminalRank})`);
  else if (token.coinGeckoRank) bits.push(`ancora in trending CoinGecko (#${token.coinGeckoRank})`);
  if (token.verified) bits.push("Jupiter verified");
  if (bits.length) return `Segnali da ${bits.join(", ")}.`;
  return "In lista per volume e trending, senza altri segnali chiari adesso.";
}
