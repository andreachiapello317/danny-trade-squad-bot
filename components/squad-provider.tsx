"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { PublicSquad } from "@/lib/public-squad";
import type { PostKind, Sighting } from "@/lib/types";

type SquadContextValue = {
  data: PublicSquad | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  ingest: (input: {
    source: "patreon" | "mail" | "incolla";
    kind: PostKind;
    title: string;
    body: string;
    ticker?: string | null;
    imageUrl?: string | null;
  }) => Promise<void>;
  saveAnalysis: (sighting: Sighting, id?: string) => Promise<void>;
  markRow: (ticker: string, mark: "valida" | "non_valida") => Promise<void>;
  setNote: (note: string) => Promise<void>;
  dispatchCeo: () => Promise<void>;
  sendToSender: () => Promise<void>;
  flushSender: () => Promise<void>;
  connectTelegram: (token: string) => Promise<{ ok: boolean; error?: string; chatId?: string }>;
  tick: () => Promise<string[]>;
  reset: () => Promise<void>;
};

const SquadContext = createContext<SquadContextValue | null>(null);

async function readJson<T>(res: Response): Promise<T> {
  const data = (await res.json().catch(() => ({}))) as T & { error?: string };
  if (!res.ok) {
    throw new Error(data.error || "Richiesta non riuscita.");
  }
  return data;
}

function applyState(
  setData: (s: PublicSquad) => void,
  payload: PublicSquad | { state?: PublicSquad }
) {
  if ("telegram" in payload && "analyses" in payload) {
    setData(payload);
    return;
  }
  if ("state" in payload && payload.state) {
    setData(payload.state);
  }
}

export function SquadProvider({
  children,
  initial,
}: {
  children: React.ReactNode;
  initial?: PublicSquad | null;
}) {
  const [data, setData] = useState<PublicSquad | null>(initial ?? null);
  const [loading, setLoading] = useState(!initial);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/squad", { cache: "no-store" });
      const next = await readJson<PublicSquad>(res);
      setData(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Non riesco a leggere la squadra.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, 20_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const ingest = useCallback(async (input: Parameters<SquadContextValue["ingest"]>[0]) => {
    const res = await fetch("/api/posts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    applyState(setData, await readJson(res));
  }, []);

  const saveAnalysis = useCallback(async (sighting: Sighting, id?: string) => {
    const res = await fetch("/api/analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sighting, id }),
    });
    applyState(setData, await readJson(res));
  }, []);

  const markRow = useCallback(async (ticker: string, mark: "valida" | "non_valida") => {
    const res = await fetch("/api/ceo/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, mark }),
    });
    applyState(setData, await readJson(res));
  }, []);

  const setNote = useCallback(async (note: string) => {
    const res = await fetch("/api/ceo/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note }),
    });
    applyState(setData, await readJson(res));
  }, []);

  const dispatchCeo = useCallback(async () => {
    const res = await fetch("/api/cart/dispatch", { method: "POST" });
    applyState(setData, await readJson(res));
  }, []);

  const sendToSender = useCallback(async () => {
    const res = await fetch("/api/ceo/send", { method: "POST" });
    applyState(setData, await readJson(res));
  }, []);

  const flushSender = useCallback(async () => {
    const res = await fetch("/api/sender/flush", { method: "POST" });
    applyState(setData, await readJson(res));
  }, []);

  const connectTelegram = useCallback(async (token: string) => {
    const res = await fetch("/api/telegram/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const result = (await res.json()) as { ok?: boolean; error?: string; chatId?: string };
    if (result.ok) await refresh();
    return { ok: Boolean(result.ok), error: result.error, chatId: result.chatId };
  }, [refresh]);

  const tick = useCallback(async () => {
    const res = await fetch("/api/tick", { method: "POST" });
    const result = await readJson<{ actions: string[]; state: PublicSquad }>(res);
    applyState(setData, result);
    return result.actions;
  }, []);

  const reset = useCallback(async () => {
    const res = await fetch("/api/squad", { method: "DELETE" });
    applyState(setData, await readJson(res));
  }, []);

  const value = useMemo(
    () => ({
      data,
      loading,
      error,
      refresh,
      ingest,
      saveAnalysis,
      markRow,
      setNote,
      dispatchCeo,
      sendToSender,
      flushSender,
      connectTelegram,
      tick,
      reset,
    }),
    [
      data,
      loading,
      error,
      refresh,
      ingest,
      saveAnalysis,
      markRow,
      setNote,
      dispatchCeo,
      sendToSender,
      flushSender,
      connectTelegram,
      tick,
      reset,
    ]
  );

  return <SquadContext.Provider value={value}>{children}</SquadContext.Provider>;
}

export function useSquad() {
  const ctx = useContext(SquadContext);
  if (!ctx) throw new Error("useSquad va dentro SquadProvider");
  return ctx;
}
