import { getHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";
export const maxDuration = 180;

export async function GET(request: Request) {
  try {
    const fresh =
      new URL(request.url).searchParams.get("fresh") === "1" ||
      new URL(request.url).searchParams.get("fresh") === "true";
    const board = await getHypeBoard({ fresh, skipNotify: fresh });
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
        topContracts: [],
        established: [],
        sources: {
          coinGecko: false,
          geckoTerminal: false,
          dexScreener: false,
          x: false,
          rugcheck: false,
          jupiter: false,
        },
        note: "Impossibile calcolare l'hype in questo momento.",
        error: true,
      },
      { status: 502 }
    );
  }
}
