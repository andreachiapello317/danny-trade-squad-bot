"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FLOW_LINE, TRADER_LINE } from "@/lib/canon";
import { cn } from "@/lib/utils";

import { useSquad } from "./squad-provider";

const NAV = [
  { href: "/", label: "Carrello", hint: "10 slot" },
  { href: "/reader", label: "Reader", hint: "niente opinioni" },
  { href: "/analyst", label: "Analyst", hint: "voto 1–10" },
  { href: "/ceo", label: "CEO", hint: "solo valida" },
  { href: "/sender", label: "Sender", hint: "solo Telegram" },
  { href: "/trader", label: "Trader", hint: "fuori flusso" },
];

function when(iso: string | null) {
  if (!iso) return "mai";
  return new Date(iso).toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function DeskShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data, error, loading, refresh, tick } = useSquad();

  return (
    <div className="min-h-full bg-zinc-950 text-zinc-100">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top,_rgba(163,230,53,0.07),_transparent_42%),linear-gradient(to_bottom,_#09090b,_#09090b_40%,_#0c0a09)]" />
      <div className="relative mx-auto flex min-h-full max-w-[1400px] flex-col lg:flex-row">
        <aside className="border-b border-white/10 lg:w-56 lg:shrink-0 lg:border-r lg:border-b-0">
          <div className="flex items-center justify-between gap-3 px-4 py-4 lg:block">
            <Link href="/" className="block">
              <p className="font-mono text-[11px] tracking-[0.28em] text-lime-300/80">BOTSQUAD</p>
              <h1 className="text-lg font-semibold tracking-tight">Desk Danny</h1>
            </Link>
            <div className="hidden text-[11px] text-zinc-500 lg:mt-3 lg:block">
              Solo il Sender scrive su Telegram. Il carrello ogni 4 ore va al CEO.
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:px-3 lg:pb-6">
            {NAV.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex min-w-fit items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm",
                    active
                      ? "bg-lime-500/15 text-lime-200 ring-1 ring-lime-500/30"
                      : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100"
                  )}
                >
                  <span>{item.label}</span>
                  <span className="hidden font-mono text-[10px] text-zinc-500 lg:inline">
                    {item.hint}
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="flex flex-col gap-3 border-b border-white/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-3xl text-xs leading-relaxed text-zinc-400">
              {FLOW_LINE} {TRADER_LINE}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-zinc-500">
                CEO {when(data?.lastCeoDispatchAt ?? null)} · Sender{" "}
                {when(data?.lastSenderPollAt ?? null)}
              </span>
              <Button size="sm" variant="outline" onClick={() => void refresh()}>
                Aggiorna
              </Button>
              <Button size="sm" variant="secondary" onClick={() => void tick()}>
                Ciclo
              </Button>
            </div>
          </header>

          {error ? (
            <div className="mx-4 mt-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {error}{" "}
              <button type="button" className="underline" onClick={() => void refresh()}>
                Riprova
              </button>
            </div>
          ) : null}

          {loading && !data ? (
            <div className="p-4">
              <div className="grid gap-3 sm:grid-cols-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-36 animate-pulse rounded-xl bg-zinc-900 ring-1 ring-white/10"
                  />
                ))}
              </div>
              <p className="mt-3 text-sm text-zinc-500">Apro il desk…</p>
            </div>
          ) : (
            <main className="p-4 pb-16">{children}</main>
          )}
        </div>
      </div>
    </div>
  );
}
