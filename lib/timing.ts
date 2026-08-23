/** Classifica in pagina: ogni 5 minuti. */
export const PAGE_REFRESH_MS = 5 * 60 * 1000;

/** Ricalcolo feed: stesso ritmo della pagina. */
export const BOARD_CACHE_MS = 5 * 60 * 1000;

/** Telegram: un messaggio, e non prima di 15 minuti dal precedente. */
export const TELEGRAM_COOLDOWN_MS = 15 * 60 * 1000;

/** RugCheck e X: non a ogni apertura, tengono 15 minuti. */
export const CHECK_CACHE_MS = 15 * 60 * 1000;
