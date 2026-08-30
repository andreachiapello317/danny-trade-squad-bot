"use client";

import { fivePanelSvg } from "@/lib/five-panel-svg";
import type { Sighting } from "@/lib/types";

export function FivePanel({ sighting }: { sighting: Sighting }) {
  return (
    <div
      className="overflow-hidden rounded-xl ring-1 ring-white/10"
      dangerouslySetInnerHTML={{ __html: fivePanelSvg(sighting) }}
    />
  );
}
