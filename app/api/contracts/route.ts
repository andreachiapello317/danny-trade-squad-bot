import { getHypeBoard } from "@/lib/hype";
import { TOP_CONTRACTS_COUNT } from "@/lib/timing";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  try {
    const board = await getHypeBoard();
    const lines = (board.topContracts ?? []).slice(0, TOP_CONTRACTS_COUNT).map(
      (token, index) =>
        `${index + 1}. $${token.symbol}  Pump ${Math.round(token.hypeScore)}/100  ${token.mint}`
    );
    const body =
      lines.length > 0
        ? `Radar Solana — 4 token\n${new Date(board.generatedAt).toLocaleString("it-IT", { timeZone: "Europe/Rome" })}\n\n${lines.join("\n")}\n`
        : "Nessun contratto disponibile adesso.\n";
    return new Response(body, {
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store, max-age=0",
      },
    });
  } catch {
    return new Response("Impossibile leggere i contratti.\n", { status: 502 });
  }
}
