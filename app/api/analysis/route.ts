import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { emptySighting, scoreSighting } from "@/lib/score";
import { saveAnalysis } from "@/lib/store";
import type { Sighting } from "@/lib/types";

export async function POST(req: Request) {
  const body = (await req.json()) as {
    sighting?: Partial<Sighting>;
    id?: string;
    previewOnly?: boolean;
  };
  const sighting = emptySighting(body.sighting ?? {});
  if (!sighting.ticker.trim() && !body.previewOnly) {
    return NextResponse.json({ error: "Serve il ticker." }, { status: 400 });
  }
  const preview = scoreSighting(sighting);
  if (body.previewOnly) {
    return NextResponse.json({ preview });
  }
  const saved = await saveAnalysis(sighting, body.id);
  return NextResponse.json({ preview, ...saved, state: toPublicSquad(saved.state) });
}
