"use client";

import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { useSquad } from "@/components/squad-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { KIND_LABEL, routePost } from "@/lib/route";
import type { PostKind } from "@/lib/types";

const KINDS: PostKind[] = ["must_read", "bullish", "trending", "my_buy", "how_to", "other"];
const SOURCES = ["patreon", "mail", "incolla"] as const;

function routeLabel(kind: PostKind) {
  const roles = routePost(kind);
  if (kind === "how_to") return "Solo CEO";
  if (roles.includes("sender")) return "Analyst + Sender (testo e foto)";
  return "Solo Analyst";
}

export function ReaderDesk() {
  const { data, ingest } = useSquad();
  const [source, setSource] = useState<(typeof SOURCES)[number]>("patreon");
  const [kind, setKind] = useState<PostKind>("must_read");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [ticker, setTicker] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await ingest({
        source,
        kind,
        title,
        body,
        ticker: ticker.trim() || null,
        imageUrl: imageUrl.trim() || null,
      });
      setTitle("");
      setBody("");
      setTicker("");
      setImageUrl("");
      setMessage("Post letto e instradato. Il Reader non aggiunge opinioni.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Ingestione non riuscita.");
    } finally {
      setBusy(false);
    }
  }

  const posts = data?.posts ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Card className="bg-zinc-900/70">
        <CardHeader>
          <CardTitle>Reader — solo lettura</CardTitle>
          <p className="text-sm text-zinc-400">
            Patreon e mail. Niente opinioni. MUST READ, Bullish Signals, Trending e My BUY
            vanno al Sender (testo + foto) e a tutti gli Analyst. HOW TO va al CEO. Tutto
            il resto agli Analyst.
          </p>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(e) => void onSubmit(e)}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="source">Fonte</Label>
                <select
                  id="source"
                  className="h-9 w-full rounded-lg border border-input bg-zinc-950 px-3 text-sm"
                  value={source}
                  onChange={(e) => setSource(e.target.value as (typeof SOURCES)[number])}
                >
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="kind">Tipo</Label>
                <select
                  id="kind"
                  className="h-9 w-full rounded-lg border border-input bg-zinc-950 px-3 text-sm"
                  value={kind}
                  onChange={(e) => setKind(e.target.value as PostKind)}
                >
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABEL[k]}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="font-mono text-xs text-lime-200/80">Destinazione: {routeLabel(kind)}</p>
            <div className="space-y-1.5">
              <Label htmlFor="title">Titolo</Label>
              <Input
                id="title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="MUST READ — AVGO weekly rossa"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="body">Testo del post</Label>
              <Textarea
                id="body"
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Copia il post. Non commentare."
                required
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="ticker">Ticker (se c’è)</Label>
                <Input
                  id="ticker"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value.toUpperCase())}
                  placeholder="AVGO"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="image">URL foto 5 pannelli</Label>
                <Input
                  id="image"
                  value={imageUrl}
                  onChange={(e) => setImageUrl(e.target.value)}
                  placeholder="/api/chart/AVGO"
                />
              </div>
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? "Invio…" : "Leggi e instrada"}
            </Button>
            {message ? <p className="text-sm text-zinc-300">{message}</p> : null}
          </form>
        </CardContent>
      </Card>

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Post in arrivo</h3>
        {posts.length === 0 ? (
          <EmptyState
            title="Nessun post"
            body="Incolla da Patreon o dalla mail. Il Reader non vota."
          />
        ) : (
          <ul className="space-y-3">
            {posts.map((post) => (
              <li key={post.id} className="rounded-xl bg-zinc-900/70 p-4 ring-1 ring-white/10">
                <p className="font-mono text-[11px] text-zinc-500">
                  {KIND_LABEL[post.kind]} · {post.source} ·{" "}
                  {new Date(post.receivedAt).toLocaleString("it-IT", {
                    hour: "2-digit",
                    minute: "2-digit",
                    day: "2-digit",
                    month: "2-digit",
                  })}
                </p>
                <p className="mt-1 font-medium">{post.title}</p>
                <p className="mt-1 text-sm text-zinc-400">{post.body}</p>
                <p className="mt-2 font-mono text-xs text-lime-200/70">
                  {post.ticker ? `${post.ticker} · ` : ""}
                  verso {post.routedTo.join(", ")}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
