"use client";

import { useMemo, useState } from "react";

import { ChartFrame } from "@/components/chart-frame";
import { EmptyState } from "@/components/empty-state";
import { RatingBadge, VoteMark } from "@/components/rating-badge";
import { useSquad } from "@/components/squad-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { emptySighting, scoreSighting } from "@/lib/score";
import type {
  CandleSight,
  ChipSight,
  HoleSight,
  Panel2Sight,
  RibbonSight,
  Sighting,
} from "@/lib/types";
import { cn } from "@/lib/utils";

function Choice<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-xs",
            value === opt.value
              ? "border-lime-500/50 bg-lime-500/15 text-lime-100"
              : "border-white/10 bg-zinc-950 text-zinc-400 hover:text-zinc-100"
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function CheckRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-zinc-300">
      <Checkbox checked={checked} onCheckedChange={(v) => onChange(v === true)} />
      {label}
    </label>
  );
}

export function AnalystDesk() {
  const { data, saveAnalysis } = useSquad();
  const analyses = data?.analyses ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(analyses[0]?.id ?? null);
  const selected = analyses.find((a) => a.id === selectedId) ?? analyses[0] ?? null;
  const [draft, setDraft] = useState<Sighting | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [newTicker, setNewTicker] = useState("");

  const sighting = draft ?? selected?.sighting ?? emptySighting();
  const live = useMemo(() => scoreSighting(sighting), [sighting]);

  function patch(partial: Partial<Sighting>) {
    setDraft((prev) => ({ ...(prev ?? selected?.sighting ?? emptySighting()), ...partial }));
  }

  function pick(id: string) {
    setSelectedId(id);
    const next = analyses.find((a) => a.id === id);
    setDraft(next?.sighting ?? null);
    setMessage(null);
  }

  async function onSave() {
    if (!sighting.ticker.trim()) {
      setMessage("Serve il ticker.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const next: Sighting = {
        ...sighting,
        ticker: sighting.ticker.trim().toUpperCase(),
        chartImage: sighting.chartImage || `/api/chart/${sighting.ticker.trim().toUpperCase()}`,
      };
      await saveAnalysis(next, selected?.id);
      setMessage("Voto salvato. Il carrello si ricostruisce. Non si tocca wallet. Non si scrive su Telegram.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Salvataggio non riuscito.");
    } finally {
      setBusy(false);
    }
  }

  function startNew() {
    const ticker = newTicker.trim().toUpperCase();
    if (!ticker) return;
    setSelectedId(null);
    setDraft(
      emptySighting({
        ticker,
        name: ticker,
        hasDaily: true,
        chartImage: `/api/chart/${ticker}`,
      })
    );
    setNewTicker("");
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[220px_minmax(0,1fr)_minmax(280px,340px)]">
      <aside className="space-y-3">
        <h2 className="text-sm font-medium">Titoli letti</h2>
        {analyses.length === 0 ? (
          <EmptyState title="Nessuna analisi" body="Il Reader deve passare un ticker, o aprine uno nuovo." />
        ) : (
          <ul className="space-y-1">
            {analyses.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => pick(a.id)}
                  className={cn(
                    "flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm",
                    (selectedId ?? selected?.id) === a.id
                      ? "bg-lime-500/15 text-lime-100"
                      : "text-zinc-400 hover:bg-white/5"
                  )}
                >
                  <span className="font-mono">{a.sighting.ticker}</span>
                  <span className="font-mono text-xs">{a.score.vote}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <Input
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
            placeholder="NUOVO"
          />
          <Button type="button" variant="outline" onClick={startNew}>
            Apri
          </Button>
        </div>
      </aside>

      <Card className="bg-zinc-900/70">
        <CardHeader>
          <CardTitle>Checklist 5 pannelli — {sighting.ticker || "—"}</CardTitle>
          <p className="text-sm text-zinc-400">
            Si vota il setup, non il nome. Se un pezzo non è sul grafico, quel punto non si dà.
            Niente wallet, niente size, niente Telegram.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Ticker</Label>
              <Input
                value={sighting.ticker}
                onChange={(e) => patch({ ticker: e.target.value.toUpperCase() })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Nome</Label>
              <Input value={sighting.name} onChange={(e) => patch({ name: e.target.value })} />
            </div>
          </div>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">GRAFICI</h3>
            <CheckRow label="Daily" checked={sighting.hasDaily} onChange={(v) => patch({ hasDaily: v })} />
            <CheckRow label="Weekly" checked={sighting.hasWeekly} onChange={(v) => patch({ hasWeekly: v })} />
            <CheckRow label="Monthly" checked={sighting.hasMonthly} onChange={(v) => patch({ hasMonthly: v })} />
            <CheckRow
              label="Foto 5 pannelli (senza questa: tetto 4, mai Buy)"
              checked={sighting.hasFivePanelChart}
              onChange={(v) => patch({ hasFivePanelChart: v })}
            />
            <CheckRow
              label="Daily sembra buono (serve per monthly rotto)"
              checked={sighting.dailyLooksGood}
              onChange={(v) => patch({ dailyLooksGood: v })}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">RIBBON</h3>
            <Choice<RibbonSight>
              value={sighting.ribbon}
              onChange={(ribbon) => patch({ ribbon })}
              options={[
                { value: "absent", label: "Assente" },
                { value: "red_widening", label: "Rossa che si allarga" },
                { value: "red_thinning", label: "Rossa che si assottiglia" },
                { value: "thick_blue_above", label: "Blu spessa sopra" },
              ]}
            />
            <CheckRow
              label="Estensione: prezzo troppo lontano"
              checked={sighting.ribbonExtension}
              onChange={(v) => patch({ ribbonExtension: v })}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">CANDELA</h3>
            <Choice<CandleSight>
              value={sighting.candle}
              onChange={(candle) => patch({ candle })}
              options={[
                { value: "absent", label: "Assente" },
                { value: "fresh_red_wm", label: "Rossa W/M fresca" },
                { value: "dark_blue_continuation", label: "Blu scure di continuazione" },
                { value: "yellow_weekly", label: "Gialla weekly" },
                { value: "yellow_monthly", label: "Gialla monthly" },
              ]}
            />
            <div className="space-y-1.5">
              <Label>Giorni della rossa</Label>
              <Input
                type="number"
                min={0}
                value={sighting.redAgeDays ?? ""}
                onChange={(e) =>
                  patch({ redAgeDays: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </div>
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">CHIP</h3>
            <Choice<ChipSight>
              value={sighting.chip}
              onChange={(chip) => patch({ chip })}
              options={[
                { value: "absent", label: "Assente" },
                { value: "above_support", label: "Sopra, supporto" },
                { value: "below_resistance", label: "Sotto, tetto" },
                { value: "flipped_res_to_sup", label: "Girato res→sup" },
              ]}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">HOLE</h3>
            <Choice<HoleSight>
              value={sighting.hole}
              onChange={(hole) => patch({ hole })}
              options={[
                { value: "absent", label: "Assente" },
                { value: "close_above_high", label: "Close sopra bordo alto" },
                { value: "early_with_blue", label: "Hole + blu discendente" },
                { value: "close_in_middle", label: "Close in mezzo" },
                { value: "close_below_low", label: "Close sotto bordo basso" },
              ]}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">PANNELLO 2</h3>
            <Choice<Panel2Sight>
              value={sighting.panel2}
              onChange={(panel2) => patch({ panel2 })}
              options={[
                { value: "absent", label: "Assente" },
                { value: "flip_green_red_widening", label: "Flip verde→rosso, si allarga" },
                { value: "off_or_red_to_green", label: "Spento o rosso→verde" },
              ]}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">WHALE</h3>
            <div className="space-y-1.5">
              <Label>Whale %</Label>
              <Input
                type="number"
                min={0}
                max={100}
                value={sighting.whalePct ?? ""}
                onChange={(e) =>
                  patch({ whalePct: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            </div>
            <CheckRow label="Whale in salita" checked={sighting.whaleRising} onChange={(v) => patch({ whaleRising: v })} />
            <CheckRow
              label="Whale in calo"
              checked={sighting.whaleDeclining}
              onChange={(v) => patch({ whaleDeclining: v })}
            />
            <CheckRow
              label="Retail dominante"
              checked={sighting.retailDominant}
              onChange={(v) => patch({ retailDominant: v })}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">PANNELLO 4 / 5 — non si spara</h3>
            <CheckRow
              label="MACD sotto zero, croce bear"
              checked={sighting.macdBearCrossBelowZero}
              onChange={(v) => patch({ macdBearCrossBelowZero: v })}
            />
            <CheckRow
              label="RSI sotto 50 impilato al contrario"
              checked={sighting.rsiBelow50StackedWrong}
              onChange={(v) => patch({ rsiBelow50StackedWrong: v })}
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-xs font-medium tracking-wide text-zinc-500">POSIZIONE E DUE PREZZI</h3>
            <CheckRow
              label="A supporto (ribbon / CHIP / POC)"
              checked={sighting.atSupport}
              onChange={(v) => patch({ atSupport: v, chaseClose: v ? false : sighting.chaseClose })}
            />
            <CheckRow
              label="Close già sopra la zona (chase)"
              checked={sighting.chaseClose}
              onChange={(v) => patch({ chaseClose: v, atSupport: v ? false : sighting.atSupport })}
            />
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="space-y-1.5">
                <Label>Close</Label>
                <Input
                  value={sighting.closePrice}
                  onChange={(e) => patch({ closePrice: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Accel</Label>
                <Input
                  value={sighting.accelPrice}
                  onChange={(e) => patch({ accelPrice: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Inv</Label>
                <Input
                  value={sighting.invPrice}
                  onChange={(e) => patch({ invPrice: e.target.value })}
                />
              </div>
            </div>
            <CheckRow
              label="Prezzi copiati dal high/low della candela in corso"
              checked={sighting.pricesCopiedFromCandle}
              onChange={(v) => patch({ pricesCopiedFromCandle: v })}
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Zona bassa</Label>
                <Input value={sighting.zoneLow} onChange={(e) => patch({ zoneLow: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Zona alta</Label>
                <Input value={sighting.zoneHigh} onChange={(e) => patch({ zoneHigh: e.target.value })} />
              </div>
            </div>
          </section>

          <div className="space-y-1.5">
            <Label>Note (non è un voto)</Label>
            <Textarea value={sighting.notes} onChange={(e) => patch({ notes: e.target.value })} />
          </div>

          <Button type="button" disabled={busy} onClick={() => void onSave()}>
            {busy ? "Salvo…" : "Salva voto e aggiorna carrello"}
          </Button>
          {message ? <p className="text-sm text-zinc-300">{message}</p> : null}
        </CardContent>
      </Card>

      <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start">
        <Card className="bg-zinc-950 ring-1 ring-lime-500/20">
          <CardHeader>
            <p className="font-mono text-[11px] text-zinc-500">VOTO LIVE</p>
            <div className="flex items-end justify-between gap-3">
              <VoteMark vote={live.vote} rating={live.rating} />
              <RatingBadge rating={live.rating} />
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm leading-relaxed text-zinc-200">{live.explanation}</p>
            {live.zone ? (
              <p className="font-mono text-xs text-lime-200">
                zona {live.zone.low}–{live.zone.high}
              </p>
            ) : (
              <p className="text-xs text-zinc-500">Nessuna zona: manca il 5 pannelli o i bordi.</p>
            )}
            {live.caps.length > 0 ? (
              <ul className="text-xs text-amber-200/80">
                {live.caps.map((c) => (
                  <li key={c.reason}>
                    Tetto {c.limit}: {c.reason}
                  </li>
                ))}
              </ul>
            ) : null}
            {live.warnings.map((w) => (
              <p key={w} className="text-xs text-orange-200/80">
                {w}
              </p>
            ))}
            <ul className="space-y-1 border-t border-white/10 pt-3 text-xs text-zinc-400">
              {live.parts.map((p) => (
                <li key={p.key} className="flex justify-between gap-3">
                  <span>{p.label}</span>
                  <span className="font-mono">
                    {p.points > 0 ? `+${p.points}` : p.points}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <ChartFrame
          src={sighting.hasFivePanelChart ? sighting.chartImage || `/api/chart/${sighting.ticker}` : null}
          ticker={sighting.ticker || "—"}
        />
      </aside>
    </div>
  );
}
