# Radar Solana — cosa sta partendo

Classifica i token Solana da **200k di market cap** in su. I launch entrano **dopo 30 minuti**, non prima.

X vale il 10% e conta i **post della gente** sul ticker, non l’account ufficiale. Il resto è accelerazione e launch (dopo 30 minuti). Chi ha già fatto +80% oggi finisce sotto, in “già pompate oggi”.

RugCheck guarda solo mint, freeze e rugged sui 4 in cima. Non gira a ogni refresh.

Non è consulenza finanziaria.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## Telegram sul telefono

La ricerca, la classifica e Telegram girano insieme ogni **15 minuti**. Arriva **un** messaggio solo se i 4 contratti sono cambiati.

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

`GET /api/hype` restituisce `tokens` (in accelerazione) e `established` (già pompate oggi).
