import { getHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  try {
    const board = await getHypeBoard();
    return Response.json(board, {
      headers: {
        "cache-control": "no-store, max-age=0",
      },
    });
  } catch {
    return Response.json(
      {
        generatedAt: new Date().toISOString(),
        winner: null,
        tokens: [],
        sources: { coinGecko: false, geckoTerminal: false, dexScreener: false, x: false },
        note: "Impossibile calcolare l'hype in questo momento.",
        error: true,
      },
      { status: 502 }
    );
  }
}
