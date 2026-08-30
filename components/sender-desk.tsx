"use client";

import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { useSquad } from "@/components/squad-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const KIND_IT: Record<string, string> = {
  hot_post: "Post caldo · Reader",
  validated_cart: "Carrello validato · CEO",
  ceo_note: "Nota CEO",
};

const STATUS_IT: Record<string, string> = {
  queued: "In coda",
  sent: "Inviato",
  blocked: "Bloccato",
  mock: "Mock (Telegram non collegato)",
};

function cartText(body: string) {
  try {
    const parsed = JSON.parse(body) as { headline?: string; rows?: { ticker: string }[] };
    if (parsed.headline) {
      return `${parsed.headline} · ${parsed.rows?.length ?? 0} righe validate`;
    }
  } catch {
    /* testo libero */
  }
  return body;
}

export function SenderDesk() {
  const { data, flushSender, connectTelegram } = useSquad();
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const outbox = data?.outbox ?? [];

  async function onConnect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const result = await connectTelegram(token);
      setMessage(
        result.ok
          ? `Bot collegato. Chat ${result.chatId}.`
          : result.error || "Collegamento non riuscito."
      );
      if (result.ok) setToken("");
    } finally {
      setBusy(false);
    }
  }

  async function onFlush() {
    setBusy(true);
    setMessage(null);
    try {
      await flushSender();
      setMessage(
        data?.telegram.linked
          ? "Coda inviata su Telegram. Solo tu scrivi lì."
          : "Coda marcata mock: manca il bot. I messaggi restano visibili qui."
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Invio non riuscito.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="space-y-4">
        <div>
          <p className="font-mono text-[11px] tracking-[0.2em] text-zinc-500">SENDER</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">
            L’unico che scrive su Telegram
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            Post caldi dal Reader (testo + foto). Analisi solo dopo che il CEO ha detto
            Valida. Ogni 2 ore controlli se il CEO ha scritto. Analyst e CEO non hanno
            la penna Telegram.
          </p>
        </div>

        <Card className="bg-zinc-900/70">
          <CardHeader>
            <CardTitle>Collega Telegram</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={(e) => void onConnect(e)}>
              <p className="text-sm text-zinc-400">
                BotFather → /newbot → copia il token → apri il bot e premi Start →
                incolla qui. In alternativa: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.
              </p>
              <div className="space-y-1.5">
                <Label htmlFor="token">Token BotFather</Label>
                <Input
                  id="token"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="123456:ABC…"
                  autoComplete="off"
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={busy || !token.trim()}>
                  {busy ? "Collego…" : "Collega"}
                </Button>
                <Button type="button" variant="outline" disabled={busy} onClick={() => void onFlush()}>
                  Svuota coda ora
                </Button>
              </div>
              <p className="font-mono text-xs text-zinc-500">
                {data?.telegram.linked
                  ? `Collegato · chat ${data.telegram.chatId}`
                  : "Non collegato — gli invii restano mock."}
              </p>
              {message ? <p className="text-sm text-zinc-300">{message}</p> : null}
            </form>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Outbox</h3>
        {outbox.length === 0 ? (
          <EmptyState
            title="Coda vuota"
            body="I MUST READ e i carrelli validati dal CEO arrivano qui. Tu sei l’unico che li spedisce."
          />
        ) : (
          <ul className="space-y-3">
            {outbox.map((item) => (
              <li key={item.id} className="rounded-xl bg-zinc-900/70 p-4 ring-1 ring-white/10">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{KIND_IT[item.kind] ?? item.kind}</Badge>
                  <Badge variant="secondary">{STATUS_IT[item.status] ?? item.status}</Badge>
                </div>
                <p className="mt-2 font-medium">{item.title}</p>
                <p className="mt-1 text-sm text-zinc-400">
                  {item.kind === "validated_cart" ? cartText(item.body) : item.body}
                </p>
                <p className="mt-2 font-mono text-[11px] text-zinc-500">
                  da {item.fromRole} ·{" "}
                  {new Date(item.createdAt).toLocaleString("it-IT", {
                    day: "2-digit",
                    month: "2-digit",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                  {item.sentAt
                    ? ` · uscito ${new Date(item.sentAt).toLocaleString("it-IT", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}`
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
