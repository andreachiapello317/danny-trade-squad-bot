# Price watch

Le schede Trader su Telegram (`$AMD · daily` + motivo Danny + P1/P2/P3 + Hole + Livelli) sono una **watchlist con livelli**. Non sono ordini. Non è un segnale di “compra adesso”.

Questo script sta in mezzo: **Grok Trader → Telegram → tu incolli il ticket in `watch.py add` → `watch.py run` tutto il giorno**. Confronta il prezzo Yahoo (yfinance) con ingresso / stop / target già scritti sulla scheda. Se un pezzo manca, vede solo il prezzo e salta quell’alert.

Non piazza ordini. Non è consulenza finanziaria.

## Install

```bash
pip install -r requirements.txt
```

## Uso

Aggiungi una o più schede (stdin: incolla, poi Ctrl+D):

```bash
python watch.py add
```

O da file:

```bash
python watch.py add scheda.txt
```

Poi:

```bash
python watch.py list
python watch.py remove AMD
python watch.py run
python watch.py run --interval 30
```

`run` stampa uno stato compatto a ogni ciclo (default 60s). **ALERT** quando:

- il prezzo tocca la banda di **ingresso**
- il prezzo è **≤ stop**
- il prezzo è **≥ target**

Ogni alert una volta sola, finché la condizione non si spegne (niente spam). Ctrl+C esce.

## Esempio `add`

```bash
python watch.py add <<'EOF'
$AMD · daily

Danny: Red candle on daily chart, panel 1

P1: …
Hole: 120–140, close in mezzo
CHIP: supporto a 132

Livelli: ingresso 130–134 · stop 124 · target 148
rossa daily sul bordo, whale 40
EOF
```

Serve `$TICKER`. Poi i numeri su `ingresso` / `stop` / `target` / `Livelli` se ci sono. Ticker tipo IBIT, MSTR, ETHA: stesso Yahoo, stesso comando.

Watchlist: `watchlist.json` (ticker, tf, ingresso_low, ingresso_high, stop, target, motivo). Stesso ticker + stesso timeframe: si sovrascrive.

## Telegram (opzionale)

Se ci sono `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` (default `-1003929227957`), l’alert va anche su Telegram. Senza token: solo console. Non si blocca.
