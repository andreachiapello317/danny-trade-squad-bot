# BotSquad — router Drive

Python ogni 12 ore mette i post su Drive. Analyst ogni 4 ore apre `Il mio Drive/PatreonPostdacontrollare`, legge le cartelle nuove, instrada. Un post alla volta.

**Drive → Analyst → Sender (Telegram) / Trader (watchlist → Sender → Telegram)**

Ping Analyst: `giro 4 ore`.

| Titolo | Destino | Chat |
| --- | --- | --- |
| MUST READ | Sender, testo + foto com’è | 4349690570 |
| HOW TO | Sender, testo + foto com’è | 4382873897 |
| TRENDING STOCK | Sender, testo + foto com’è | 5021603163 |
| Stock with bullish signal today | Trader → Sender, watchlist + foto | 3929227957 |
| Altro | post successivo | — |

Niente di nuovo: `nessun post nuovo`.

Incolla in tre chat Grok: `prompts/analyst-grok.md`, `prompts/sender-grok.md`, `prompts/trader-grok.md`. Python resta su 12 ore.

`lib/score.ts` è leftover.
