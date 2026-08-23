"use client";

import { useCallback, useEffect, useState, type ReactElement } from "react";
import { AlertCircle, ArrowDownRight, ArrowUpRight, Copy, ExternalLink } from "lucide-react";

import { PhoneAccess } from "@/components/phone-access";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PAGE_REFRESH_MS } from "@/lib/timing";
import type { Stock, StockBoard } from "@/lib/types";

function formatUsd(value: number | null, digits = 2) {
  if (value == null) return "—";
  if (value >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toFixed(digits)}`;
}

function formatPct(value: number | null) {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function formatVolume(value: number | null) {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return String(Math.round(value));
}

function Change({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  const up = value >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={up ? "text-lime-400" : "text-red-400"}>
      <Icon className="mr-0.5 inline size-3.5" />
      {formatPct(value)}
    </span>
  );
}

function romeClock(iso: string) {
  return new Date(iso).toLocaleTimeString("it-IT", {
    timeZone: "Europe/Rome",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function StockRadar({ initial }: { initial?: StockBoard | null }) {
  const hasInitial = Boolean(initial && (initial.winner || initial.stocks.length));
  const [data, setData] = useState<StockBoard | null>(hasInitial ? initial! : null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!hasInitial);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/stocks", { cache: "no-store" });
      if (!response.ok) throw new Error("fetch failed");
      const json = (await response.json()) as StockBoard;
      if (!json.winner && !json.stocks.length) {
        setError("Nessuna azione in trending adesso. Aspetta la prossima ricerca, ogni 2 ore.");
      }
      setData(json);
    } catch {
      setError("Non riesco a leggere il NASDAQ. La ricerca riparte da sola ogni 2 ore.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasInitial) void load();
    const id = window.setInterval(() => void load(true), PAGE_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [hasInitial, load]);

  async function copyTicker(symbol: string) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(symbol);
      ok = true;
    } catch {
      try {
        const field = document.createElement("textarea");
        field.value = symbol;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.left = "-9999px";
        document.body.appendChild(field);
        field.select();
        ok = document.execCommand("copy");
        document.body.removeChild(field);
      } catch {
        ok = false;
      }
    }
    setCopied(ok ? symbol : null);
    window.setTimeout(() => setCopied(null), 1800);
  }

  const winner = data?.winner ?? null;
  const topTickers = (data?.topTickers ?? []).slice(0, 4);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <header className="space-y-2">
        <p className="font-mono text-[11px] tracking-[0.28em] text-lime-400 uppercase">
          NASDAQ · listate · trending
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
          Le più in trending sul NASDAQ
        </h1>
        <p className="max-w-2xl text-sm leading-6 text-zinc-400">
          Solo azioni comuni davvero listate. In cima chi muove di più: volume,
          rialzi e Nasdaq-100. La ricerca gira ogni 2 ore.
        </p>
      </header>

      {topTickers.length ? (
        <TickersCard stocks={topTickers} copied={copied} onCopy={copyTicker} />
      ) : null}

      <PhoneAccess />

      {error ? (
        <Card className="border-red-500/30 bg-red-950/20">
          <CardContent className="flex items-start gap-3 pt-1">
            <AlertCircle className="mt-0.5 size-4 text-red-400" />
            <p className="text-sm text-red-100">{error}</p>
          </CardContent>
        </Card>
      ) : null}

      {loading && !winner ? (
        <Skeleton className="h-40 w-full rounded-xl bg-zinc-800" />
      ) : winner ? (
        <WinnerCard stock={winner} copied={copied === winner.symbol} onCopy={copyTicker} />
      ) : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium tracking-wide text-zinc-300 uppercase">
            Trending NASDAQ
          </h2>
          {data?.generatedAt ? (
            <p className="text-right font-mono text-[11px] text-zinc-500">
              Ricerca delle {romeClock(data.generatedAt)}
              <span className="block sm:inline sm:before:content-['·'] sm:before:mx-1">
                prossima alle {romeClock(data.nextSearchAt ?? new Date(new Date(data.generatedAt).getTime() + PAGE_REFRESH_MS).toISOString())}
              </span>
            </p>
          ) : null}
        </div>

        {loading && !data ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full rounded-xl bg-zinc-800" />
            ))}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl ring-1 ring-white/10">
            <div className="hidden grid-cols-[2.5rem_1fr_5rem_5.5rem_6.5rem_6.5rem] gap-3 bg-zinc-900/80 px-4 py-2 text-[11px] tracking-wide text-zinc-500 uppercase sm:grid">
              <span>#</span>
              <span>Azione</span>
              <span className="text-right">Score</span>
              <span className="text-right">Oggi</span>
              <span className="text-right">Prezzo</span>
              <span className="text-right">Volume</span>
            </div>
            {(data?.stocks ?? []).map((stock, index) => (
              <a
                key={stock.symbol}
                href={stock.chartUrl}
                target="_blank"
                rel="noreferrer"
                className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 border-t border-white/5 px-4 py-3 transition hover:bg-white/5 sm:grid-cols-[2.5rem_1fr_5rem_5.5rem_6.5rem_6.5rem]"
              >
                <span className="font-mono text-xs text-zinc-500">{index + 1}</span>
                <span className="min-w-0">
                  <span className="block truncate font-medium text-zinc-100">${stock.symbol}</span>
                  <span className="block truncate text-xs text-zinc-500">
                    {stock.name}
                    {stock.nasdaq100 ? " · Nasdaq-100" : " · NASDAQ"}
                  </span>
                </span>
                <span className="text-right font-mono text-sm text-lime-300">{stock.score}</span>
                <span className="hidden text-right text-sm sm:block">
                  <Change value={stock.changePct} />
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatUsd(stock.priceUsd)}
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatVolume(stock.volume)}
                </span>
              </a>
            ))}
          </div>
        )}
      </section>

      <p className="pb-8 text-xs leading-5 text-zinc-500">
        Non è consulenza finanziaria. Fonte: NASDAQ market movers. Verifica sempre il ticker
        prima di un ordine.
      </p>
    </div>
  );
}

function TickersCard({
  stocks,
  copied,
  onCopy,
}: {
  stocks: Stock[];
  copied: string | null;
  onCopy: (symbol: string) => void;
}) {
  return (
    <Card className="ring-lime-400/25">
      <CardHeader>
        <CardTitle>4 ticker da copiare</CardTitle>
        <CardDescription>
          Le 4 NASDAQ più in trending. Tocca il ticker per copiarlo. Non è un via libera.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {stocks.map((stock, index) => (
          <div key={stock.symbol} className="flex flex-col gap-2 rounded-xl px-3 py-3 ring-1 ring-white/10 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-zinc-100">
                {index + 1}. ${stock.symbol}{" "}
                <Change value={stock.changePct} />
              </p>
              <p className="truncate font-mono text-xs text-zinc-400">{stock.symbol}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => onCopy(stock.symbol)}>
                <Copy className="size-3.5" />
                {copied === stock.symbol ? "Copiato" : "Copia"}
              </Button>
              <a className={buttonLink()} href={stock.xUrl} target="_blank" rel="noreferrer">
                X
              </a>
              <a className={buttonLink()} href={stock.chartUrl} target="_blank" rel="noreferrer">
                Grafico
                <ExternalLink className="size-3.5" />
              </a>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function buttonLink() {
  return "inline-flex h-7 items-center gap-1 rounded-lg border border-border px-2.5 text-[0.8rem] hover:bg-muted";
}

function WinnerCard({
  stock,
  copied,
  onCopy,
}: {
  stock: Stock;
  copied: boolean;
  onCopy: (symbol: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs tracking-wide text-zinc-500 uppercase">In cima adesso</p>
          <CardTitle className="mt-1 text-3xl">${stock.symbol}</CardTitle>
          <CardDescription>{stock.name}</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {stock.nasdaq100 ? <Badge variant="outline">Nasdaq-100</Badge> : <Badge variant="outline">NASDAQ</Badge>}
          <Badge variant="outline">{formatUsd(stock.priceUsd)}</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Oggi" value={<Change value={stock.changePct} />} />
        <Stat label="Volume" value={formatVolume(stock.volume)} />
        <Stat label="Market cap" value={formatUsd(stock.marketCap, 0)} />
        <Stat label="Score" value={stock.score} />
      </CardContent>
      <CardContent className="flex flex-wrap gap-2 pt-0">
        <Button size="sm" onClick={() => onCopy(stock.symbol)}>
          <Copy className="size-3.5" />
          {copied ? "Ticker copiato" : "Copia ticker"}
        </Button>
        <a className={buttonLink()} href={stock.xUrl} target="_blank" rel="noreferrer">
          X
        </a>
        <a className={buttonLink()} href={stock.chartUrl} target="_blank" rel="noreferrer">
          Grafico
        </a>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string | number | ReactElement }) {
  return (
    <div className="rounded-lg bg-black/30 px-3 py-2">
      <p className="text-[11px] tracking-wide text-zinc-500 uppercase">{label}</p>
      <p className="mt-1 font-mono text-sm text-zinc-100">{value}</p>
    </div>
  );
}
