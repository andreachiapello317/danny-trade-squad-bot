# BotSquad — router Drive

Python aggiorna i post su Drive ogni 12 ore. L’Analyst (Grok) ogni 4 ore apre solo `Il mio Drive/PatreonPostdacontrollare`, legge i post **nuovi**, e fa da router. Non vota. Non filtra candele.

**Drive (12h) → Analyst (4h, solo nuovi) → Sender (Telegram, MUST READ) / Trader (watchlist, bullish signal)**

Grok non si sveglia da solo. Il prompt dice ogni 4 ore; tu gli mandi il ping `giro 4 ore`.

## Cosa passa

| Post | Dove | Cosa |
| --- | --- | --- |
| MUST READ / Must Read / must-read | Sender → Telegram | Testo + foto così com’è. Un post = un messaggio (o un album) |
| Titolo «Stock with bullish signal today» | Trader | Lista ticker + motivo di Danny + chart. No Telegram |
| Tutto il resto (Bullish, Trending, My BUY, HOW TO, dump) | — | Salta. Foto/cartella dopo |

HOW TO: salta. Niente di nuovo: `nessun post nuovo` e chiudi.

## Come si usa

1. Incolla `prompts/analyst-grok.md` in una chat Grok — questa è l’Analyst.
2. Incolla `prompts/sender-grok.md` in una chat Grok — questa è il Sender.
3. Incolla `prompts/trader-grok.md` in una chat Grok — questa è il Trader.
4. Tieni lo script Python su 12 ore. Non ricostruire il downloader. Path Drive, non `C:\Users\...`.
5. Ogni 4 ore pinghi l’Analyst: `giro 4 ore`. Se escono blocchi, li inoltri a Sender o Trader. Se dice `nessun post nuovo`, stop.

Il Sender ogni 2 ore fa solo quello che gli scrivi. Se l’Analyst non ha mandato un MUST READ, sta fermo.

`lib/score.ts` è leftover (vecchio voto 1–10). Non è il bot live.
