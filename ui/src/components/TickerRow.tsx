import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { StockTick } from "../types";

function formatVol(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toString();
}

interface Props {
  ticker: string;
  tick?: StockTick;
  prevPrice?: number;
  onRemove: () => void;
}

interface DropdownPos { top: number; right: number; }

export default function TickerRow({ ticker, tick, prevPrice, onRemove }: Props) {
  const up = (tick?.changePct ?? 0) >= 0;
  const changeColor = tick ? (up ? "var(--green)" : "var(--red)") : "var(--fg-muted)";
  const priceFlashClass =
    tick && prevPrice !== undefined && prevPrice !== tick.price
      ? tick.price > prevPrice ? "price-flash-up" : "price-flash-down"
      : "";

  const [dropdownPos, setDropdownPos] = useState<DropdownPos | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on outside click or scroll
  useEffect(() => {
    if (!dropdownPos) return;
    function close() { setDropdownPos(null); }
    document.addEventListener("pointerdown", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [dropdownPos]);

  function openMenu(e: React.MouseEvent) {
    e.stopPropagation();
    if (dropdownPos) { setDropdownPos(null); return; }
    const rect = triggerRef.current!.getBoundingClientRect();
    setDropdownPos({
      top: rect.bottom + 4,
      right: window.innerWidth - rect.right,
    });
  }

  const dropdown = dropdownPos && createPortal(
    <div
      className="row-menu-dropdown"
      style={{ position: "fixed", top: dropdownPos.top, right: dropdownPos.right }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <button
        className="row-menu-item row-menu-item--danger"
        onClick={() => { setDropdownPos(null); onRemove(); }}
      >
        remove from watchlist
      </button>
    </div>,
    document.body
  );

  return (
    <tr className="ticker-row">
      <td className="cell cell--ticker">{ticker}</td>
      <td className="cell cell--price">
        <span className={priceFlashClass}>{tick ? `$${tick.price.toFixed(2)}` : "—"}</span>
      </td>
      <td className="cell cell--num" style={{ color: changeColor }}>
        {tick ? `${up ? "+" : ""}${tick.change.toFixed(2)}` : "—"}
      </td>
      <td className="cell cell--num" style={{ color: changeColor }}>
        {tick ? `${up ? "+" : ""}${tick.changePct.toFixed(3)}%` : "—"}
      </td>
      <td className="cell cell--num" style={{ color: tick?.perf5d != null ? (tick.perf5d >= 0 ? "var(--green)" : "var(--red)") : "var(--fg-muted)" }}>
        {tick?.perf5d != null ? `${tick.perf5d >= 0 ? "+" : ""}${tick.perf5d.toFixed(3)}%` : "—"}
      </td>
      <td className="cell cell--num" style={{ color: tick?.perfYtd != null ? (tick.perfYtd >= 0 ? "var(--green)" : "var(--red)") : "var(--fg-muted)" }}>
        {tick?.perfYtd != null ? `${tick.perfYtd >= 0 ? "+" : ""}${tick.perfYtd.toFixed(3)}%` : "—"}
      </td>
      <td className="cell cell--num cell--muted">
        {tick?.volume != null ? formatVol(tick.volume) : "—"}
      </td>
      <td className="cell cell--action">
        <button
          ref={triggerRef}
          className="row-menu-trigger"
          onClick={openMenu}
          aria-label="row options"
        >
          ⋮
        </button>
        {dropdown}
      </td>
    </tr>
  );
}
