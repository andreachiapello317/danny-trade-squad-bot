import { getHypeBoard } from "@/lib/hype";
import { notifyConfigured, notifyTopContracts } from "@/lib/notify";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  return Response.json({
    configured: notifyConfigured(),
    ntfy: Boolean(process.env.NTFY_TOPIC?.trim()),
    telegram: Boolean(process.env.TELEGRAM_BOT_TOKEN?.trim() && process.env.TELEGRAM_CHAT_ID?.trim()),
    topic: process.env.NTFY_TOPIC?.trim() || null,
  });
}

export async function POST() {
  const board = await getHypeBoard();
  const result = await notifyTopContracts(board.topContracts ?? [], true);
  return Response.json({ ...result, topContracts: board.topContracts ?? [] });
}
