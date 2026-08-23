"use client";

import { useEffect, useState } from "react";
import { Check, MessageCircle, Smartphone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Status = {
  telegramReady?: boolean;
  telegramLinked?: boolean;
};

export function PhoneAccess() {
  const [token, setToken] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/notify", { cache: "no-store" })
      .then((res) => res.json())
      .then((data: Status) => setStatus(data))
      .catch(() => undefined);
  }, []);

  async function connect() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch("/api/notify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = (await res.json()) as { error?: string; sent?: boolean };
      if (!res.ok) {
        throw new Error(data.error || "Collegamento non riuscito");
      }
      setStatus({ telegramReady: true, telegramLinked: true });
      setToken("");
      setMessage("Collegato. La prossima ricerca è tra 6 ore. Un messaggio solo se i 10 token cambiano.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Collegamento non riuscito");
    } finally {
      setBusy(false);
    }
  }

  async function sendNow() {
    setSending(true);
    setError(null);
    setMessage(null);
    try {
      const res = await fetch("/api/notify", { method: "POST" });
      const data = (await res.json()) as { sent?: boolean; error?: string };
      if (!res.ok || data.sent === false) {
        throw new Error(data.error || "Invio non riuscito");
      }
      setMessage("Inviato. Controlla la chat del bot su Telegram.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invio non riuscito");
    } finally {
      setSending(false);
    }
  }

  const linked = Boolean(status?.telegramReady || status?.telegramLinked);

  return (
    <Card className="border-sky-500/30 bg-sky-500/5">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Smartphone className="size-4 text-sky-300" />
          Telegram sul telefono
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {linked ? (
          <>
            <p className="flex items-start gap-2 text-sky-100">
              <Check className="mt-0.5 size-4 shrink-0" />
              Telegram è collegato. Ricerca e messaggio ogni 6 ore. Mandiamo solo
              se i 10 token sono cambiati. In ogni riga: contratto da copiare, X e grafico.
            </p>
            <Button variant="outline" disabled={sending} onClick={() => void sendNow()}>
              {sending ? "Invio…" : "Forza un invio ora"}
            </Button>
          </>
        ) : (
          <>
            <p className="text-muted-foreground">
              Serve un bot Telegram tuo, gratis. Lo crei in un minuto e poi i 10
              token arrivano sul telefono.
            </p>
            <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
              <li>
                Sul telefono apri Telegram e cerca <strong>BotFather</strong>
              </li>
              <li>
                Scrivi <code>/newbot</code>, dai un nome, poi un username che
                finisce con <code>bot</code>
              </li>
              <li>BotFather ti dà un token: copialo</li>
              <li>
                Cerca il bot che hai appena creato e premi <strong>Start</strong>
              </li>
              <li>Incolla il token qui sotto e premi Collega</li>
            </ol>
            <Input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="123456789:AAH..."
              autoComplete="off"
              spellCheck={false}
            />
            <Button className="w-full sm:w-auto" disabled={busy || !token.trim()} onClick={() => void connect()}>
              <MessageCircle className="size-4" />
              {busy ? "Collego…" : "Collega Telegram"}
            </Button>
          </>
        )}
        {message ? <p className="text-sky-200">{message}</p> : null}
        {error ? <p className="text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  );
}
