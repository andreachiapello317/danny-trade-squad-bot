# Watchlist

Non è un sistema di alert.

## Cosa fa

Dal menu Telegram → Watchlist:

- **Set buy**: un ticker, entry sotto spot, strategia, azioni, delta.
- **Upload buy**: lista `TICKER PREZZO` (anche in massa: `AMD 120`, `AMD $120`, `NVDA:140`). Solo watchlist, niente strategia. Un nuovo upload sullo stesso ticker riarma l'entry.
- **Gestisci buy**: selezioni i ticker, scegli la strategia (oggi Trail), importo in **$ per titolo**, poi delta %. Le azioni sono `ceil($ / spot)`, minimo 1.

Quando il prezzo tocca l'entry, parte la strategia scelta.

Prima di armare (Set buy, Gestisci buy, Trail guidato) il bot chiede conferma con stima IBKR: what-if (costo + fee), buying power, halt/sessione, ATR e volume. Il Trail **non compra** se il titolo è in halt o il mercato è chiuso. Gli ordini LMT automatici usano ask/bid (non last × 1.005). Stop e limiti sono arrotondati al minTick. La lista mostra spot / low / close; in home compaiono PnL del giorno e liquidità disponibile.

## Cosa non fa più

- Non importa i ticket `$TICKER` del canale Trader
- Non imposta ingresso / stop / target
- Non manda `ALERT AMD ingresso …` su Telegram
- I comandi `/set`, `/setbuy`, `/setstop`, `/settarget` sono disattivati

## Trail, in breve

Compra subito a mercato. Break-even = medio + 1% entrata + 1% uscita. Il delta è in %. Quando il prezzo supera il BE di un delta, parte uno stop su quel livello e sale a scalini. **Ferma Trail** cancella lo stop e lascia la posizione.
