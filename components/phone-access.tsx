"use client";

import { useEffect, useState } from "react";
import { Smartphone } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type NotifyInfo = {
  configured: boolean;
  ntfy: boolean;
  telegram: boolean;
  topic: string | null;
};

export function PhoneAccess() {
  const [info, setInfo] = useState<NotifyInfo | null>(null);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  useEffect(() => {
    void fetch("/api/notify", { cache: "no-store" })
      .then((response) => response.json())
      .then((json) => setInfo(json as NotifyInfo))
      .catch(() => setInfo(null));
  }, []);

  async function sendNow() {
    setSending(true);
    setSent(null);
    try {
      const response = await fetch("/api/notify", { method: "POST" });
      const json = (await response.json()) as { sent?: boolean };
      setSent(json.sent ? "Inviato sul telefono" : "Invio non configurato o fallito");
    } catch {
      setSent("Invio non riuscito");
    } finally {
      setSending(false);
    }
  }

  return (
    <Card className="bg-zinc-900/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="size-4 text-lime-400" />
          Ti arrivano sul telefono
        </CardTitle>
        <CardDescription>
          Quando i 4 contratti cambiano, parte una notifica. Il modo più veloce è
          l’app ntfy. Telegram è opzionale.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm text-zinc-400">
        <ol className="list-decimal space-y-2 pl-5">
          <li>
            Installa <span className="text-zinc-200">ntfy</span> da App Store o Play Store.
          </li>
          <li>
            Apri ntfy → ＋ → iscriviti al topic{" "}
            <span className="break-all font-mono text-lime-300">
              {info?.topic ?? "radar-sol-4d99b770"}
            </span>
          </li>
          <li>Lascia le notifiche accese. I 4 mint arrivano quando la classifica cambia.</li>
        </ol>
        <p>
          Telegram: crea un bot con @BotFather, scrivigli /start, metti token e chat id in
          `.env.local`.
        </p>
        <Button variant="outline" onClick={() => void sendNow()} disabled={sending}>
          {sending ? "Invio…" : "Invia i 4 contratti adesso"}
        </Button>
        {sent ? <p className="font-mono text-[11px] text-lime-300">{sent}</p> : null}
      </CardContent>
    </Card>
  );
}
