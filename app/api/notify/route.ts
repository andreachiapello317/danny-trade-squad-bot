import { getHypeBoard } from "@/lib/hype";
import { connectTelegram, notifyStatus, notifyTopContracts } from "@/lib/notify";

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
  const board = await getHypeBoard({ skipNotify: true });
  const result = await notifyTopContracts(board.topContracts ?? [], true);
  return Response.json({ ...result, topContracts: board.topContracts ?? [] });
}
