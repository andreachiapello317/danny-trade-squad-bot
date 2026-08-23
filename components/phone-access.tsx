"use client";

import { useEffect, useState } from "react";
import { Smartphone } from "lucide-react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function PhoneAccess() {
  const [url, setUrl] = useState<string | null>(null);
  const [local, setLocal] = useState(true);

  useEffect(() => {
    const href = window.location.origin;
    setUrl(href);
    const host = window.location.hostname;
    setLocal(host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0");
  }, []);

  const qr =
    url && !local
      ? `https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(url)}`
      : null;

  return (
    <Card className="bg-zinc-900/60">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Smartphone className="size-4 text-lime-400" />
          Sul telefono
        </CardTitle>
        <CardDescription>
          La lista è già mobile. Per tenerla in Home, aprila da Safari o Chrome e
          installala come app.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm text-zinc-400 sm:grid-cols-[1fr_auto] sm:items-start">
        <ol className="list-decimal space-y-2 pl-5">
          {local ? (
            <li>
              Dal computer, avvia il radar sulla rete (`npm run dev -- --port 43177
              --hostname 0.0.0.0`). Poi sul telefono, stessa Wi‑Fi, apri
              `http://IP-DEL-PC:43177`.
            </li>
          ) : (
            <li>
              Apri questo indirizzo sul telefono:{" "}
              <span className="break-all font-mono text-zinc-200">{url}</span>
            </li>
          )}
          <li>
            <span className="text-zinc-200">iPhone:</span> Safari → Condividi → Aggiungi
            a Home.
          </li>
          <li>
            <span className="text-zinc-200">Android:</span> Chrome → menu ⋮ → Aggiungi
            alla schermata Home.
          </li>
        </ol>
        {qr ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={qr}
            alt="QR per aprire il radar sul telefono"
            width={160}
            height={160}
            className="rounded-lg bg-white p-2"
          />
        ) : null}
      </CardContent>
    </Card>
  );
}
