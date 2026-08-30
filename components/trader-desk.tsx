"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FLOW_LINE, TRADER_LINE } from "@/lib/canon";

export function TraderDesk() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <p className="font-mono text-[11px] tracking-[0.2em] text-orange-300/80">TRADER</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight">Sei nel gruppo. Lo stampo non ti arriva più.</h2>
        <p className="mt-2 text-sm text-zinc-400">{TRADER_LINE}</p>
      </div>

      <Card className="bg-zinc-900/40 ring-1 ring-white/10">
        <CardHeader>
          <CardTitle>Ruolo da chiarire</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed text-zinc-400">
          <p>
            Prima lo stampo del carrello andava al Trader. Ora no. Il carrello ogni 4 ore
            va solo al CEO. Il CEO dice Valida o Non valida. Poi scrive il Sender su
            Telegram. Tu resti nel gruppo, ma sei fuori da quel tubo.
          </p>
          <p className="text-zinc-200">{FLOW_LINE}</p>
          <p>
            Da questa sedia non si tocca wallet, non si fa size, non si valida, non si
            spedisce. Se serve un ingresso, lo vedi quando il Sender pubblica il carrello
            già validato. Non prima.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
