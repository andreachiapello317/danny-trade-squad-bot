# Cosa fare (price watch)

Non gira sul tuo PC. Non incolli niente.

## Cosa è già automatico

1. Analyst trova il post bullish su Drive.
2. Trader scrive una scheda per ogni stock.
3. Sender la manda sul gruppo Telegram `-1003929227957`.

Lo script **legge quel gruppo da solo** e ti scrive lì quando il prezzo tocca **ingresso**, **stop** o **target**. Non piazza ordini.

## Cosa fai tu, una volta

Serve il **token del bot Telegram** (lo stesso che usa già il Sender, o uno nuovo da @BotFather).

1. Metti il bot nel gruppo delle schede (`-1003929227957`).
2. Su @BotFather: il tuo bot → **Group Privacy → OFF**.
3. Nel gruppo: scrivi `/start`.
4. Sul repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**
   - Nome: `TELEGRAM_BOT_TOKEN`
   - Valore: il token
5. **Actions** → workflow `watch` → **Enable** (se chiede). Poi **Run workflow** una volta per prova.

GitHub lo lancia **ogni 5 minuti dalle 15:00 alle 22:00 ora italiana**. Fuori da quella fascia non controlla. Il PC può restare spento.

Se il repo ancora non c’è: crea il repo da Cursor, pusha questo branch, poi i passi 4–5.

## Cosa vedi

Sul gruppo Telegram, messaggi tipo:

`ALERT AMD ingresso 131.20 (130–134)`

Ogni alert arriva **una volta** finché il prezzo non esce da quella zona.

## Se gli alert non partono

- Il bot è nel gruppo e Privacy è OFF?
- Hai fatto `/start` nel gruppo **dopo** aver spento la privacy?
- Lo script vede solo i ticket **da quando** il bot è nel gruppo (non lo storico).
- Il secret `TELEGRAM_BOT_TOKEN` è quello giusto?

## Account utente (opzionale)

I bot Telegram non vedono i messaggi scritti da altri bot. Per leggere le schede del Sender serve anche un **account utente** (Telethon).

Una volta, su https://my.telegram.org → API development tools: `api_id` e `api_hash`. Poi genera una `StringSession` (script Telethon sul tuo telefono/PC, login una volta). In `.env` o nei secret GitHub:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_USER_SESSION`

Senza queste tre chiavi lo script gira lo stesso, solo con la Bot API.

## Non fare

Non lasciare `watch.py run` acceso sul computer. Quello era il piano vecchio.
