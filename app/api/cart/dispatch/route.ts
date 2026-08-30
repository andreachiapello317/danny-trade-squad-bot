import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { dispatchCartToCeo } from "@/lib/store";

export async function POST() {
  const state = await dispatchCartToCeo();
  return NextResponse.json(toPublicSquad(state));
}
