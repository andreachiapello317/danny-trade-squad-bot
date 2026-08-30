export type Rating = "Strong Buy" | "Buy" | "Hold" | "Sell" | "Sell Now";

export type RibbonSight =
  | "absent"
  | "red_widening"
  | "red_thinning"
  | "thick_blue_above";

export type CandleSight =
  | "absent"
  | "fresh_red_wm"
  | "dark_blue_continuation"
  | "yellow_weekly"
  | "yellow_monthly";

export type ChipSight =
  | "absent"
  | "above_support"
  | "below_resistance"
  | "flipped_res_to_sup";

export type HoleSight =
  | "absent"
  | "close_above_high"
  | "early_with_blue"
  | "close_in_middle"
  | "close_below_low";

export type Panel2Sight =
  | "absent"
  | "flip_green_red_widening"
  | "off_or_red_to_green";

export type PostKind =
  | "must_read"
  | "bullish"
  | "trending"
  | "my_buy"
  | "how_to"
  | "other";

export type Role = "reader" | "analyst" | "ceo" | "sender" | "trader";

export type Sighting = {
  ticker: string;
  name: string;
  hasDaily: boolean;
  hasWeekly: boolean;
  hasMonthly: boolean;
  hasFivePanelChart: boolean;
  chartImage: string | null;
  dailyLooksGood: boolean;
  ribbon: RibbonSight;
  ribbonExtension: boolean;
  candle: CandleSight;
  redAgeDays: number | null;
  chip: ChipSight;
  hole: HoleSight;
  panel2: Panel2Sight;
  whalePct: number | null;
  whaleRising: boolean;
  whaleDeclining: boolean;
  retailDominant: boolean;
  macdBearCrossBelowZero: boolean;
  rsiBelow50StackedWrong: boolean;
  atSupport: boolean;
  chaseClose: boolean;
  closePrice: string;
  accelPrice: string;
  invPrice: string;
  pricesCopiedFromCandle: boolean;
  zoneLow: string;
  zoneHigh: string;
  postId: string | null;
  notes: string;
};

export type ScorePart = {
  key: string;
  label: string;
  points: number;
};

export type ScoreResult = {
  sum: number;
  vote: number;
  rating: Rating;
  parts: ScorePart[];
  caps: { limit: number; reason: string }[];
  sellBranch: boolean;
  sellNow: boolean;
  notBuy: boolean;
  notFullBuy: boolean;
  inCartAsBuy: boolean;
  zone: { low: string; high: string } | null;
  explanation: string;
  warnings: string[];
};

export type Analysis = {
  id: string;
  sighting: Sighting;
  score: ScoreResult;
  updatedAt: string;
};

export type CeoMark = "pending" | "valida" | "non_valida";

export type CartRow = {
  analysisId: string;
  ticker: string;
  name: string;
  rating: Rating;
  vote: number;
  explanation: string;
  zone: { low: string; high: string } | null;
  chartImage: string | null;
  hasFivePanelChart: boolean;
  ceoMark: CeoMark;
};

export type Cart = {
  id: string;
  builtAt: string;
  rows: CartRow[];
  reds: CartRow[];
  marketOfferingEntry: boolean;
  headline: string;
  sentToCeoAt: string | null;
  sentToSenderAt: string | null;
};

export type IncomingPost = {
  id: string;
  source: "patreon" | "mail" | "incolla";
  kind: PostKind;
  title: string;
  body: string;
  ticker: string | null;
  imageUrl: string | null;
  receivedAt: string;
  routedTo: Role[];
};

export type TelegramOutboxItem = {
  id: string;
  kind: "hot_post" | "validated_cart" | "ceo_note";
  title: string;
  body: string;
  imageUrl: string | null;
  createdAt: string;
  sentAt: string | null;
  status: "queued" | "sent" | "blocked" | "mock";
  fromRole: Role;
};

export type TelegramSettings = {
  botToken?: string;
  chatId?: string;
};

export type SquadState = {
  posts: IncomingPost[];
  analyses: Analysis[];
  cart: Cart | null;
  previousCart: Cart | null;
  outbox: TelegramOutboxItem[];
  telegram: TelegramSettings;
  lastCeoDispatchAt: string | null;
  lastSenderPollAt: string | null;
  ceoNote: string;
};

export const CEO_CYCLE_MS = 4 * 60 * 60 * 1000;
export const SENDER_POLL_MS = 2 * 60 * 60 * 1000;
export const CART_SIZE = 10;
export const REDS_SIZE = 10;
