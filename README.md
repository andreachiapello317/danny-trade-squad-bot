# Radar NASDAQ — trending listate

Classifica le azioni **comuni listate sul NASDAQ** più in trending: volume, rialzi e Nasdaq-100.

La ricerca, la classifica e Telegram girano insieme ogni **2 ore**. Aprire la pagina non lancia una nuova caccia. Nel messaggio ogni riga ha il ticker da copiare, il link X e il grafico.

Non è consulenza finanziaria.

## Avvio locale

```bash
npm install
npm run dev -- --port 43177 --hostname 127.0.0.1
```

Apri [http://127.0.0.1:43177](http://127.0.0.1:43177).

## Telegram

1. Apri Telegram e cerca **BotFather**.
2. Scrivi `/newbot`, scegli un nome e un username che finisce con `bot`.
3. Copia il token, apri il bot e premi **Start**.
4. Incolla il token nella card in pagina e premi **Collega**.

## API

`GET /api/stocks` restituisce la classifica.
`GET /api/tickers` è il testo dei 4 ticker.
