"use client";

import { useState } from "react";

import { ChartFrame } from "@/components/chart-frame";
import { EmptyState } from "@/components/empty-state";
import { RatingBadge, VoteMark } from "@/components/rating-badge";
import { useSquad } from "@/components/squad-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { CANON_INTRO, CANON_SECTIONS, CANON_TITLE } from "@/lib/canon";
import type { CeoMark } from "@/lib/types";

function markTone(mark: CeoMark) {
  if (mark === "valida") return "Valida";
  if (mark === "non_valida") return "Non valida";
  return "In attesa";
}

export function CeoDesk() {
  const { data, markRow, setNote, dispatchCeo, sendToSender } = useSquad();
  const [note, setNoteLocal] = useState(data?.ceoNote ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const cart = data?.cart;
  const howTo = (data?.posts ?? []).filter((p) => p.kind === "how_to");
  const validated = cart?.rows.filter((r) => r.ceoMark === "valida").length ?? 0;

  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setMessage(null);
    try {
      await fn();
      setMessage(
        label === "send"
          ? "Carrello validato passato al Sender. Tu non scrivi su Telegram."
          : label === "dispatch"
            ? "Carrello inviato al CEO (ciclo 4 ore)."
            : "Segnato."
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Operazione non riuscita.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="font-mono text-[11px] tracking-[0.2em] text-zinc-500">CEO</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">
          Non modifichi i voti. Solo Valida o Non valida.
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Ogni 4 ore il carrello arriva qui, anche se è uguale. Poi, se le righe sono
          valide, lo inoltri al Sender insieme alle ultime 10 rosse. Niente wallet. Niente
          Telegram da questa sedia.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={busy !== null}
          onClick={() => void run("dispatch", dispatchCeo)}
        >
          {busy === "dispatch" ? "Invio…" : "Ricevi carrello ora"}
        </Button>
        <Button
          disabled={busy !== null || validated === 0}
          onClick={() => void run("send", sendToSender)}
        >
          {busy === "send" ? "Inoltro…" : `Inoltra al Sender (${validated} valide)`}
        </Button>
      </div>
      {message ? <p className="text-sm text-zinc-300">{message}</p> : null}

      {!cart || cart.rows.length === 0 ? (
        <EmptyState
          title="Nessun carrello da validare"
          body="L’Analyst deve costruire i 10 slot. Tu non li riscrivi."
        />
      ) : (
        <ol className="space-y-3">
          {cart.rows.map((row, i) => (
            <li key={row.ticker} className="rounded-xl bg-zinc-900/70 p-4 ring-1 ring-white/10">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-mono text-[11px] text-zinc-500">
                    {i + 1}. {row.name} · {markTone(row.ceoMark)}
                  </p>
                  <p className="font-mono text-xl font-semibold">{row.ticker}</p>
                </div>
                <div className="text-right">
                  <VoteMark vote={row.vote} rating={row.rating} />
                  <div className="mt-1">
                    <RatingBadge rating={row.rating} />
                  </div>
                </div>
              </div>
              <p className="mt-2 text-sm text-zinc-300">{row.explanation}</p>
              <p className="mt-1 text-xs text-zinc-500">
                I numeri sono dell’Analyst. Non si toccano.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant={row.ceoMark === "valida" ? "default" : "outline"}
                  onClick={() => void run(`v-${row.ticker}`, () => markRow(row.ticker, "valida"))}
                >
                  Valida
                </Button>
                <Button
                  size="sm"
                  variant={row.ceoMark === "non_valida" ? "destructive" : "outline"}
                  onClick={() =>
                    void run(`n-${row.ticker}`, () => markRow(row.ticker, "non_valida"))
                  }
                >
                  Non valida
                </Button>
              </div>
              <div className="mt-3 max-w-xl">
                <ChartFrame src={row.chartImage} ticker={row.ticker} compact />
              </div>
            </li>
          ))}
        </ol>
      )}

      <Card className="bg-zinc-900/70">
        <CardHeader>
          <CardTitle>Nota per il Sender (opzionale)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            value={note}
            onChange={(e) => setNoteLocal(e.target.value)}
            placeholder="Niente size, niente wallet. Solo contesto per il Sender."
          />
          <Button
            variant="outline"
            onClick={() => void run("note", () => setNote(note))}
          >
            Salva nota
          </Button>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h3 className="text-lg font-semibold">{CANON_TITLE}</h3>
        <p className="max-w-3xl text-sm text-zinc-400">{CANON_INTRO}</p>
        {howTo.length > 0 ? (
          <ul className="space-y-2">
            {howTo.map((post) => (
              <li key={post.id} className="rounded-lg bg-zinc-900 p-3 ring-1 ring-white/10">
                <p className="text-sm font-medium">{post.title}</p>
                <p className="mt-1 text-sm text-zinc-400">{post.body}</p>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="Nessun HOW TO dal Reader"
            body="I post HOW TO arrivano solo qui. Intanto vale il canone sotto."
          />
        )}
        <div className="grid gap-3 md:grid-cols-2">
          {CANON_SECTIONS.map((section) => (
            <article key={section.title} className="rounded-xl bg-zinc-900/60 p-4 ring-1 ring-white/10">
              <h4 className="text-sm font-medium text-lime-100">{section.title}</h4>
              <p className="mt-1 text-sm leading-relaxed text-zinc-400">{section.body}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
