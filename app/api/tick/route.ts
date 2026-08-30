import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { dispatchCartToCeo, dueForCeo, dueForSenderPoll, getSquad } from "@/lib/store";
import { flushOutbox } from "@/lib/telegram";

export async function POST() {
  let state = await getSquad();
  const actions: string[] = [];
  if (dueForCeo(state)) {
    state = await dispatchCartToCeo();
    actions.push("cart_to_ceo");
  }
  if (dueForSenderPoll(state)) {
    await flushOutbox(state);
    actions.push("sender_poll");
    state = await getSquad();
  }
  return NextResponse.json({ actions, state: toPublicSquad(state) });
}
