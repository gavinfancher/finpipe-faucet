import { useState, useEffect, useRef, useCallback, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useStockWebSocket } from "../hooks/useStockWebSocket";
import { useMarketStatus } from "../hooks/useMarketStatus";
import { clearCurrentUsername } from "../store/userStore";
import TickerRow from "./TickerRow";

interface Props {
  username: string;
  token: string;
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

export default function Dashboard({ username, token, onLogout }: Props) {
  const { ticks, status } = useStockWebSocket(token);
  const authHeader = { Authorization: `Bearer ${token}` };
  const market = useMarketStatus();
  const prevPrices = useRef<Record<string, number>>({});
  const [, forceUpdate] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchFeedback, setSearchFeedback] = useState<{ msg: string; ok: boolean } | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [userTickers, setUserTickers] = useState<string[]>([]);

  // menu
  const menuRef = useRef<HTMLButtonElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);

  // api key modal
  const [showApiKey, setShowApiKey] = useState(false);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const fetchUserTickers = useCallback(async () => {
    const res = await fetch(`${API}/external/tickers`, { headers: authHeader });
    const data = await res.json();
    setUserTickers(data.tickers ?? []);
  }, [token]);

  useEffect(() => {
    fetchUserTickers();
    const id = setInterval(fetchUserTickers, 5000);
    return () => clearInterval(id);
  }, [fetchUserTickers]);

  // close menu on outside click/scroll
  useEffect(() => {
    if (!menuPos) return;
    function close() { setMenuPos(null); }
    document.addEventListener("pointerdown", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [menuPos]);

  function openMenu(e: React.MouseEvent) {
    e.stopPropagation();
    if (menuPos) { setMenuPos(null); return; }
    const rect = menuRef.current!.getBoundingClientRect();
    setMenuPos({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
  }

  async function generateApiKey() {
    setApiKeyLoading(true);
    try {
      const res = await fetch(`${API}/external/api-key`, {
        method: "POST",
        headers: authHeader,
      });
      const data = await res.json();
      setApiKey(data.api_key ?? null);
    } finally {
      setApiKeyLoading(false);
    }
  }

  function copyKey() {
    if (!apiKey) return;
    navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function openApiKeyModal() {
    setMenuPos(null);
    setApiKey(null);
    setCopied(false);
    setShowApiKey(true);
  }

  // press / to focus search
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
    if (userTickers.includes(ticker)) {
      showFeedback(`${ticker} already subscribed`, false);
      setSearchQuery("");
      return;
    }
    await fetch(`${API}/external/tickers/${ticker}`, { method: "PUT", headers: authHeader });
    showFeedback(`${ticker} added`, true);
    setSearchQuery("");
  }

  // track previous prices for flash animation
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

  const lastTickAt = useRef<number | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (status === "connected") lastTickAt.current = Date.now();
  }, [status]);

  useEffect(() => {
    if (Object.keys(ticks).length > 0) lastTickAt.current = Date.now();
  }, [ticks]);

  useEffect(() => {
    const id = setInterval(() => {
      if (lastTickAt.current === null) { setElapsed(null); return; }
      setElapsed(Math.floor((Date.now() - lastTickAt.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  function formatMmSs(s: number): string {
    const mm = Math.floor(s / 60).toString().padStart(2, "0");
    const ss = (s % 60).toString().padStart(2, "0");
    return `${mm}:${ss}`;
  }

  const displayList = userTickers.slice().sort();
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
              placeholder="add ticker…"
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
          <span className={`status-dot ${market.dotClass}`} />
          <span className="status-label">{market.label}</span>
        </div>
        <div className="topbar-right">
          <span className="username-badge">{username}</span>
          <button ref={menuRef} className="hamburger" onClick={openMenu} aria-label="menu" data-1p-ignore>
            <span /><span /><span />
          </button>
        </div>
      </header>

      {/* Hamburger dropdown */}
      {menuPos && createPortal(
        <div
          className="user-menu-dropdown"
          style={{ position: "fixed", top: menuPos.top, right: menuPos.right }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <button className="user-menu-item" onClick={openApiKeyModal}>
            api key
          </button>
          <button className="user-menu-item user-menu-item--danger" onClick={handleLogout}>
            sign out
          </button>
        </div>,
        document.body
      )}

      {/* API key modal */}
      {showApiKey && createPortal(
        <div className="modal-overlay" onClick={() => setShowApiKey(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} data-1p-ignore>
            <div className="modal-header">
              <h2 className="modal-title">api key</h2>
              <button className="btn-icon" onClick={() => setShowApiKey(false)}>✕</button>
            </div>

            <div className="apikey-body">
              {apiKey ? (
                <>
                  <p className="apikey-note">copy your key now — it won't be shown again.</p>
                  <div className="apikey-display">
                    <code className="apikey-value">{apiKey}</code>
                    <button className="btn-ghost btn-ghost--sm" onClick={copyKey}>
                      {copied ? "copied!" : "copy"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <p className="apikey-note">generate an api key to update your watchlist programmatically. generating a new key invalidates the previous one.</p>
                  <button className="btn-primary" onClick={generateApiKey} disabled={apiKeyLoading}>
                    {apiKeyLoading ? "generating…" : "generate key"}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}

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
                    onRemove={async () => {
                      await fetch(`${API}/external/tickers/${ticker}`, { method: "DELETE", headers: authHeader });
                      await fetchUserTickers();
                    }}
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
        {market.session !== "market open" && (
          <>
            <span className="statusbar-sep">·</span>
            <span className="statusbar-label statusbar-label--muted">
              {elapsed === null || elapsed < 2
                ? "updated --:-- ago"
                : `updated ${formatMmSs(elapsed)} ago`}
            </span>
          </>
        )}
      </footer>
    </div>
  );
}
