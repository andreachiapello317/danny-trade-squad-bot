export const CANON_TITLE = "HOW TO — si vota il setup, non il nome";

export const CANON_INTRO =
  "Il voto parte da 0. Si sommano solo i pezzi visibili sul grafico. Poi vincono i tetti. Se un pezzo non c’è, quel punto non si dà. Non si tocca wallet. Non si fa size.";

export const CANON_SECTIONS: { title: string; body: string }[] = [
  {
    title: "Timeframe",
    body: "Weekly o monthly presente +2. Solo daily +0. Monthly rotto (gialla monthly + whale in calo) mentre il daily è bello: non si somma, ramo sell. Senza weekly il voto non può superare 5.",
  },
  {
    title: "Ribbon — pannello 1",
    body: "Rossa che si allarga, prezzo sul bordo o sopra +2. Rossa che si assottiglia +1. Blu spessa sopra il prezzo +0 e tetto 3, non è un buy. Estensione (prezzo troppo lontano) −1.",
  },
  {
    title: "Candela — pannello 1",
    body: "Rossa W/M fresca prima settimana (daily: primi due giorni), <5 giorni +2. Blu scure di continuazione su ribbon rossa +1. Gialla weekly +0, non è un buy, tetto 5. Gialla monthly: non è un buy, ramo sell. La size della candela sul pannello 1 vale 0. Sul breach del bordo alto dell’hole il colore non conta: close sopra il bordo alto = accumulo +2 (rossa o gialla uguale).",
  },
  {
    title: "CHIP",
    body: "Prezzo sopra il CHIP lungo usato come supporto +1. Prezzo sotto il CHIP usato come tetto / incollato alla resistenza −2. Appena bucato CHIP da resistenza a supporto +1.",
  },
  {
    title: "Hole",
    body: "Close sopra il bordo alto +2. Hole + ribbon blu discendente (prima accumulazione) +1, non è un buy pieno. Close in mezzo +0. Close sotto il bordo basso: non si somma, ramo sell. Senza close fuori dal bordo non si scommette la direzione.",
  },
  {
    title: "Pannello 2",
    body: "Flip verde→rosso, barre che si allargano +1. Già spento o rosso→verde −1. Qui la size conta. Da solo non basta per un buy.",
  },
  {
    title: "Whale — pannello 3",
    body: "≥75% in salita +3. 50–74% in salita +2. 35–49% +1. Sotto 35% +0 e tetto 4. Whale in calo −1. Retail dominante −1. Sotto 50% non entra in carrello come Buy: tetto 6.",
  },
  {
    title: "Pannello 4 e 5",
    body: "Nessun punto extra. Se contraddicono (MACD sotto zero in croce bear, RSI sotto 50 impilato al contrario) mentre stavi per dire Buy: −1. Non si spara su MACD/RSI.",
  },
  {
    title: "Posizione",
    body: "A supporto (ribbon / CHIP / POC) +2. Close già sopra la zona (chase) −2, non si allarga la zona. Rossa più vecchia di 5 giorni / oltre la prima settimana −2.",
  },
  {
    title: "Due prezzi",
    body: "Accel e inv scritti, non copiati dal high/low della candela in corso +1. Se mancano: −1 e non è Buy.",
  },
  {
    title: "Grafici",
    body: "D+W allegati +0 (minimo). Senza weekly: tetto 5. Senza grafico a 5 pannelli: tetto 4, mai Buy, nessuna zona inventata.",
  },
  {
    title: "Tetti che battono la somma",
    body: "Rossa sotto ribbon blu spessa max 3. Whale sotto 35 max 4. Senza weekly max 5. Whale sotto 50 max 6, niente Strong Buy/Buy da carrello. Gialla weekly max 5. Senza 5 pannelli max 4. Chase close: togli 2 e diventa Hold o sotto.",
  },
  {
    title: "Voto finale e rating",
    body: "Voto 1–10 con una riga (ribbon, whale, candela, hole, posizione). 9–10 Strong Buy (raro: rossa W/M fresca, ribbon rossa che si allarga, whale ≥75 in salita, a supporto, due prezzi, D+W). 7–8 Buy (il 7 spesso è condizionale: vale sulla zona, non sul close; se il close è già fuori, non è Buy). 5–6 Hold (gialla weekly con ribbon rossa e whale alti, o hole+blu fondo precoce senza breach; niente zona da comprare ora; il watch remoto resta qui). 3–4 Sell. 1–2 Sell Now (gialla monthly + whale in calo, o hole bucato in giù, o ribbon rossa che si stringe con bearish W/M).",
  },
  {
    title: "Secchio: Morto / Inversione / Setup / Sporco",
    body: "Morto (skip Telegram) solo se la morte è chiara: non è un grafico; close sotto il bordo basso dell’hole; gialla monthly + whale in calo; ribbon rossa che si stringe E bearish W/M; whale in calo E retail in salita (avanzato); whale <35% E in calo (avanzato); rossa stantia + ribbon che si stringe + whale in calo. NON è Morto: ribbon appena girata rossa / candela rossa recente con CHIP ancora tetto; blu spessa ancora sopra più un nuovo inizio rosso; whale basso / retail alto / not-ready da soli; close nel nodo pieno sotto un hole vuoto sopra (non è “sotto il bordo basso”); due verdi con P1 blu-sopra e P3 retail; P2 misto; P4/P5 (MACD/RSI) non decidono mai Morto. Inversione: precoce, direzione non chiusa — ribbon appena rossa, rossa recente, hole in mezzo o hole+blu discendente ancora sopra, P2 verde→rosso prima del rosso su P1, whale appena smesso di scendere / 35–49, o whale ancora assente ma il colore è appena girato. Inversione: voto 1–10, va a Telegram, zona di solito no. Setup: confluenza su questa foto (ribbon rossa sul bordo, e/o close sopra hole alto, e/o CHIP res→sup, rossa fresca o blu scure, whale in salita). Sporco: non morto, non pulito (rossa sotto blu spessa; chase; gialla con whale ancora alto; P2 vs candela misti). Sporco e Inversione votano e vanno a Telegram.",
  },
  {
    title: "Quattro cose che non si fanno",
    body: "Niente wallet, niente size. Non si flippa Strong Buy e Sell Now sullo stesso grafico nello stesso giro. Non si mette un ticker in carrello senza la foto a 5 pannelli. Non si manda il carrello al Trader o su Telegram: ogni 4 ore il carrello va solo al CEO; lui valida e inoltra.",
  },
  {
    title: "Cosa non può battere cosa",
    body: "Niente 8 senza weekly. Niente 9 con whale a 40. Niente Strong Buy sotto ribbon blu. Se il primo non è almeno Buy 7, si scrive che il mercato non sta offrendo un ingresso.",
  },
];

export const FLOW_LINE =
  "Patreon → Reader → Analyst (tutti) + Sender (post caldi) + CEO (HOW TO) → carrello Analyst → CEO valida → Sender su Telegram.";

export const TRADER_LINE =
  "Il Trader è nel gruppo, ma lo stampo non gli arriva più. Fuori dal flusso Telegram.";
