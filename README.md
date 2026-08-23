# Radar Hype Solana

App web che classifica i token Solana con più attenzione in questo momento.

Il primo posto combina:

1. **Trending CoinGecko** (proxy dell’hype social / search, il segnale più vicino a X)
2. **Pool Solana in tendenza** su GeckoTerminal
3. **Volume, transazioni e boost** DexScreener

La ricerca diretta dei post su X non è inclusa: l’account X collegato non è ancora abilitato alla console developer.

Non è consulenza finanziaria. I memecoin sono estremamente volatili.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## API

`GET /api/hype` restituisce il vincitore e la classifica, ricalcolati a ogni richiesta dalle API pubbliche.
