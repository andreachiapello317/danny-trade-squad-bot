import type { Sighting } from "@/lib/types";

function esc(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function fivePanelSvg(s: Sighting) {
  const ribbon =
    s.ribbon === "red_widening"
      ? { fill: "#ef4444", w: 18 }
      : s.ribbon === "red_thinning"
        ? { fill: "#f87171", w: 8 }
        : s.ribbon === "thick_blue_above"
          ? { fill: "#3b82f6", w: 20 }
          : { fill: "#3f3f46", w: 10 };
  const candle =
    s.candle === "fresh_red_wm" || s.hole === "close_above_high"
      ? "#ef4444"
      : s.candle === "yellow_weekly" || s.candle === "yellow_monthly"
        ? "#eab308"
        : s.candle === "dark_blue_continuation"
          ? "#1d4ed8"
          : "#71717a";
  const priceY =
    s.ribbon === "thick_blue_above" ? 70 : s.chaseClose ? 28 : s.atSupport ? 52 : 44;
  const whale = s.whalePct ?? 0;
  const whaleColor = s.whaleDeclining ? "#f97316" : whale >= 50 ? "#22c55e" : "#a1a1aa";
  const p2 =
    s.panel2 === "flip_green_red_widening"
      ? "#ef4444"
      : s.panel2 === "off_or_red_to_green"
        ? "#22c55e"
        : "#3f3f46";
  const holeY =
    s.hole === "close_above_high" ? 30 : s.hole === "close_below_low" ? 78 : 54;
  const chipLabel = s.chip === "absent" ? "n/d" : s.chip.replace(/_/g, " ");
  const ticker = esc(s.ticker || "—");
  const name = esc(s.name || "");

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 420" width="640" height="420">
  <rect width="640" height="420" fill="#09090b"/>
  <text x="16" y="22" fill="#e4e4e7" font-family="ui-sans-serif, system-ui" font-size="14" font-weight="700">${ticker} 5 pannelli</text>
  <text x="16" y="38" fill="#a1a1aa" font-family="ui-sans-serif, system-ui" font-size="10">${name} · D${s.hasDaily ? "" : " no"} W${s.hasWeekly ? "" : " no"} M${s.hasMonthly ? "" : " no"}</text>

  <rect x="12" y="48" width="616" height="150" rx="8" fill="#18181b" stroke="#27272a"/>
  <text x="22" y="66" fill="#71717a" font-size="10" font-family="ui-sans-serif, system-ui">P1 ribbon / candela / CHIP / hole</text>
  <rect x="40" y="${70 - ribbon.w / 2}" width="560" height="${ribbon.w}" rx="4" fill="${ribbon.fill}" opacity="0.55"/>
  <rect x="430" y="58" width="36" height="110" rx="2" fill="#14532d" opacity="0.35"/>
  <text x="434" y="168" fill="#86efac" font-size="9" font-family="ui-sans-serif, system-ui">hole</text>
  <circle cx="480" cy="${holeY + 48}" r="5" fill="${s.hole === "close_below_low" ? "#f97316" : "#f4f4f5"}"/>
  <rect x="300" y="${priceY + 48}" width="14" height="36" fill="${candle}"/>
  <rect x="297" y="${priceY + 40}" width="20" height="8" fill="${candle}"/>
  <line x1="40" y1="155" x2="600" y2="155" stroke="#52525b" stroke-dasharray="4 6"/>
  <text x="40" y="188" fill="#a1a1aa" font-size="9" font-family="ui-sans-serif, system-ui">CHIP ${chipLabel}</text>

  <rect x="12" y="208" width="200" height="90" rx="8" fill="#18181b" stroke="#27272a"/>
  <text x="22" y="226" fill="#71717a" font-size="10" font-family="ui-sans-serif, system-ui">P2 momentum</text>
  <rect x="28" y="240" width="18" height="40" fill="${p2}"/>
  <rect x="52" y="232" width="22" height="48" fill="${p2}"/>
  <rect x="80" y="224" width="26" height="56" fill="${p2}"/>
  <rect x="112" y="236" width="20" height="44" fill="${p2}" opacity="0.7"/>

  <rect x="220" y="208" width="200" height="90" rx="8" fill="#18181b" stroke="#27272a"/>
  <text x="230" y="226" fill="#71717a" font-size="10" font-family="ui-sans-serif, system-ui">P3 whale ${whale}%</text>
  <rect x="236" y="240" width="168" height="16" rx="4" fill="#27272a"/>
  <rect x="236" y="240" width="${Math.max(4, Math.min(168, (whale / 100) * 168))}" height="16" rx="4" fill="${whaleColor}"/>
  <text x="236" y="276" fill="${whaleColor}" font-size="10" font-family="ui-sans-serif, system-ui">${s.whaleDeclining ? "in calo" : s.whaleRising ? "in salita" : "n/d"} ${s.retailDominant ? "· retail alto" : ""}</text>

  <rect x="428" y="208" width="200" height="90" rx="8" fill="#18181b" stroke="#27272a"/>
  <text x="438" y="226" fill="#71717a" font-size="10" font-family="ui-sans-serif, system-ui">P4 MACD · P5 RSI</text>
  <text x="438" y="258" fill="${s.macdBearCrossBelowZero ? "#f97316" : "#71717a"}" font-size="11" font-family="ui-sans-serif, system-ui">MACD ${s.macdBearCrossBelowZero ? "bear sotto 0" : "non si spara"}</text>
  <text x="438" y="278" fill="${s.rsiBelow50StackedWrong ? "#f97316" : "#71717a"}" font-size="11" font-family="ui-sans-serif, system-ui">RSI ${s.rsiBelow50StackedWrong ? "&lt;50 contrario" : "non si spara"}</text>

  <rect x="12" y="308" width="616" height="98" rx="8" fill="#18181b" stroke="#27272a"/>
  <text x="22" y="328" fill="#71717a" font-size="10" font-family="ui-sans-serif, system-ui">Posizione · due prezzi · zona</text>
  <text x="22" y="352" fill="#e4e4e7" font-size="13" font-family="ui-sans-serif, system-ui">${s.chaseClose ? "CHASE" : s.atSupport ? "A SUPPORTO" : "—"}  close ${esc(s.closePrice || "n/d")}</text>
  <text x="22" y="374" fill="#a3e635" font-size="12" font-family="ui-sans-serif, system-ui">accel ${esc(s.accelPrice || "manca")}   inv ${esc(s.invPrice || "manca")}</text>
  <text x="22" y="394" fill="#fafafa" font-size="12" font-family="ui-sans-serif, system-ui">zona ${esc(s.zoneLow || "—")}–${esc(s.zoneHigh || "—")}</text>
</svg>`;
}
