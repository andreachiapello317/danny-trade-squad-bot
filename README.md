# BotSquad — router Drive

Python aggiorna i post su Drive ogni 12 ore. L’Analyst ogni 4 ore apre `Il mio Drive/PatreonPostdacontrollare`, legge i post nuovi, instrada.

**Drive (12h) → Analyst (4h, post nuovi) → Sender (Telegram) / Trader (watchlist)**

Ogni 4 ore mandi all’Analyst il ping `giro 4 ore`.

## Cosa passa

| Post | Dove | Cosa |
| --- | --- | --- |
| MUST READ / Must Read / must-read | Sender → chat **4349690570** | Testo + foto, com’è. Un post = un messaggio (o un album) |
| TRENDING STOCK / Trending Stock / trending stock | Sender → chat **5021603163** | Testo + foto, com’è. Un post = un messaggio (o un album) |
| HOW TO / How To / how-to | Sender → chat **4382873897** | Testo + foto, com’è. Un post = un messaggio (o un album) |
| Titolo «Stock with bullish signal today» | Trader | Lista `$TICKER — motivo` + chart |
| Altro titolo | — | Post successivo |

Niente di nuovo: `nessun post nuovo` e chiudi.

## Come si usa

1. Incolla `prompts/analyst-grok.md` in una chat Grok — Analyst.
2. Incolla `prompts/sender-grok.md` in una chat Grok — Sender.
3. Incolla `prompts/trader-grok.md` in una chat Grok — Trader.
4. Python resta su 12 ore. Path Drive: `Il mio Drive/PatreonPostdacontrollare`.
5. Ogni 4 ore: `giro 4 ore` all’Analyst. I blocchi DEST: Sender vanno al Sender. DEST: Trader vanno al Trader. `nessun post nuovo`: stop.

Il Sender ogni 2 ore fa quello che gli scrivi. Legge TIPO + CHAT dal blocco e pubblica lì.

`lib/score.ts` è leftover.
