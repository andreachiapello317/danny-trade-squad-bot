import { dueForCeo, dueForSenderPoll } from "@/lib/store";
import { telegramCreds } from "@/lib/telegram";
import type { SquadState } from "@/lib/types";

export type PublicSquad = Omit<SquadState, "telegram"> & {
  telegram: { linked: boolean; chatId: string | null };
  dueCeo: boolean;
  dueSender: boolean;
};

export function toPublicSquad(state: SquadState): PublicSquad {
  const { token, chatId } = telegramCreds(state);
  const { telegram: _secret, ...rest } = state;
  return {
    ...rest,
    telegram: {
      linked: Boolean(token && chatId),
      chatId: chatId || null,
    },
    dueCeo: dueForCeo(state),
    dueSender: dueForSenderPoll(state),
  };
}
