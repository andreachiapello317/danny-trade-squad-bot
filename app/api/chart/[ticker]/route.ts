import { fivePanelSvg } from "@/lib/five-panel-svg";
import { emptySighting } from "@/lib/score";
import { getSquad } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ ticker: string }> }
) {
  const { ticker } = await ctx.params;
  const state = await getSquad();
  const analysis = state.analyses.find(
    (a) => a.sighting.ticker.toUpperCase() === ticker.toUpperCase()
  );
  const sighting = analysis?.sighting ?? emptySighting({ ticker: ticker.toUpperCase() });
  const svg = fivePanelSvg(sighting);
  return new Response(svg, {
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
