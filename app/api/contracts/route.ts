import { getHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export async function GET() {
  try {
    const board = await getHypeBoard();
    const lines = (board.topContracts ?? []).map(
      (token, index) => `${index + 1}. $${token.symbol}  ${token.mint}`
    );
    const body =
      lines.length > 0
        ? `Radar Solana — 4 contratti\n${new Date(board.generatedAt).toLocaleString("it-IT", { timeZone: "Europe/Rome" })}\n\n${lines.join("\n")}\n`
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
