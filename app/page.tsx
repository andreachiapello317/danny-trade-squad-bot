import { StockRadar } from "@/components/stock-radar";
import { peekStockBoard } from "@/lib/stocks";

export const dynamic = "force-dynamic";

export default async function Home() {
  const initial = await peekStockBoard();
  return <StockRadar initial={initial} />;
}
