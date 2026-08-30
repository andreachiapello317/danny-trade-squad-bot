"use client";

import { ChartFrame } from "@/components/chart-frame";
import { EmptyState } from "@/components/empty-state";
import { RatingBadge, VoteMark } from "@/components/rating-badge";
import { useSquad } from "@/components/squad-provider";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CART_SIZE } from "@/lib/types";

function markLabel(mark: string) {
  if (mark === "valida") return "Valida";
  if (mark === "non_valida") return "Non valida";
  return "In attesa CEO";
}

export function CartBoard() {
  const { data } = useSquad();
  const cart = data?.cart ?? null;
  const rows = cart?.rows ?? [];

  return (
    <div className="space-y-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.2em] text-zinc-500">CARRELLO DA 10</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">
          {cart?.headline ?? "Il carrello si costruisce dopo la lettura."}
        </h2>
        <p className="mt-2 max-w-3xl text-sm text-zinc-400">
          Sempre 10 ticker, voto decrescente. Se non ci sono 10 Buy, si riempie con Hold.
          Sell / Sell Now in fondo, o fuori se non servono a spiegare un taglio. Ogni 4 ore
          questo carrello va solo al CEO. Non al Trader. Non su Telegram.
        </p>
      </div>

      {!cart || rows.length === 0 ? (
        <EmptyState
          title="Nessun titolo con grafico a 5 pannelli"
          body="L’Analyst deve leggere i 5 pannelli e salvare il voto. Senza foto non si riempie uno slot."
        />
      ) : (
        <ol className="grid gap-3 md:grid-cols-2">
          {Array.from({ length: CART_SIZE }, (_, i) => {
            const row = rows[i];
            if (!row) {
              return (
                <li
                  key={`empty-${i}`}
                  className="rounded-xl border border-dashed border-white/10 bg-zinc-900/30 px-4 py-6 text-sm text-zinc-500"
                >
                  <span className="font-mono text-zinc-600">{i + 1}.</span> Slot vuoto
                </li>
              );
            }
            return (
              <li key={row.ticker}>
                <Card className="h-full bg-zinc-900/70">
                  <CardHeader className="flex flex-row items-start justify-between gap-3">
                    <div>
                      <p className="font-mono text-[11px] text-zinc-500">
                        {i + 1}. {row.name}
                      </p>
                      <CardTitle className="font-mono text-2xl tracking-tight">
                        {row.ticker}
                      </CardTitle>
                    </div>
                    <div className="text-right">
                      <VoteMark vote={row.vote} rating={row.rating} />
                      <div className="mt-2">
                        <RatingBadge rating={row.rating} />
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-sm leading-relaxed text-zinc-300">{row.explanation}</p>
                    {row.zone ? (
                      <p className="font-mono text-xs text-lime-200/80">
                        zona {row.zone.low}–{row.zone.high}
                      </p>
                    ) : null}
                    <Badge variant="outline">{markLabel(row.ceoMark)}</Badge>
                    <ChartFrame src={row.chartImage} ticker={row.ticker} compact />
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ol>
      )}

      <section className="space-y-3">
        <h3 className="text-sm font-medium text-zinc-200">Ultime 10 rosse</h3>
        {(cart?.reds.length ?? 0) === 0 ? (
          <EmptyState
            title="Nessuna rossa fresca in lista"
            body="Servono W/M rosse sotto i 5 giorni, con foto a 5 pannelli."
          />
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {cart?.reds.map((row) => (
              <li key={row.ticker} className="rounded-lg bg-zinc-900 px-3 py-2 ring-1 ring-white/10">
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold">{row.ticker}</span>
                  <VoteMark vote={row.vote} rating={row.rating} />
                </div>
                <RatingBadge rating={row.rating} className="mt-1" />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
