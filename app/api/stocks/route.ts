import { getStockBoard } from "@/lib/stocks";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  try {
    const board = await getStockBoard();
    return Response.json(board, {
      headers: { "cache-control": "no-store, max-age=0" },
    });
  } catch {
    return Response.json(
      {
        generatedAt: new Date().toISOString(),
        winner: null,
        stocks: [],
        topTickers: [],
        sources: { nasdaqMovers: false, nasdaqQuotes: false },
        note: "Impossibile leggere il NASDAQ in questo momento.",
        error: true,
      },
      { status: 502 },
    );
  }
}
