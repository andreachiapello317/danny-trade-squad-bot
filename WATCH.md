# Price watch

Le schede Trader su Telegram (`$AMD · daily` + Livelli ingresso/stop/target) sono una **watchlist**. Non sono ordini.

**Grok Trader → Sender → Telegram → `watch.py run` da solo.** Niente incolla. Confronta il prezzo Yahoo con i livelli già sulla scheda. Pezzo assente: salta quell’alert.

Non piazza ordini. Non è consulenza finanziaria.

## Una volta

```bash
pip install -r requirements.txt
```

Copia `.env.example` → `.env`.

Metti `TELEGRAM_BOT_TOKEN` in `.env` (stesso bot del Sender, o uno nuovo). Aggiungi il bot al gruppo `-1003929227957`. Su @BotFather: **Group Privacy OFF**. Nel gruppo: un `/start`.

Il bot non legge lo storico: solo i ticket da quando è nel gruppo e lo script è acceso. Non incollare i ticket.

## Ogni giorno

```bash
python watch.py run
```

O doppio click su `watch.bat` (Windows). Lascia il terminale aperto.

`run` legge i ticket nuovi dal gruppo, aggiorna `watchlist.json`, poi poll Yahoo (default 60s). **ALERT** (console + stesso gruppo, o `TELEGRAM_CHAT_ID` se lo cambi) quando:

- il prezzo tocca la banda di **ingresso**
- il prezzo è **≤ stop**
- il prezzo è **≥ target**

Ogni alert una volta sola, finché la condizione non si spegne. Ctrl+C esce.

Offset Telegram: `watch_state.json` (non rimangia i vecchi messaggi).

```bash
python watch.py list
python watch.py remove AMD
python watch.py run --interval 30
```

Watchlist: `watchlist.json` (ticker, tf, ingresso_low, ingresso_high, stop, target, motivo). Stesso ticker + stesso timeframe: si sovrascrive.

## Windows

Lascia una finestra aperta con `watch.py run` / `watch.bat`. Per accenderlo al login: collegamento a `watch.bat` in Esecuzione automatica (`shell:startup`).
