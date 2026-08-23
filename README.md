# Radar Hype Solana

App web che classifica i token Solana con più attenzione in questo momento.

Il primo posto combina:

1. **X** — profilo ufficiale e post recenti (follower, view, like, reply)
2. **Trending CoinGecko**
3. **Pool Solana in tendenza** su GeckoTerminal
4. **Volume, transazioni e boost** DexScreener

Non è consulenza finanziaria. I memecoin sono estremamente volatili.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## API

`GET /api/hype` restituisce il vincitore e la classifica, ricalcolati a ogni richiesta dalle API pubbliche.
