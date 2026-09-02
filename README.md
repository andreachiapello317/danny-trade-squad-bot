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

## Morto vs Inversione (Analyst)

**Morto** (skip Telegram) solo se la morte è chiara: non è un grafico; close sotto il **bordo basso** dell’hole; gialla monthly + whale in calo; ribbon rossa che si stringe **e** bearish W/M; whale in calo **e** retail in salita (avanzato); whale <35% **e** in calo (avanzato); rossa stantia + ribbon che si stringe + whale in calo.

**Non è Morto** — resta Inversione o Sporco, **voto 1–10, va a Telegram**: ribbon appena girata rossa / candela rossa recente con CHIP ancora tetto; blu spessa ancora visibile sopra + nuovo inizio rosso; whale basso / retail alto / “not ready” da soli; close nel nodo pieno **sotto** un hole vuoto sopra (non è “close sotto hole low”); due verdi con P1 blu-sopra; P2 misto; P4/P5 non decidono.

Prompt Grok da incollare: `prompts/analyst-grok.md`. Il giro successivo vota da solo sul grafico e sulle regole. Non coachare il bot su un ticker.
