# Radar Solana — cosa sta partendo

Classifica i token Solana da **200k di market cap** in su. I launch entrano **dopo 30 minuti**, non prima.

X vale il 10% e conta i **post della gente** sul ticker, non l’account ufficiale. Il resto è accelerazione e launch (dopo 30 minuti). Chi ha già fatto +80% oggi finisce sotto, in “già pompate oggi”.

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
