import { NextResponse } from "next/server";

import { connectTelegram } from "@/lib/telegram";

export async function POST(req: Request) {
  const body = (await req.json()) as { token?: string };
  if (!body.token?.trim()) {
    return NextResponse.json({ error: "Incolla il token BotFather." }, { status: 400 });
  }
  const result = await connectTelegram(body.token);
  return NextResponse.json(result, { status: result.ok ? 200 : 400 });
}
