import { connectTelegram, notifyStatus, notifyTopTickers } from "@/lib/notify";
import { getStockBoard } from "@/lib/stocks";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  return Response.json(await notifyStatus());
}

export async function POST(request: Request) {
  const contentType = request.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const body = (await request.json()) as { token?: string };
    if (body.token) {
      const connected = await connectTelegram(body.token);
      if (!connected.ok) return Response.json(connected, { status: 400 });
      return Response.json(connected);
    }
  }
  const board = await getStockBoard({ skipNotify: true });
  const result = await notifyTopTickers(board.topTickers ?? [], true);
  return Response.json({ ...result, topTickers: board.topTickers ?? [] });
}
