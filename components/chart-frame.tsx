import { EmptyState } from "@/components/empty-state";

export function ChartFrame({
  src,
  ticker,
  compact,
}: {
  src: string | null;
  ticker: string;
  compact?: boolean;
}) {
  if (!src) {
    return (
      <EmptyState
        title={`Manca la foto a 5 pannelli di ${ticker}`}
        body="Senza quella foto il titolo non entra in carrello. Non si inventa la zona."
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={src}
      alt={`${ticker} 5 pannelli`}
      className={
        compact
          ? "h-auto w-full rounded-lg ring-1 ring-white/10"
          : "h-auto w-full rounded-xl ring-1 ring-white/10"
      }
    />
  );
}
