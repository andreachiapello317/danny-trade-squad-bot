# Radar Solana — trending verified

Classifica i token Solana **Jupiter verified** più in trending (GeckoTerminal e CoinGecko), da **200k di market cap**. I launch entrano **dopo 30 minuti**.

X vale il 10% e conta i **post della gente** sul ticker. Chi ha già pompato **resta in lista**: seguiamo volume e whale, non tagliamo un pump a metà.

RugCheck guarda solo mint, freeze e rugged sui 4 in cima. Non gira a ogni refresh.

Non è consulenza finanziaria.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## Telegram sul telefono

La ricerca, la classifica e Telegram girano insieme ogni **2 ore**. Aprire o ricaricare la pagina **non** lancia una nuova caccia: restano i dati dell’ultimo ciclo. Arriva **un** messaggio solo se i 4 contratti sono cambiati. Nel messaggio ogni riga ha il mint da copiare, il link X e il grafico DexScreener.

1. Apri Telegram e cerca **BotFather**.
2. Scrivi `/newbot`, scegli un nome e un username che finisce con `bot`.
3. Copia il token, apri il bot appena creato e premi **Start**.
4. Incolla il token nella card “Telegram sul telefono” e premi **Collega**.

In alternativa puoi mettere `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` in `.env.local`.

`GET /api/contracts` è il testo dei 4 mint. `POST /api/notify` forza un invio (ignora il cooldown).

## Sul telefono (aprire la pagina)

La UI è già mobile. Per usarla dal telefono sulla stessa Wi‑Fi del computer:

```bash
npm install
npm run phone
```

Sul telefono apri `http://IP-DEL-COMPUTER:43177` (l’IP lo vedi con `ipconfig` su Windows o `ipconfig getifaddr en0` su Mac).

Poi:
- **iPhone:** Safari → Condividi → Aggiungi a Home
- **Android:** Chrome → menu ⋮ → Aggiungi alla schermata Home

## API

`GET /api/hype` restituisce `tokens` (trending + soldi forti) e `topContracts`.
