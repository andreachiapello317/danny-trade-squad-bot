# Danny Trade Squad Bot

Bot Telegram collegato a IBKR (via IBeam). Home: Watchlist, Trading, Trading automatico, Conto, Info.

Non è consulenza finanziaria.

## Watchlist

Set buy arma un ticker con un **entry sotto il prezzo attuale**. Quando il prezzo tocca o scende sotto quell'entry parte la strategia scelta.

Oggi l'unica strategia selezionabile è **Trail**:

1. Compra a mercato (LMT auto ≈ spot × 1.005, `outsideRTH`).
2. Nessuno stop sotto il prezzo di carico.
3. Break-even = medio × 1.01 / 0.99 (1% entrata + 1% uscita).
4. Il delta è in % del BE. Ogni scalino alza lo stop.

I ticket Trader e i vecchi comandi `/set`, `/setbuy`, `/setstop`, `/settarget` non scrivono più livelli. Non partono più alert Telegram di ingresso/stop/target.

## Avvio locale

```bash
cd danny-trade-squad-bot
python3 -m pip install -r requirements.txt
cp .env.example .env   # se c'è: TELEGRAM_BOT_TOKEN, IBeam
python3 server.py
```

Il webhook Flask e il ciclo prezzi girano insieme. Il ciclo controlla gli entry 24/7 (non solo 15–22).

## Test

```bash
python3 -m unittest test_watch test_server -q
```

## Deploy

Da questa cartella: `gomain` (Railway/IBeam già previsti dal repo).
