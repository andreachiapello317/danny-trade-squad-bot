export const HOT_KINDS = ["must_read", "bullish", "trending", "my_buy"] as const;

export function isHotPost(kind: string) {
  return (HOT_KINDS as readonly string[]).includes(kind);
}

export function routePost(kind: string) {
  if (kind === "how_to") return ["ceo"] as const;
  if (isHotPost(kind)) return ["analyst", "sender"] as const;
  return ["analyst"] as const;
}

export const KIND_LABEL: Record<string, string> = {
  must_read: "MUST READ",
  bullish: "Bullish Signals",
  trending: "Trending",
  my_buy: "My BUY",
  how_to: "HOW TO",
  other: "Altro",
};

export const ROLE_LABEL: Record<string, string> = {
  reader: "Reader",
  analyst: "Analyst",
  ceo: "CEO",
  sender: "Sender",
  trader: "Trader",
};

