# Watchlist

Non è un sistema di alert.

## Cosa fa

Dal menu Telegram → Watchlist:

- **Set buy**: un ticker, entry sotto spot, strategia, azioni, delta.
- **Upload buy**: lista `TICKER PREZZO` (anche in massa). Solo watchlist, niente strategia.
- **Gestisci buy**: selezioni i ticker, scegli la strategia (oggi Trail), importo in **$ per titolo**, poi delta %. Le azioni sono `ceil($ / spot)`, minimo 1.

Quando il prezzo tocca l'entry, parte la strategia scelta.

## Cosa non fa più

- Non importa i ticket `$TICKER` del canale Trader
- Non imposta ingresso / stop / target
- Non manda `ALERT AMD ingresso …` su Telegram
- I comandi `/set`, `/setbuy`, `/setstop`, `/settarget` sono disattivati

## Trail, in breve

Compra subito a mercato. Break-even = medio + 1% entrata + 1% uscita. Il delta è in %. Quando il prezzo supera il BE di un delta, parte uno stop su quel livello e sale a scalini. **Ferma Trail** cancella lo stop e lascia la posizione.
