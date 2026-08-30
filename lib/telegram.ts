import { formatCartForTelegram } from "@/lib/cart";
import { markOutbox, patchTelegram, touchSenderPoll } from "@/lib/store";
import type { Cart, SquadState, TelegramOutboxItem } from "@/lib/types";

function env(name: string) {
  return process.env[name]?.trim() || "";
}

export function telegramCreds(state: SquadState) {
  const token = state.telegram.botToken || env("TELEGRAM_BOT_TOKEN");
  const chatId = state.telegram.chatId || env("TELEGRAM_CHAT_ID");
  return { token, chatId };
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

export async function connectTelegram(token: string) {
  const clean = cleanBotToken(token);
  if (!/^\d+:[A-Za-z0-9_-]{20,}$/.test(clean)) {
    return {
      ok: false as const,
      error: "Token non valido. Copialo da BotFather: sembra 123456:ABC...",
    };
  }
  try {
    await telegramApi(clean, "getMe");
    const updates = (await telegramApi(clean, "getUpdates", {
      timeout: 0,
      allowed_updates: ["message"],
    })) as Array<{ message?: { chat?: { id?: number } } }>;
    const chatId = [...updates]
      .reverse()
      .map((u) => u.message?.chat?.id)
      .find((id) => typeof id === "number");
    if (!chatId) {
      return {
        ok: false as const,
        error: "Apri Telegram, cerca il tuo bot e premi Start. Poi torna qui e riprova.",
      };
    }
    await patchTelegram({ botToken: clean, chatId: String(chatId) });
    return { ok: true as const, chatId: String(chatId) };
  } catch (error) {
    return {
      ok: false as const,
      error: error instanceof Error ? error.message : "Collegamento Telegram non riuscito",
    };
  }
}

function cartBody(item: TelegramOutboxItem): { text: string; imageUrl: string | null } {
  if (item.kind !== "validated_cart") {
    return { text: `${item.title}\n\n${item.body}`, imageUrl: item.imageUrl };
  }
  try {
    const parsed = JSON.parse(item.body) as {
      headline: string;
      rows: Cart["rows"];
      reds: Cart["reds"];
    };
    const fake: Cart = {
      id: item.id,
      builtAt: item.createdAt,
      rows: parsed.rows,
      reds: parsed.reds,
      marketOfferingEntry: parsed.rows[0]?.vote >= 7 &&
        (parsed.rows[0]?.rating === "Buy" || parsed.rows[0]?.rating === "Strong Buy"),
      headline: parsed.headline,
      sentToCeoAt: null,
      sentToSenderAt: null,
    };
    return { text: formatCartForTelegram(fake), imageUrl: item.imageUrl };
  } catch {
    return { text: item.body, imageUrl: item.imageUrl };
  }
}

export async function flushOutbox(state: SquadState) {
  const { token, chatId } = telegramCreds(state);
  const queued = state.outbox.filter((i) => i.status === "queued");
  const results: { id: string; status: TelegramOutboxItem["status"]; error?: string }[] = [];

  for (const item of queued) {
    const { text, imageUrl } = cartBody(item);
    if (!token || !chatId) {
      await markOutbox(item.id, { status: "mock", sentAt: new Date().toISOString() });
      results.push({ id: item.id, status: "mock" });
      continue;
    }
    try {
      if (imageUrl && imageUrl.startsWith("http")) {
        await telegramApi(token, "sendPhoto", {
          chat_id: chatId,
          photo: imageUrl,
          caption: text.slice(0, 1024),
        });
      } else {
        await telegramApi(token, "sendMessage", {
          chat_id: chatId,
          text,
        });
      }
      await markOutbox(item.id, { status: "sent", sentAt: new Date().toISOString() });
      results.push({ id: item.id, status: "sent" });
    } catch (error) {
      await markOutbox(item.id, { status: "blocked" });
      results.push({
        id: item.id,
        status: "blocked",
        error: error instanceof Error ? error.message : "send failed",
      });
    }
  }

  await touchSenderPoll();
  return results;
}

