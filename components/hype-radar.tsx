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
  Repeat2,
} from "lucide-react";

import { PhoneAccess } from "@/components/phone-access";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { pumpWhy } from "@/lib/pump-why";
import { PAGE_REFRESH_MS, TOP_CONTRACTS_COUNT } from "@/lib/timing";
import type { HypeResponse, HypeToken } from "@/lib/types";
import { cn } from "@/lib/utils";

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

export function HypeRadar({ initial }: { initial?: HypeResponse | null }) {
  const hasInitial = Boolean(initial && (initial.winner || initial.tokens.length));
  const [data, setData] = useState<HypeResponse | null>(hasInitial ? initial! : null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!hasInitial);
  const [copied, setCopied] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/hype", { cache: "no-store" });
      if (!response.ok) throw new Error("fetch failed");
      const json = (await response.json()) as HypeResponse;
      if (!json.winner && !json.tokens.length) {
        setError("Nessun token in tendenza al momento. Aspetta la prossima ricerca, ogni 6 ore.");
      }
      setData(json);
    } catch {
      setError("Non riesco a leggere i feed. La ricerca riparte da sola ogni 6 ore.");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hasInitial) {
      void load();
    }
  }, [hasInitial, load]);

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
    setCopied(ok ? mint : null);
    window.setTimeout(() => setCopied(null), 1800);
  }

  const winner = data?.winner ?? null;
  const topContracts = (data?.topContracts ?? []).slice(0, TOP_CONTRACTS_COUNT);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-2">
          <p className="font-mono text-[11px] tracking-[0.28em] text-lime-400 uppercase">
            Solana · verified · trending
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
            I più in trending, solo verified
          </h1>
          <p className="max-w-2xl text-sm leading-6 text-zinc-400">
            Solo token Jupiter verified. In cima chi è davvero in trending su
            GeckoTerminal e CoinGecko, con volume. I nomi veri restano anche se
            hanno già corso, pump.fun compresi se i soldi ci sono. Fuori i
            copycat palesi. Market cap da 200k, launch dopo 30 minuti. La
            ricerca gira ogni 6 ore.
          </p>
        </div>
      </header>

      {topContracts.length ? (
        <ContractsCard tokens={topContracts} copied={copied} onCopy={copyMint} />
      ) : null}

      <PhoneAccess />

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

      {loading && !winner ? <HeroSkeleton /> : winner ? <WinnerCard token={winner} copied={copied === winner.mint} onCopy={copyMint} /> : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium tracking-wide text-zinc-300 uppercase">
            Trending verified
          </h2>
          {data?.generatedAt ? (
            <UpdatedAt iso={data.generatedAt} nextIso={data.nextSearchAt} />
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
            <div className="hidden grid-cols-[2.5rem_1fr_5rem_5.5rem_5.5rem_6.5rem_5.5rem] gap-3 bg-zinc-900/80 px-4 py-2 text-[11px] tracking-wide text-zinc-500 uppercase sm:grid">
              <span>#</span>
              <span>Token</span>
              <span className="text-right">Heat</span>
              <span className="text-right">24h</span>
              <span className="text-right">1h</span>
              <span className="text-right">Mcap</span>
              <span className="text-right">Vol 1h</span>
            </div>
            {(data?.tokens ?? []).map((token, index) => (
              <a
                key={token.mint}
                href={token.dexScreenerUrl ?? `https://dexscreener.com/solana/${token.mint}`}
                target="_blank"
                rel="noreferrer"
                className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 border-t border-white/5 px-4 py-3 transition hover:bg-white/5 sm:grid-cols-[2.5rem_1fr_5rem_5.5rem_5.5rem_6.5rem_5.5rem]"
              >
                <span className="font-mono text-xs text-zinc-500">{index + 1}</span>
                <span className="flex min-w-0 items-center gap-3">
                  <TokenImage token={token} size={32} />
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-zinc-100">
                      ${token.symbol}
                    </span>
                    <span className="block truncate text-xs text-zinc-500">
                      {token.name}
                      {token.verified ? " · verified" : ""}
                      {token.pairAgeHours != null && token.pairAgeHours < 12
                        ? token.pairAgeHours < 1
                          ? ` · ${Math.round(token.pairAgeHours * 60)} min`
                          : ` · ${token.pairAgeHours.toFixed(1)} h`
                        : ""}
                      {token.check ? ` · ${token.check.label}` : ""}
                    </span>
                  </span>
                </span>
                <span className="text-right font-mono text-sm text-lime-300">
                  {token.hypeScore}
                </span>
                <span className="hidden text-right text-sm sm:block">
                  <Change value={token.priceChange24h} />
                </span>
                <span className="hidden text-right text-sm sm:block">
                  <Change value={token.priceChange1h} />
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatUsd(token.marketCap)}
                </span>
                <span className="hidden text-right font-mono text-sm text-zinc-300 sm:block">
                  {formatUsd(token.volume1h)}
                </span>
              </a>
            ))}
          </div>
        )}
      </section>

      {(data?.established ?? []).length ? (
        <section className="space-y-3">
          <h2 className="text-sm font-medium tracking-wide text-zinc-500 uppercase">
            Già pompate oggi — tardi
          </h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {(data?.established ?? []).map((token) => (
              <a
                key={token.mint}
                href={token.dexScreenerUrl ?? `https://dexscreener.com/solana/${token.mint}`}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-3 rounded-xl px-3 py-2 ring-1 ring-white/10 transition hover:bg-white/5"
              >
                <TokenImage token={token} size={28} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-zinc-200">${token.symbol}</span>
                  <span className="block truncate text-xs text-zinc-500">
                    {formatUsd(token.marketCap)} · <Change value={token.priceChange24h} />
                  </span>
                </span>
              </a>
            ))}
          </div>
        </section>
      ) : null}

      <Card className="bg-zinc-900/60">
        <CardHeader>
          <CardTitle>Come viene calcolato</CardTitle>
          <CardDescription>
            {data?.note ??
              "Solo Jupiter verified, i più in trending. I nomi veri restano anche se hanno già corso — pump.fun con flusso vero compresi. Fuori i copycat e RugCheck danger."}
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm text-zinc-400 sm:grid-cols-2 lg:grid-cols-4">
          <p>
            <span className="block font-medium text-zinc-200">Soglia 200k</span>
            Sotto i 200k di market cap non entra. Sopra sì, anche se non è ancora un nome da miliardi.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">Launch 30 min</span>
            I pool con meno di 30 minuti restano fuori. Dopo mezz’ora possono entrare in classifica.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">X della gente</span>
            Conta chi sta twittando il ticker, non il profilo del progetto. Vale il 10%.
          </p>
          <p>
            <span className="block font-medium text-zinc-200">RugCheck</span>
            I primi della lista passano mint/freeze/LP e il confronto col profilo X.
          </p>
        </CardContent>
      </Card>

      <p className="pb-8 text-xs leading-5 text-zinc-500">
        Non è consulenza finanziaria. Anche un token listato può crollare. Verifica sempre il
        mint prima di uno swap. Fonti: Jupiter verified, CoinGecko, GeckoTerminal, DexScreener, RugCheck e X.
      </p>
    </div>
  );
}

