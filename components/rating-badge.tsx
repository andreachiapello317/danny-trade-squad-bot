import { Badge } from "@/components/ui/badge";
import type { Rating } from "@/lib/types";
import { cn } from "@/lib/utils";

const tone: Record<Rating, string> = {
  "Strong Buy": "border-lime-500/40 bg-lime-500/15 text-lime-300",
  Buy: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
  Hold: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  Sell: "border-orange-500/40 bg-orange-500/15 text-orange-300",
  "Sell Now": "border-red-500/40 bg-red-500/15 text-red-300",
};

export function RatingBadge({ rating, className }: { rating: Rating; className?: string }) {
  return (
    <Badge variant="outline" className={cn(tone[rating], className)}>
      {rating}
    </Badge>
  );
}

export function VoteMark({
  vote,
  rating,
  size = "lg",
}: {
  vote: number;
  rating: Rating;
  size?: "lg" | "sm";
}) {
  const color =
    rating === "Strong Buy" || rating === "Buy"
      ? "text-lime-300"
      : rating === "Hold"
        ? "text-amber-300"
        : rating === "Sell"
          ? "text-orange-300"
          : "text-red-300";
  return (
    <span
      className={cn(
        "font-mono font-semibold tabular-nums leading-none",
        size === "lg" ? "text-4xl" : "text-xl",
        color
      )}
    >
      {vote}
    </span>
  );
}
