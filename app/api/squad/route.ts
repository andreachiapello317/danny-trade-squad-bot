import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { getSquad, resetSquad } from "@/lib/store";

export const dynamic = "force-dynamic";

export async function GET() {
  const state = await getSquad();
  return NextResponse.json(toPublicSquad(state));
}

export async function DELETE() {
  const state = await resetSquad();
  return NextResponse.json(toPublicSquad(state));
}
