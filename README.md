# BotSquad

Desk della squadra che legge i grafici della newsletter di Danny Chang, vota i setup di **buy** (non i nomi) e tiene un carrello da 10. Ogni 4 ore il carrello va **solo al CEO**. Lui dice Valida o Non valida. **Solo il Sender** scrive su Telegram. Niente wallet, niente size.

Flusso: Patreon → Reader → Analyst (tutti) + Sender (post caldi) + CEO (HOW TO) → carrello Analyst → CEO valida → Sender su Telegram. Il Trader è nel gruppo ma è fuori da quel tubo.

## Avvio

```bash
npm install
npm test
npm run dev
```

Apri [http://127.0.0.1:43211](http://127.0.0.1:43211).

Sul telefono, stessa rete:

```bash
npm run phone
```

Poi `http://IP-DEL-COMPUTER:43211`.

## Ruoli

| Sedia | Cosa fa | Cosa non fa |
| --- | --- | --- |
| Reader | Incolla Patreon/mail. Instrada. | Opinioni, voto, Telegram |
| Analyst | Legge i 5 pannelli, voto 1–10, carrello da 10 + ultime 10 rosse | Wallet, size, Telegram |
| CEO | Valida / Non valida. HOW TO. Inoltra al Sender | Non cambia i voti, non scrive su Telegram |
| Sender | Unica penna Telegram. Post caldi + carrello validato. Check ogni 2 ore | Non vota |
| Trader | Resta nel gruppo | Fuori dal flusso Telegram |

## Telegram

1. BotFather → `/newbot`
2. Apri il bot e premi Start
3. Incolla il token nella sedia Sender → Collega

Oppure `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` in `.env.local`.

Senza bot gli invii restano **mock** nell’outbox: il desk funziona lo stesso.

## Cicli

- Ogni 4 ore: carrello all’CEO (`POST /api/tick` o `POST /api/cart/dispatch`)
- Ogni 2 ore: il Sender guarda se il CEO ha scritto (`POST /api/sender/flush`)

Il canone di voto è in `lib/score.ts` e sulla sedia CEO. I test: `npx vitest run`.
