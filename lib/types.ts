export type Stock = {
  symbol: string;
  name: string;
  priceUsd: number | null;
  changeUsd: number | null;
  changePct: number | null;
  volume: number | null;
  marketCap: number | null;
  exchange: string;
  sector: string | null;
  nasdaq100: boolean;
  score: number;
  reasons: string[];
  xUrl: string;
  chartUrl: string;
  nasdaqUrl: string;
};

export type StockBoard = {
  generatedAt: string;
  nextSearchAt?: string;
  winner: Stock | null;
  stocks: Stock[];
  topTickers: Stock[];
  sources: {
    nasdaqMovers: boolean;
    nasdaqQuotes: boolean;
  };
  note: string;
};
