import { HypeRadar } from "@/components/hype-radar";
import { getHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";
export const maxDuration = 30;

export default async function Home() {
  const initial = await getHypeBoard();
  return <HypeRadar initial={initial} />;
}