function ContractsCard({
  tokens,
  copied,
  onCopy,
}: {
  tokens: HypeToken[];
  copied: string | null;
  onCopy: (mint: string) => void;
}) {
  const allMints = tokens.map((token) => `$${token.symbol} ${token.mint}`).join("\n");

  return (
    <Card className="ring-lime-400/25">
      <CardHeader>
        <CardTitle>4 token da copiare</CardTitle>
        <CardDescription>
          I 4 migliori: soldi forti, trending, whale. Pump e perché, senza garanzia.
          Tocca il mint per copiarlo. Non è un via libera.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {tokens.map((token, index) => (
          <div
            key={token.mint}
            className="flex flex-col gap-2 rounded-lg bg-black/30 px-3 py-2 sm:flex-row sm:items-start"
          >
            <div className="flex min-w-0 flex-1 items-start gap-3">
              <span className="w-4 pt-1 font-mono text-xs text-zinc-500">{index + 1}</span>
              <TokenImage token={token} size={28} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-zinc-100">
                  ${token.symbol}
                  <span className="ml-2 font-mono text-xs text-lime-300">
                    Pump {Math.round(token.hypeScore)}/100
                  </span>
                </p>
                <p className="truncate font-mono text-[11px] text-zinc-500">{token.mint}</p>
                <p className="mt-1 text-xs leading-5 text-pretty text-zinc-400">{pumpWhy(token)}</p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2 pl-7 sm:pl-0">
              <button
                type="button"
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "font-mono")}
                onClick={() => onCopy(token.mint)}
              >
                <Copy />
                {copied === token.mint ? "Copiato" : shortMint(token.mint)}
              </button>
              <a
                href={token.twitterUrl ?? xSearchUrl(token)}
                target="_blank"
                rel="noreferrer"
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              >
                X
                <ExternalLink />
              </a>
              <a
                href={token.dexScreenerUrl ?? `https://dexscreener.com/solana/${token.mint}`}
                target="_blank"
                rel="noreferrer"
                className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
              >
                Grafico
                <ExternalLink />
              </a>
            </div>
          </div>
        ))}
        <button
          type="button"
          className={cn(buttonVariants({ variant: "outline" }), "w-full font-mono")}
          onClick={() => onCopy(allMints)}
        >
          <Copy />
          {copied === allMints ? "Tutti copiati" : "Copia i 4 mint"}
        </button>
      </CardContent>
    </Card>
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
            <Badge className="bg-lime-400 text-zinc-950 hover:bg-lime-300">In heat</Badge>
            {token.verified ? <Badge variant="outline">Jupiter verified</Badge> : null}
            {token.listed ? <Badge variant="outline">CoinGecko</Badge> : null}
            {token.coinGeckoRank ? (
              <Badge variant="outline">CoinGecko #{token.coinGeckoRank}</Badge>
            ) : null}
            {token.geckoTerminalRank ? (
              <Badge variant="outline">DEX #{token.geckoTerminalRank}</Badge>
            ) : null}
            {token.xHandle ? <Badge variant="outline">X @{token.xHandle}</Badge> : null}
            {token.check ? <CheckBadge check={token.check} /> : null}
          </div>
          <CardTitle className="font-mono text-3xl tracking-tight sm:text-4xl">
            ${token.symbol}
          </CardTitle>
          <CardDescription className="text-base text-zinc-300">{token.name}</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Heat score" value={String(token.hypeScore)} />
          <Stat label="Cambio 1h" value={<Change value={token.priceChange1h} />} />
          <Stat label="Cambio 24h" value={<Change value={token.priceChange24h} />} />
          <Stat
            label="Buy 5m"
            value={
              token.buyPressure5m != null
                ? `${Math.round(token.buyPressure5m * 100)}% buy`
                : "—"
            }
          />
          <Stat label="Market cap" value={formatUsd(token.marketCap)} />
          <Stat label="Volume 1h" value={formatUsd(token.volume1h)} />
          <Stat label="Volume 24h" value={formatUsd(token.volume24h)} />
          <Stat label="Liquidità" value={formatUsd(token.liquidityUsd)} />
          <Stat
            label="Età pool"
            value={
              token.pairAgeHours == null
                ? "—"
                : token.pairAgeHours < 1
                  ? `${Math.round(token.pairAgeHours * 60)} min`
                  : token.pairAgeHours < 24
                    ? `${token.pairAgeHours < 10 ? token.pairAgeHours.toFixed(1) : Math.round(token.pairAgeHours)} h`
                    : `${Math.round(token.pairAgeHours / 24)} g`
            }
          />
          <Stat label="Cambio 5m" value={<Change value={token.priceChange5m} />} />
        </div>

        {token.check ? <CheckPanel check={token.check} /> : null}

        {token.xPosts.length ? (
          <div className="space-y-2">
            <p className="text-[11px] tracking-wide text-zinc-500 uppercase">Post della gente su X</p>
            <div className="space-y-2">
              {token.xPosts.map((post) => (
                <a
                  key={post.id}
                  href={post.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-lg bg-black/30 px-3 py-2 transition hover:bg-black/50"
                >
                  {post.author ? (
                    <p className="mb-1 font-mono text-[11px] text-lime-300">@{post.author}</p>
                  ) : null}
                  <p className="line-clamp-2 text-sm text-zinc-200">{post.text}</p>
                  {token.check?.xMintInPosts &&
                  token.mint &&
                  post.text.toLowerCase().includes(token.mint.slice(-8).toLowerCase()) ? (
                    <p className="mt-1 text-[11px] text-lime-400">Questo post cita il mint</p>
                  ) : null}
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

function CheckBadge({ check }: { check: NonNullable<HypeToken["check"]> }) {
  const tone =
    check.verdict === "danger"
      ? "border-red-400/40 text-red-300"
      : check.verdict === "caution"
        ? "border-amber-400/40 text-amber-200"
        : check.verdict === "pass"
          ? "border-lime-400/40 text-lime-300"
          : "border-zinc-500 text-zinc-400";
  return <Badge variant="outline" className={tone}>{check.label}</Badge>;
}

function CheckPanel({ check }: { check: NonNullable<HypeToken["check"]> }) {
  return (
    <div
      className={
        check.verdict === "danger"
          ? "space-y-2 rounded-lg border border-red-500/30 bg-red-950/30 px-3 py-3"
          : check.verdict === "caution"
            ? "space-y-2 rounded-lg border border-amber-500/30 bg-amber-950/20 px-3 py-3"
            : "space-y-2 rounded-lg border border-lime-500/20 bg-lime-950/20 px-3 py-3"
      }
    >
      <p className="text-[11px] tracking-wide text-zinc-400 uppercase">Verifica contratto + X</p>
      <div className="flex flex-wrap gap-2 text-[11px] font-mono text-zinc-300">
        <span>mint {check.mintRevoked == null ? "?" : check.mintRevoked ? "revocato" : "ATTIVO"}</span>
        <span>freeze {check.freezeRevoked == null ? "?" : check.freezeRevoked ? "revocato" : "ATTIVO"}</span>
        <span>
          LP {check.lpLockedPct == null ? "?" : `${Math.round(check.lpLockedPct)}% locked`}
        </span>
        <span>holder {check.holders ?? "—"}</span>
        <span>
          X mint {check.xMintInPosts == null ? "?" : check.xMintInPosts ? "citato" : "non citato"}
        </span>
      </div>
      <ul className="space-y-1 text-sm text-zinc-300">
        {check.notes.map((note) => (
          <li key={note}>▸ {note}</li>
        ))}
      </ul>
      <p className="text-[11px] text-zinc-500">
        Non è un via libera. Un check ok non significa che il token sia sicuro.
      </p>
    </div>
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

function romeClock(iso: string) {
  return new Date(iso).toLocaleTimeString("it-IT", {
    timeZone: "Europe/Rome",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function UpdatedAt({ iso, nextIso }: { iso: string; nextIso?: string }) {
  const next = nextIso ?? new Date(new Date(iso).getTime() + PAGE_REFRESH_MS).toISOString();
  return (
    <p className="text-right font-mono text-[11px] text-zinc-500">
      Ricerca delle {romeClock(iso)}
      <span className="block sm:inline sm:before:content-['·'] sm:before:mx-1">
        prossima alle {romeClock(next)}
      </span>
    </p>
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
