import { NextResponse } from "next/server";

import { toPublicSquad } from "@/lib/public-squad";
import { ingestPost } from "@/lib/store";
import type { PostKind } from "@/lib/types";

export async function POST(req: Request) {
  const body = (await req.json()) as {
    source?: "patreon" | "mail" | "incolla";
    kind?: PostKind;
    title?: string;
    body?: string;
    ticker?: string | null;
    imageUrl?: string | null;
  };
  if (!body.title?.trim() || !body.body?.trim()) {
    return NextResponse.json({ error: "Titolo e testo servono." }, { status: 400 });
  }
  const result = await ingestPost({
    source: body.source ?? "incolla",
    kind: body.kind ?? "other",
    title: body.title.trim(),
    body: body.body.trim(),
    ticker: body.ticker?.trim().toUpperCase() || null,
    imageUrl: body.imageUrl?.trim() || null,
  });
  return NextResponse.json({ post: result.post, state: toPublicSquad(result.state) });
}
