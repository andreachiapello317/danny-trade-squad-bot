import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { buildCart } from "@/lib/cart";
import { isHotPost, routePost } from "@/lib/route";
import { emptySighting, scoreSighting } from "@/lib/score";
import { seedAnalyses, seedPosts } from "@/lib/seed";
import type {
  Analysis,
  Cart,
  IncomingPost,
  Sighting,
  SquadState,
  TelegramOutboxItem,
} from "@/lib/types";

const DATA_DIR = path.join(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "squad.json");

function freshState(): SquadState {
  const analyses = seedAnalyses();
  const cart = buildCart(analyses, null);
  const outbox: TelegramOutboxItem[] = seedPosts
    .filter((p) => isHotPost(p.kind))
    .map((p) => ({
      id: `out-${p.id}`,
      kind: "hot_post",
      title: p.title,
      body: p.body,
      imageUrl: p.imageUrl,
      createdAt: p.receivedAt,
      sentAt: null,
      status: "queued",
      fromRole: "reader",
    }));
  return {
    posts: seedPosts,
    analyses,
    cart,
    previousCart: null,
    outbox,
    telegram: {},
    lastCeoDispatchAt: null,
    lastSenderPollAt: null,
    ceoNote: "",
  };
}

async function load(): Promise<SquadState> {
  try {
    const raw = await readFile(STORE_PATH, "utf8");
    return JSON.parse(raw) as SquadState;
  } catch {
    const state = freshState();
    await save(state);
    return state;
  }
}

async function save(state: SquadState) {
  await mkdir(DATA_DIR, { recursive: true });
  await writeFile(STORE_PATH, JSON.stringify(state, null, 2));
}

export async function getSquad(): Promise<SquadState> {
  return load();
}

export async function resetSquad() {
  const state = freshState();
  await save(state);
  return state;
}

export async function ingestPost(
  input: Omit<IncomingPost, "id" | "receivedAt" | "routedTo">
) {
  const state = await load();
  const post: IncomingPost = {
    ...input,
    id: `post-${Date.now()}`,
    receivedAt: new Date().toISOString(),
    routedTo: [...routePost(input.kind)],
  };
  state.posts.unshift(post);

  if (isHotPost(post.kind)) {
    state.outbox.unshift({
      id: `out-${post.id}`,
      kind: "hot_post",
      title: post.title,
      body: post.body,
      imageUrl: post.imageUrl,
      createdAt: post.receivedAt,
      sentAt: null,
      status: "queued",
      fromRole: "reader",
    });
  }

  if (post.ticker) {
    const existing = state.analyses.find(
      (a) => a.sighting.ticker === post.ticker
    );
    if (!existing) {
      const sighting = emptySighting({
        ticker: post.ticker,
        name: post.ticker,
        postId: post.id,
        chartImage: post.imageUrl ?? `/api/chart/${post.ticker}`,
        hasFivePanelChart: Boolean(post.imageUrl),
        hasDaily: true,
        notes: post.body,
      });
      state.analyses.unshift({
        id: `an-${post.ticker.toLowerCase()}-${Date.now()}`,
        sighting,
        score: scoreSighting(sighting),
        updatedAt: new Date().toISOString(),
      });
    }
  }

  state.cart = buildCart(state.analyses, state.cart);
  await save(state);
  return { post, state };
}

export async function saveAnalysis(sighting: Sighting, id?: string) {
  const state = await load();
  const ticker = sighting.ticker.trim().toUpperCase();
  const nextSighting: Sighting = {
    ...sighting,
    ticker,
    chartImage: sighting.chartImage || `/api/chart/${ticker}`,
  };
  const score = scoreSighting(nextSighting);
  const existing = state.analyses.find(
    (a) => a.id === id || a.sighting.ticker === ticker
  );
  const analysis: Analysis = {
    id: existing?.id ?? `an-${ticker.toLowerCase()}-${Date.now()}`,
    sighting: nextSighting,
    score,
    updatedAt: new Date().toISOString(),
  };
  state.analyses = [
    analysis,
    ...state.analyses.filter((a) => a.id !== analysis.id),
  ];
  state.cart = buildCart(state.analyses, state.cart);
  await save(state);
  return { analysis, state };
}

