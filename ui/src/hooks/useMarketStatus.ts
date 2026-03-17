import { useState, useEffect } from "react";

export type MarketSession = "pre-market" | "market open" | "post-market" | "off hours";

interface MarketStatus {
  session: MarketSession;
  label: string;
  dotClass: string;
  icon?: string; // emoji override — replaces dot when set
}

function getEtMinutes(): number {
  // Get current time in ET (handles EST/EDT automatically)
  const etStr = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date());

  const [h, m] = etStr.split(":").map(Number);
  return h * 60 + m;
}

function computeStatus(): MarketStatus {
  const mins = getEtMinutes();

  // 04:00 – 09:30  pre-market
  // 09:30 – 16:00  market open
  // 16:00 – 20:00  post-market
  // 20:00 – 04:00  off hours
  if (mins >= 4 * 60 && mins < 9 * 60 + 30) {
    return { session: "pre-market",  label: "pre-market",  dotClass: "dot--yellow", icon: "🌤" };
  }
  if (mins >= 9 * 60 + 30 && mins < 16 * 60) {
    return { session: "market open", label: "market open", dotClass: "dot--green" };
  }
  if (mins >= 16 * 60 && mins < 20 * 60) {
    return { session: "post-market", label: "post-market", dotClass: "dot--yellow", icon: "🌙" };
  }
  return   { session: "off hours",   label: "off hours",   dotClass: "dot--red" };
}

export function useMarketStatus(): MarketStatus {
  const [status, setStatus] = useState<MarketStatus>(computeStatus);

  useEffect(() => {
    // Recompute every 30 seconds — cheap enough, precise enough
    const id = setInterval(() => setStatus(computeStatus()), 30_000);
    return () => clearInterval(id);
  }, []);

  return status;
}
