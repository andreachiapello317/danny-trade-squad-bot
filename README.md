# BotSquad — router Drive

Python ogni 12 ore mette i post su Drive. Analyst ogni 4 ore apre `Il mio Drive/PatreonPostdacontrollare`, legge le cartelle nuove, instrada. Un post alla volta.

**Drive → Analyst → Sender (Telegram) / Trader (watchlist → Sender → Telegram)**

Ping Analyst: `giro 4 ore`.

| Titolo | Destino | Chat |
| --- | --- | --- |
| MUST READ | Sender, un ticker = un messaggio + tutte le sue foto | `-1004349690570` |
| HOW TO | Sender, post intero così com’è, un album | `-1004382873897` |
| TRENDING STOCK | Sender, un ticker = un messaggio + tutte le sue foto | `-5021603163` |
| Stock with bullish signal today | Trader (scheda one-shot) → Sender | `-1003929227957` |
| Altro | post successivo | — |

MUST READ e Trending: un ticker, un messaggio, tutte le sue foto. HOW TO intero. Trader: un trade unico, un click; ticket `$TICKER · weekly · ENTRA` su `-1003929227957`. Zero shot: `nessuno shot`, Telegram fermo.

Niente di nuovo: `nessun post nuovo`.

Incolla in tre chat Grok: `prompts/analyst-grok.md`, `prompts/sender-grok.md`, `prompts/trader-grok.md`. Python resta su 12 ore.

`lib/score.ts` è leftover.

## Price watch

Le schede Trader su Telegram sono watchlist + livelli (ingresso/stop/target), non ordini. Script: `watch.py` — come usarlo in `WATCH.md`. `pip install -r requirements.txt`, poi `python watch.py add` (incolli il ticket) e `python watch.py run` tutto il giorno. Solo prezzo vs i livelli già sulla scheda.
