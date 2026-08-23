import { HypeRadar } from "@/components/hype-radar";
import { peekHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";

export default async function Home() {
  const initial = await peekHypeBoard();
  return <HypeRadar initial={initial} />;
}
