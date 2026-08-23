import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { HypeToken } from "@/lib/types";
import { TELEGRAM_COOLDOWN_MS } from "@/lib/timing";

const DATA_DIR = path.join(process.cwd(), ".data");
const STORE_PATH = path.join(DATA_DIR, "notify.json");

type Settings = {
  lastSignature?: string;
  lastSentAt?: number;
  telegramBotToken?: string;
  telegramChatId?: string;
};

export type ConnectTelegramResult =
  | { ok: true; telegramReady: true; telegramLinked: true; chatId: string }
  | { ok: false; error: string };

function env(name: string) {
  return process.env[name]?.trim() || "";
}

async function loadSettings(): Promise<Settings> {
  try {
    const raw = await readFile(STORE_PATH, "utf8");
    const parsed = JSON.parse(raw) as Settings & { ntfyTopic?: string };
    delete parsed.ntfyTopic;
    return parsed;
  } catch {
    return {};
  }
}

async function saveSettings(next: Settings) {
  await mkdir(DATA_DIR, { recursive: true });
  const clean: Settings = {
    lastSignature: next.lastSignature,
    lastSentAt: next.lastSentAt,
    telegramBotToken: next.telegramBotToken,
    telegramChatId: next.telegramChatId,
  };
  await writeFile(STORE_PATH, JSON.stringify(clean, null, 2));
}

function telegramCreds(settings: Settings) {
  const token = settings.telegramBotToken || env("TELEGRAM_BOT_TOKEN");
  const chatId = settings.telegramChatId || env("TELEGRAM_CHAT_ID");
  return { token, chatId };
}

function remainingCooldownMs(settings: Settings) {
  if (!settings.lastSentAt) return 0;
  return Math.max(0, settings.lastSentAt + TELEGRAM_COOLDOWN_MS - Date.now());
}

export function contractsSignature(tokens: HypeToken[]) {
  return tokens.map((token) => token.mint).join("|");
}

export function formatContractsMessage(tokens: HypeToken[]) {
  const when = new Date().toLocaleString("it-IT", { timeZone: "Europe/Rome" });
  const rows = tokens.map((token, index) => {
    const flag = token.check?.verdict === "danger" ? "  ATTENZIONE" : "";
    return `${index + 1}. $${token.symbol}${flag}\n${token.mint}`;
  });
  return [
    "Radar Solana — 4 contratti da copiare",
    when,
    "",
    ...rows,
    "",
    "Non e un consiglio di investimento. Controlla prima di usare i fondi.",
  ].join("\n");
}

async function telegramApi(token: string, method: string, body?: unknown) {
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = (await res.json()) as {
    ok: boolean;
    description?: string;
    result?: unknown;
  };
  if (!json.ok) {
    throw new Error(json.description || `Telegram ${method} failed`);
  }
  return json.result;
}

function cleanBotToken(raw: string) {
  return raw
    .trim()
    .replace(/^bot\s+/i, "")
    .replace(/^token\s*[:=]\s*/i, "");
}

export async function notifyStatus() {
  const settings = await loadSettings();
  const { token, chatId } = telegramCreds(settings);
  const cooldownMs = remainingCooldownMs(settings);
  return {
    telegramReady: Boolean(token && chatId),
    telegramLinked: Boolean(token && chatId),
    cooldownMinutes: Math.round(TELEGRAM_COOLDOWN_MS / 60_000),
    nextSendInSeconds: Math.ceil(cooldownMs / 1000),
  };
}

export async function connectTelegram(token: string): Promise<ConnectTelegramResult> {
  try {
    const clean = cleanBotToken(token);
    if (!/^\d+:[A-Za-z0-9_-]{20,}$/.test(clean)) {
      return {
        ok: false,
        error: "Token non valido. Copialo da BotFather: sembra 123456:ABC...",
      };
    }

    await telegramApi(clean, "getMe");
    const updates = (await telegramApi(clean, "getUpdates", {
      timeout: 0,
      allowed_updates: ["message"],
    })) as Array<{
      message?: { chat?: { id?: number } };
    }>;

    const chatId = [...updates]
      .reverse()
      .map((update) => update.message?.chat?.id)
      .find((id) => typeof id === "number");

    if (!chatId) {
      return {
        ok: false,
        error: "Apri Telegram, cerca il tuo bot e premi Start. Poi torna qui e riprova.",
      };
    }

    const settings = await loadSettings();
    settings.telegramBotToken = clean;
    settings.telegramChatId = String(chatId);
    await saveSettings(settings);

    return {
      ok: true,
      telegramReady: true,
      telegramLinked: true,
      chatId: String(chatId),
    };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Collegamento Telegram non riuscito",
    };
  }
}

let inflight: Promise<{ sent: boolean; reason: string; signature?: string; error?: string }> | null =
  null;

async function notifyTopContractsOnce(tokens: HypeToken[], force: boolean) {
  if (tokens.length === 0) {
    return { sent: false, reason: "empty" as const };
  }

  const settings = await loadSettings();
  const signature = contractsSignature(tokens);
  const { token, chatId } = telegramCreds(settings);

  if (!token || !chatId) {
    return { sent: false, reason: "unconfigured" as const };
  }

  if (!force) {
    if (settings.lastSignature === signature) {
      return { sent: false, reason: "unchanged" as const };
    }
    const wait = remainingCooldownMs(settings);
    if (wait > 0) {
      return { sent: false, reason: "cooldown" as const };
    }
  }

  const body = formatContractsMessage(tokens);
  await telegramApi(token, "sendMessage", {
    chat_id: chatId,
    text: body,
    disable_web_page_preview: true,
  });

  settings.lastSignature = signature;
  settings.lastSentAt = Date.now();
  settings.telegramBotToken = token;
  settings.telegramChatId = chatId;
  await saveSettings(settings);
  return { sent: true as const, signature, reason: "sent" as const };
}

export async function notifyTopContracts(tokens: HypeToken[], force = false) {
  if (inflight && !force) {
    return inflight;
  }
  const run = (async () => {
    try {
      return await notifyTopContractsOnce(tokens, force);
    } catch (error) {
      console.error("notifyTopContracts failed", error);
      return {
        sent: false,
        reason: "error" as const,
        error: error instanceof Error ? error.message : "notify failed",
      };
    } finally {
      inflight = null;
    }
  })();
  inflight = run;
  return run;
}

export async function markNotifyQuiet() {
  const settings = await loadSettings();
  settings.lastSentAt = Date.now();
  await saveSettings(settings);
}
