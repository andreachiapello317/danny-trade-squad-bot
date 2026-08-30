import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { getSquad } from "@/lib/store";
import { flushOutbox } from "@/lib/telegram";

export async function POST() {
  const state = await getSquad();
  const results = await flushOutbox(state);
  const next = await getSquad();
  return NextResponse.json({ results, state: toPublicSquad(next) });
}
