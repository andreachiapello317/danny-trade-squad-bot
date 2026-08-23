export type XPost = {
  id: string;
  url: string;
  text: string;
  likes: number;
  views: number;
  replies: number;
  retweets: number;
  createdAt: string | null;
  author: string | null;
};

export type HypeToken = {
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
  buyPressure5m: number | null;
  liquidityUsd: number | null;
  pairAgeHours: number | null;
  freshBoost: boolean;
  twitterUrl: string | null;
  telegramUrl: string | null;
  websiteUrl: string | null;
  dexScreenerUrl: string | null;
  boostAmount: number;
  coinGeckoRank: number | null;
  geckoTerminalRank: number | null;
  listed: boolean;
  verified: boolean;
  organicScore: number | null;
  hypeScore: number;
  socialScore: number;
  momentumScore: number;
  heatScore: number;
  xScore: number;
  xHandle: string | null;
  xFollowers: number | null;
  xTweetCount: number | null;
  xPosts: XPost[];
  reasons: string[];
  check: TokenCheck | null;
};

export type TokenCheck = {
  verdict: "pass" | "caution" | "danger" | "unknown";
  label: string;
  rugScore: number | null;
  mintRevoked: boolean | null;
  freezeRevoked: boolean | null;
  lpLockedPct: number | null;
  topHolderPct: number | null;
  holders: number | null;
  rugged: boolean;
  xMintInPosts: boolean | null;
  xAccountAgeHours: number | null;
  notes: string[];
};

export type HypeResponse = {
  generatedAt: string;
  winner: HypeToken | null;
  tokens: HypeToken[];
  established: HypeToken[];
  sources: {
    coinGecko: boolean;
    geckoTerminal: boolean;
    dexScreener: boolean;
    x: boolean;
    rugcheck: boolean;
    jupiter: boolean;
  };
  note: string;
};
