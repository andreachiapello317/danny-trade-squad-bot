export type HypeToken = {
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
  hypeScore: number;
  socialScore: number;
  momentumScore: number;
  heatScore: number;
  reasons: string[];
};

export type HypeResponse = {
  generatedAt: string;
  winner: HypeToken | null;
  tokens: HypeToken[];
  sources: {
    coinGecko: boolean;
    geckoTerminal: boolean;
    dexScreener: boolean;
  };
  note: string;
};
