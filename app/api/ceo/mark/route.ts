import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { markCartRow, setCeoNote } from "@/lib/store";

export async function POST(req: Request) {
  const body = (await req.json()) as {
    ticker?: string;
    mark?: "valida" | "non_valida";
    note?: string;
  };
  if (typeof body.note === "string") {
    const state = await setCeoNote(body.note);
    return NextResponse.json(toPublicSquad(state));
  }
  if (!body.ticker || (body.mark !== "valida" && body.mark !== "non_valida")) {
    return NextResponse.json({ error: "ticker e mark servono." }, { status: 400 });
  }
  const state = await markCartRow(body.ticker, body.mark);
  return NextResponse.json(toPublicSquad(state));
}
