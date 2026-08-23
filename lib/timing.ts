/** Un ciclo solo: ricerca, classifica e Telegram ogni 6 ore. */
export const SEARCH_INTERVAL_MS = 6 * 60 * 60 * 1000;

export const PAGE_REFRESH_MS = SEARCH_INTERVAL_MS;
export const BOARD_CACHE_MS = SEARCH_INTERVAL_MS;
export const TELEGRAM_COOLDOWN_MS = SEARCH_INTERVAL_MS;
export const CHECK_CACHE_MS = SEARCH_INTERVAL_MS;
