import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { sendValidatedToSender } from "@/lib/store";

export async function POST() {
  const state = await sendValidatedToSender();
  return NextResponse.json(toPublicSquad(state));
}
