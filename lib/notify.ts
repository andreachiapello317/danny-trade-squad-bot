import type { HypeToken } from "@/lib/types";

const last = { key: "", at: 0 };

function env(name: string) {
  const value = process.env[name]?.trim();
  return value || null;
}

export function formatContractsMessage(tokens: HypeToken[]) {
  const when = new Date().toLocaleString("it-IT", { timeZone: "Europe/Rome" });
  const rows = tokens.map((token, index) => `${index + 1}. $${token.symbol}\n${token.mint}`);
  return `Radar Solana — 4 contratti\n${when}\n\n${rows.join("\n\n")}\n`;
}

function mintKey(tokens: HypeToken[]) {
  return tokens.map((token) => token.mint).join(",");
}

export function notifyConfigured() {
  return Boolean(env("NTFY_TOPIC") || (env("TELEGRAM_BOT_TOKEN") && env("TELEGRAM_CHAT_ID")));
}

async function sendNtfy(body: string) {
  const topic = env("NTFY_TOPIC");
  if (!topic) return false;
  const server = (env("NTFY_SERVER") ?? "https://ntfy.sh").replace(/\/$/, "");
  const response = await fetch(`${server}/${encodeURIComponent(topic)}`, {
    method: "POST",
    headers: {
      title: "Radar Solana — 4 contratti",
      tags: "moneybag",
      "content-type": "text/plain; charset=utf-8",
    },
    body,
  });
  return response.ok;
}

async function sendTelegram(body: string) {
  const token = env("TELEGRAM_BOT_TOKEN");
  const chat = env("TELEGRAM_CHAT_ID");
  if (!token || !chat) return false;
  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      chat_id: chat,
      text: body,
      disable_web_page_preview: true,
    }),
  });
  return response.ok;
}

export async function notifyTopContracts(tokens: HypeToken[], force = false) {
  if (!tokens.length || !notifyConfigured()) {
    return { sent: false, reason: "not-configured" as const };
  }
  const key = mintKey(tokens);
  if (!force && key === last.key) {
    return { sent: false, reason: "unchanged" as const };
  }
  const body = formatContractsMessage(tokens);
  const [ntfy, telegram] = await Promise.all([sendNtfy(body), sendTelegram(body)]);
  if (ntfy || telegram) {
    last.key = key;
    last.at = Date.now();
    return { sent: true, ntfy, telegram, reason: "sent" as const };
  }
  return { sent: false, ntfy, telegram, reason: "failed" as const };
}
