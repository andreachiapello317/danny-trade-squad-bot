import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { BOARD_CACHE_MS } from "@/lib/timing";
import type { HypeResponse } from "@/lib/types";

const STORE_PATH = path.join(process.cwd(), ".data", "board.json");

export const BOARD_VERSION = 4;

export type StoredBoard = {
  at: number;
  version?: number;
  board: HypeResponse;
};

let memory: StoredBoard | null = null;
let diskRead = false;

export function stampBoard(board: HypeResponse, at: number): HypeResponse {
  return {
    ...board,
    generatedAt: board.generatedAt || new Date(at).toISOString(),
    nextSearchAt: new Date(at + BOARD_CACHE_MS).toISOString(),
  };
}

export function isBoardFresh(stored: StoredBoard) {
  return Date.now() - stored.at < BOARD_CACHE_MS;
}

export async function peekStoredBoard(): Promise<HypeResponse | null> {
  const stored = await readStoredBoard();
  if (!stored) return null;
  return stampBoard(stored.board, stored.at);
}

function usable(stored: StoredBoard | null): StoredBoard | null {
  if (!stored?.board || typeof stored.at !== "number") return null;
  if (stored.version !== BOARD_VERSION) return null;
  return stored;
}

export async function readStoredBoard(): Promise<StoredBoard | null> {
  const fromMemory = usable(memory);
  if (fromMemory) return fromMemory;
  memory = null;
  if (diskRead) return null;
  diskRead = true;
  try {
    const raw = await readFile(STORE_PATH, "utf8");
    const parsed = usable(JSON.parse(raw) as StoredBoard);
    if (parsed) {
      memory = parsed;
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

export async function writeStoredBoard(board: HypeResponse): Promise<StoredBoard> {
  const stored: StoredBoard = { at: Date.now(), version: BOARD_VERSION, board };
  memory = stored;
  await mkdir(path.dirname(STORE_PATH), { recursive: true });
  await writeFile(STORE_PATH, JSON.stringify(stored));
  return stored;
}
