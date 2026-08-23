import { getStockBoard } from "@/lib/stocks";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  try {
    const board = await getStockBoard();
    const lines = (board.topTickers ?? []).map(
      (stock, index) => `${index + 1}. $${stock.symbol}  ${stock.symbol}`,
    );
    const body =
      lines.length > 0
        ? `Radar NASDAQ — 4 ticker\n${new Date(board.generatedAt).toLocaleString("it-IT", { timeZone: "Europe/Rome" })}\n\n${lines.join("\n")}\n`
        : "Nessun ticker disponibile adesso.\n";
    return new Response(body, {
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store, max-age=0",
      },
    });
  } catch {
    return new Response("Impossibile leggere i ticker.\n", { status: 502 });
  }
}
