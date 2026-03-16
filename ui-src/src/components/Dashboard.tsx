import { useState, useEffect, useRef, type KeyboardEvent } from "react";
import { useStockWebSocket } from "../hooks/useStockWebSocket";
import { useMarketStatus } from "../hooks/useMarketStatus";
import { clearCurrentUsername } from "../store/userStore";
import TickerRow from "./TickerRow";

interface Props {
  username: string;
  onLogout: () => void;
}

const STATUS_LABEL: Record<string, string> = {
  connecting: "Connecting…",
  connected: "Live",
  disconnected: "Reconnecting…",
};

const STATUS_DOT: Record<string, string> = {
  connecting: "dot--yellow",
  connected: "dot--green",
  disconnected: "dot--red",
};

const API = `http://${window.location.hostname}:8080`;

export default function Dashboard({ username, onLogout }: Props) {
  const { ticks, availableTickers, status } = useStockWebSocket();
  const market = useMarketStatus();
  const prevPrices = useRef<Record<string, number>>({});
  const [, forceUpdate] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchFeedback, setSearchFeedback] = useState<{ msg: string; ok: boolean } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Press / anywhere to focus the search bar
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.key !== "/") return;
      const active = document.activeElement;
      if (active === searchRef.current) return;
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      searchRef.current?.focus();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function showFeedback(msg: string, ok: boolean) {
    setSearchFeedback({ msg, ok });
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    feedbackTimer.current = setTimeout(() => setSearchFeedback(null), 2000);
  }

  async function handleSearchKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setSearchQuery("");
      searchRef.current?.blur();
      return;
    }
    if (e.key !== "Enter") return;
    const ticker = searchQuery.trim().toUpperCase();
    if (!ticker) return;

    if (!/^[A-Z]{1,5}$/.test(ticker)) {
      showFeedback(`"${ticker}" invalid ticker`, false);
      return;
    }
    if (availableTickers.includes(ticker)) {
      showFeedback(`${ticker} already subscribed`, false);
      setSearchQuery("");
      return;
    }
    await fetch(`${API}/subscriptions/${ticker}`, { method: "PUT" });
    showFeedback(`${ticker} added`, true);
    setSearchQuery("");
  }

  // Track previous prices for flash animation
  useEffect(() => {
    forceUpdate((n) => n + 1);
    const t = setTimeout(() => {
      for (const [k, v] of Object.entries(ticks)) {
        prevPrices.current[k] = v.price;
      }
      forceUpdate((n) => n + 1);
    }, 300);
    return () => clearTimeout(t);
  }, [ticks]);

  function handleLogout() {
    clearCurrentUsername();
    onLogout();
  }

  const displayList = availableTickers.slice().sort();
  const noData = displayList.length === 0;

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="topbar">
        <div className="topbar-left">
          <span className="logo-text">finpipe</span>
        </div>
        <div className="topbar-center">
          <div className="search-wrap">
            <span className="search-slash">/</span>
            <input
              ref={searchRef}
              className="search-input"
              type="text"
              placeholder="Add ticker…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value.replace(/^\//, ""))}
              onKeyDown={handleSearchKeyDown}
              autoComplete="off"
              spellCheck={false}
            />
            {searchFeedback && (
              <span className={`search-feedback ${searchFeedback.ok ? "search-feedback--ok" : "search-feedback--err"}`}>
                {searchFeedback.msg}
              </span>
            )}
          </div>
        </div>
        <div className="topbar-status">
          {market.icon
            ? <span className="market-icon">{market.icon}</span>
            : <span className={`status-dot ${market.dotClass}`} />}
          <span className="status-label">{market.label}</span>
        </div>
        <div className="topbar-right">
          <span className="username-badge">{username}</span>
          <button className="btn-ghost btn-logout" onClick={handleLogout}>
            sign out
          </button>
        </div>
      </header>

      {/* Main content */}
      <main className="main-content">
        {noData ? (
          <div className="empty-state">
            <p className="empty-state__icon">⏳</p>
            <p className="empty-state__title">waiting for data…</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table className="stock-table">
              <thead>
                <tr>
                  <th className="th">ticker</th>
                  <th className="th th--right">price</th>
                  <th className="th th--right">change</th>
                  <th className="th th--right">change %</th>
                  <th className="th th--right">volume</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {displayList.map((ticker) => (
                  <TickerRow
                    key={ticker}
                    ticker={ticker}
                    tick={ticks[ticker]}
                    prevPrice={prevPrices.current[ticker]}
                    onRemove={() => fetch(`${API}/subscriptions/${ticker}`, { method: "DELETE" })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* Bottom status bar */}
      <footer className="statusbar">
        <span className={`status-dot ${STATUS_DOT[status]}`} />
        <span className="statusbar-label">{STATUS_LABEL[status].toLowerCase()}</span>
        <span className="statusbar-sep">·</span>
        <span className="statusbar-label">ws://{window.location.hostname}:8080</span>
      </footer>
    </div>
  );
}
