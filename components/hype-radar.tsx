"use client";

import { useCallback, useEffect, useState, type ReactElement } from "react";
import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  Copy,
  Eye,
  ExternalLink,
  Heart,
  MessageCircle,
  RefreshCw,
  Repeat2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { HypeResponse, HypeToken } from "@/lib/types";

function formatUsd(value: number | null, digits = 2) {
  if (value == null) return "—";
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  if (value >= 1) return `$${value.toFixed(digits)}`;
  return `$${value.toPrecision(3)}`;
}

function formatPct(value: number | null) {
  if (value == null) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function shortMint(mint: string) {
  return `${mint.slice(0, 4)}…${mint.slice(-4)}`;
}

function xSearchUrl(token: HypeToken) {
  const query = encodeURIComponent(`$${token.symbol} solana OR ${token.name}`);
  return `https://x.com/search?q=${query}&src=typed_query&f=live`;
}

function Change({ value }: { value: number | null }) {
  if (value == null) {
    return <span className="text-muted-foreground">—</span>;
  }
  const up = value >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={up ? "text-lime-400" : "text-red-400"}>
      <Icon className="mr-0.5 inline size-3.5" />
      {formatPct(value)}
    </span>
  );
}

function TokenImage({ token, size }: { token: HypeToken; size: number }) {
  if (!token.imageUrl) {
    return (
      <div
        className="flex items-center justify-center rounded-full bg-lime-400/15 font-mono text-lime-300"
        style={{ width: size, height: size, fontSize: size / 3 }}
      >
        {token.symbol.slice(0, 2)}
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={token.imageUrl}
      alt={token.symbol}
      width={size}
      height={size}
      className="rounded-full bg-zinc-800 object-cover"
    />
  );
}

export function HypeRadar({ initial }: { initial: HypeResponse }) {
  const [data, setData] = useState<HypeResponse>(initial);
  const [error, setError] = useState<string | null>(
    initial.winner ? null : "Nessun token in tendenza al momento. Riprova tra un minuto."
  );
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/hype", { cache: "no-store" });
      if (!response.ok) throw new Error("fetch failed");
      const json = (await response.json()) as HypeResponse;
      if (!json.winner && !json.tokens.length) {
        setError("Nessun token in tendenza al momento. Riprova tra un minuto.");
      }
      setData(json);
    } catch {
      setError("Non riesco a leggere i feed live. Controlla la rete e riprova.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => void load(), 60_000);
    return () => window.clearInterval(id);
  }, [load]);

  async function copyMint(mint: string) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(mint);
      ok = true;
    } catch {
      try {
        const field = document.createElement("textarea");
        field.value = mint;
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
    setCopied(ok);
    window.setTimeout(() => setCopied(false), 1800);
  }

  const winner = data?.winner ?? null;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="font-mono text-[11px] tracking-[0.28em] text-lime-400 uppercase">
            Solana · X hype radar
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
            Quale token sta facendo più rumore
          </h1>
          <p className="max-w-2xl text-sm leading-6 text-zinc-400">
            Classifica in tempo reale dei memecoin Solana più caldi. Il primo posto pesa
            i post e i follower su X, poi trending e volume DEX.
          </p>
        </div>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : ""} />
          Aggiorna
        </Button>
      </header>

      {error ? (
        <Card className="border-red-500/30 bg-red-950/20">
          <CardContent className="flex items-start gap-3 pt-1">
            <AlertCircle className="mt-0.5 size-4 text-red-400" />
            <div className="space-y-3">
              <p className="text-sm text-red-100">{error}</p>
              <Button size="sm" variant="outline" onClick={() => void load()}>
                Riprova
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {loading && !winner ? <HeroSkeleton /> : winner ? <WinnerCard token={winner} copied={copied} onCopy={copyMint} /> : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium tracking-wide text-zinc-300 uppercase">
            Classifica hype
          </h2>
          {data?.generatedAt ? (
            <p className="font-mono text-[11px] text-zinc-500">
              {new Date(data.generatedAt).toLocaleTimeString("it-IT")}
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
            <div className="hidden grid-cols-[2.5rem_1fr_5rem_5rem_6.5rem_6.5rem_5.5rem] gap-3 bg-zinc-900/80 px-4 py-2 text-[11px] tracking-wide text-zinc-500 uppercase sm:grid">
              <span>#</span>
              <span>Token</span>
              <span className="text-right">Hype</span>
              <span className="text-right">X</span>
              <span className="text-right">Mcap</span>
              <span className="text-right">Vol 24h</span>
              <span className="text-right">24h</span>
            </div>
            {(data?.tokens ?? []).map((token, index) => (
              <a
                key={token.mint}
                href={token.dexScreenerUrl ?? `https://dexscreener.com/solana/${token.mint}`}
                target="_blank"
                rel="noreferrer"
                className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 border-t border-white/5 px-4 py-3 transition hover:bg-white/5 sm:grid-cols-[2.5rem_1fr_5rem_5rem_6.5rem_6.5rem_5.5rem]"
              >
                <span className="font-mono text-xs text-zinc-500">{index + 1}</span>
                <span className="flex min-w-0 items-center gap-3">
                  <TokenImage token={token} size={32} />
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-zinc-100">
                      ${token.symbol}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">{token.name}</span>
                  </span>
                </span>
                <span className="text-right font-mono text-sm text-lime-300">
                  {token.hypeScore}
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-400 sm:block">
                  {token.xScore}
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatUsd(token.marketCap)}
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatUsd(token.volume24h)}
                </span>
                <span className="hidden text-right text-sm sm:block">
                  <Change value={token.priceChange24h} />
                </span>
              </a>
            ))}
          </div>
        )}
      </section>

      <Card className="bg-zinc-900/60">
        <CardHeader>
          <CardTitle>Come viene calcolato</CardTitle>
          <CardDescription>
            {data?.note ??
              "L'hype su X viene stimato da fonti pubbliche perché la ricerca post non è abilitata su questo account."}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm text-zinc-400 sm:grid-cols-2 lg:grid-cols-4">
          <p>
            <span className="block font-medium text-zinc-200">40% X</span>
            Follower, view, like e reply sui post recenti del profilo ufficiale.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">28% trending</span>
            Posizione nel trending CoinGecko.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">18% momentum DEX</span>
            Rank dei pool Solana in tendenza su GeckoTerminal.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">14% on-chain</span>
            Volume, transazioni e boost DexScreener.
          </p>
        </CardContent>
      </Card>

      <p className="pb-8 text-xs leading-5 text-zinc-500">
        Non è consulenza finanziaria. I memecoin Solana sono estremamente volatili e spesso
        durano ore. Verifica sempre il mint prima di un swap. Fonti: CoinGecko, GeckoTerminal,
        DexScreener e X.
      </p>
    </div>
  );
}

