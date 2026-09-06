# BotSquad — router Drive

Python ogni 12 ore mette i post su Drive. Analyst ogni 4 ore apre `Il mio Drive/PatreonPostdacontrollare`, legge le cartelle nuove, instrada. Un post alla volta.

**Drive → Analyst → Sender (Telegram) / Trader (watchlist → Sender → Telegram)**

Ping Analyst: `giro 4 ore`.

| Titolo | Destino | Chat |
| --- | --- | --- |
| MUST READ | Sender, un ticker = un messaggio + quella foto | 4349690570 |
| HOW TO | Sender, un post = un album (lista ticker: spezza) | 4382873897 |
| TRENDING STOCK | Sender, un ticker = un messaggio + quella foto | 5021603163 |
| Stock with bullish signal today | Trader (scheda one-shot) → Sender | 3929227957 |
| Altro | post successivo | — |

MUST READ e Trending: Analyst spezza per ticker, Sender manda un titolo / un messaggio / una foto. HOW TO resta un pezzo. Trader: un trade unico, un click, stesso spezzamento su 3929227957. Zero shot: `nessuno shot`, Telegram fermo.

Niente di nuovo: `nessun post nuovo`.

Incolla in tre chat Grok: `prompts/analyst-grok.md`, `prompts/sender-grok.md`, `prompts/trader-grok.md`. Python resta su 12 ore.

`lib/score.ts` è leftover.
