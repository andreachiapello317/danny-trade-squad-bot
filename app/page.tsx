import { HypeRadar } from "@/components/hype-radar";
import { getHypeBoard } from "@/lib/hype";

export const dynamic = "force-dynamic";

export default async function Home() {
  const initial = await getHypeBoard();
  return <HypeRadar initial={initial} />;
}