function WinnerCard({
  token,
  copied,
  onCopy,
}: {
  token: HypeToken;
  copied: boolean;
  onCopy: (mint: string) => void;
}) {
  return (
    <Card className="overflow-hidden bg-linear-to-br from-lime-400/10 via-zinc-950 to-zinc-950 ring-lime-400/30">
      <CardHeader className="gap-4 sm:grid sm:grid-cols-[auto_1fr] sm:items-center">
        <TokenImage token={token} size={72} />
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="bg-lime-400 text-zinc-950 hover:bg-lime-300">Più hype ora</Badge>
            {token.coinGeckoRank ? (
              <Badge variant="outline">CoinGecko #{token.coinGeckoRank}</Badge>
            ) : null}
            {token.geckoTerminalRank ? (
              <Badge variant="outline">DEX #{token.geckoTerminalRank}</Badge>
            ) : null}
            {token.xHandle ? <Badge variant="outline">X @{token.xHandle}</Badge> : null}
          </div>
          <CardTitle className="font-mono text-3xl tracking-tight sm:text-4xl">
            ${token.symbol}
          </CardTitle>
          <CardDescription className="text-base text-zinc-300">{token.name}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Hype score" value={String(token.hypeScore)} />
          <Stat label="Prezzo" value={formatUsd(token.priceUsd, 4)} />
          <Stat label="Market cap" value={formatUsd(token.marketCap)} />
          <Stat label="Volume 24h" value={formatUsd(token.volume24h)} />
          <Stat label="Cambio 1h" value={<Change value={token.priceChange1h} />} />
          <Stat label="Cambio 24h" value={<Change value={token.priceChange24h} />} />
          <Stat label="Buy 24h" value={token.buys24h.toLocaleString("it-IT")} />
          <Stat label="Liquidità" value={formatUsd(token.liquidityUsd)} />
          <Stat label="Score X" value={String(token.xScore)} />
          <Stat
            label="Follower X"
            value={token.xFollowers != null ? token.xFollowers.toLocaleString("it-IT") : "—"}
          />
        </div>

        {token.xPosts.length ? (
          <div className="space-y-2">
            <p className="text-[11px] tracking-wide text-zinc-500 uppercase">Post recenti su X</p>
            <div className="space-y-2">
              {token.xPosts.map((post) => (
                <a
                  key={post.id}
                  href={post.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-lg bg-black/30 px-3 py-2 transition hover:bg-black/50"
                >
                  <p className="line-clamp-2 text-sm text-zinc-200">{post.text}</p>
                  <p className="mt-1.5 flex flex-wrap gap-3 font-mono text-[11px] text-zinc-500">
                    <span className="inline-flex items-center gap-1">
                      <Heart className="size-3" />
                      {post.likes}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Repeat2 className="size-3" />
                      {post.retweets}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <MessageCircle className="size-3" />
                      {post.replies}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Eye className="size-3" />
                      {post.views.toLocaleString("it-IT")}
                    </span>
                  </p>
                </a>
              ))}
            </div>
          </div>
        ) : null}

        {token.reasons.length ? (
          <ul className="space-y-1.5 text-sm text-zinc-300">
            {token.reasons.map((reason) => (
              <li key={reason} className="flex gap-2">
                <span className="text-lime-400">▸</span>
                {reason}
              </li>
            ))}
          </ul>
        ) : null}

        <Separator />

        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <button
            type="button"
            className={cn(buttonVariants({ variant: "outline" }), "justify-start font-mono")}
            onClick={() => onCopy(token.mint)}
          >
            <Copy />
            {copied ? "Mint copiato" : shortMint(token.mint)}
          </button>
          {token.twitterUrl ? (
            <a
              href={token.twitterUrl}
              target="_blank"
              rel="noreferrer"
              className={cn(buttonVariants())}
            >
              Profilo X
              <ExternalLink />
            </a>
          ) : null}
          <a
            href={xSearchUrl(token)}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline" }))}
          >
            Cerca su X
            <ExternalLink />
          </a>
          <a
            href={token.dexScreenerUrl ?? `https://dexscreener.com/solana/${token.mint}`}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline" }))}
          >
            DexScreener
            <ExternalLink />
          </a>
          <a
            href={`https://solscan.io/token/${token.mint}`}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline" }))}
          >
            Solscan
            <ExternalLink />
          </a>
        </div>
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

function HeroSkeleton() {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center gap-4">
        <Skeleton className="size-[72px] rounded-full bg-zinc-800" />
        <div className="space-y-2">
          <Skeleton className="h-5 w-28 bg-zinc-800" />
          <Skeleton className="h-8 w-48 bg-zinc-800" />
        </div>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-16 rounded-lg bg-zinc-800" />
        ))}
      </CardContent>
    </Card>
  );
}
