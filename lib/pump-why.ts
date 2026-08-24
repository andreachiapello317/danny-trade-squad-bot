import { tokenPitch } from "@/lib/pitch";
import type { HypeToken } from "@/lib/types";

/** Storia italiana per Telegram e card. Non è un via libera all’acquisto. */
export function pumpWhy(token: HypeToken): string {
  return tokenPitch(token);
}
