# Watchlist

Non è un sistema di alert.

## Cosa fa

Dal menu Telegram → Watchlist → **Set buy**:

1. Ticker
2. Prezzo di entry **sotto** lo spot IBKR
3. Strategia (ora solo Trail)
4. Numero di azioni
5. Delta in %

Quando il prezzo tocca l'entry, il bot avvia Trail da solo (stesso flusso di Trading automatico → Trail).

## Cosa non fa più

- Non importa i ticket `$TICKER` del canale Trader
- Non imposta ingresso / stop / target
- Non manda `ALERT AMD ingresso …` su Telegram
- I comandi `/set`, `/setbuy`, `/setstop`, `/settarget` sono disattivati

## Trail, in breve

Compra subito a mercato. Break-even = medio + 1% entrata + 1% uscita. Il delta è in %. Quando il prezzo supera il BE di un delta, parte uno stop su quel livello e sale a scalini. **Ferma Trail** cancella lo stop e lascia la posizione.