export async function rebuildCart() {
  const state = await load();
  state.cart = buildCart(state.analyses, state.cart);
  await save(state);
  return state;
}

export async function dispatchCartToCeo() {
  const state = await load();
  state.cart = buildCart(state.analyses, state.cart);
  if (state.cart) {
    state.cart.sentToCeoAt = new Date().toISOString();
    state.cart.rows = state.cart.rows.map((row) => ({
      ...row,
      ceoMark: row.ceoMark === "valida" ? "valida" : "pending",
    }));
  }
  state.lastCeoDispatchAt = new Date().toISOString();
  await save(state);
  return state;
}

export async function markCartRow(ticker: string, mark: "valida" | "non_valida") {
  const state = await load();
  if (!state.cart) return state;
  state.cart.rows = state.cart.rows.map((row) =>
    row.ticker === ticker ? { ...row, ceoMark: mark } : row
  );
  await save(state);
  return state;
}

export async function setCeoNote(note: string) {
  const state = await load();
  state.ceoNote = note;
  await save(state);
  return state;
}

export async function sendValidatedToSender() {
  const state = await load();
  if (!state.cart) return state;
  const validated = state.cart.rows.filter((r) => r.ceoMark === "valida");
  if (validated.length === 0) {
    return state;
  }
  state.outbox.unshift({
    id: `out-cart-${Date.now()}`,
    kind: "validated_cart",
    title: "Carrello validato dal CEO",
    body: JSON.stringify({
      headline: state.cart.headline,
      rows: validated,
      reds: state.cart.reds,
      ceoNote: state.ceoNote,
    }),
    imageUrl: validated[0]?.chartImage ?? null,
    createdAt: new Date().toISOString(),
    sentAt: null,
    status: "queued",
    fromRole: "ceo",
  });
  if (state.ceoNote.trim()) {
    state.outbox.unshift({
      id: `out-note-${Date.now()}`,
      kind: "ceo_note",
      title: "Nota CEO",
      body: state.ceoNote.trim(),
      imageUrl: null,
      createdAt: new Date().toISOString(),
      sentAt: null,
      status: "queued",
      fromRole: "ceo",
    });
  }
  state.cart.sentToSenderAt = new Date().toISOString();
  await save(state);
  return state;
}

export async function saveTelegram(botToken: string, chatId?: string) {
  const state = await load();
  state.telegram.botToken = botToken;
  if (chatId) state.telegram.chatId = chatId;
  await save(state);
  return state;
}

export async function patchTelegram(partial: { botToken?: string; chatId?: string }) {
  const state = await load();
  state.telegram = { ...state.telegram, ...partial };
  await save(state);
  return state;
}

export async function markOutbox(
  id: string,
  patch: Partial<TelegramOutboxItem>
) {
  const state = await load();
  state.outbox = state.outbox.map((item) =>
    item.id === id ? { ...item, ...patch } : item
  );
  await save(state);
  return state;
}

export async function touchSenderPoll() {
  const state = await load();
  state.lastSenderPollAt = new Date().toISOString();
  await save(state);
  return state;
}

export function dueForCeo(state: SquadState, now = Date.now()) {
  if (!state.lastCeoDispatchAt) return true;
  return now - new Date(state.lastCeoDispatchAt).getTime() >= 4 * 60 * 60 * 1000;
}

export function dueForSenderPoll(state: SquadState, now = Date.now()) {
  if (!state.lastSenderPollAt) return true;
  return now - new Date(state.lastSenderPollAt).getTime() >= 2 * 60 * 60 * 1000;
}
