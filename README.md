# Radar Solana — nomi grossi in accelerazione

Classifica i token Solana **già listati e verificati** che stanno partendo adesso: market cap da 15M in su, liquidità reale, presenza nella lista Jupiter verified.

Non è la lista dei launch da un’ora, né dei ticker già +200% oggi. Quelli, se passano i filtri, finiscono sotto in “già pompate oggi”.

Ogni candidato in cima passa anche RugCheck (mint, freeze, LP, holder) e il confronto col profilo X ufficiale.

Non è consulenza finanziaria.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## API

`GET /api/hype` restituisce `tokens` (in accelerazione) e `established` (già pompate oggi).
