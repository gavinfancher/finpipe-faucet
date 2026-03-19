import { useState, useEffect, useRef, useCallback, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useStockWebSocket } from "../hooks/useStockWebSocket";
import { useMarketStatus } from "../hooks/useMarketStatus";
import { clearCurrentUsername } from "../store/userStore";
import TickerRow, { type WLColKey } from "./TickerRow";
import PositionsTab from "./PositionsTab";
import Logo from "./Logo";

interface WLCol { key: WLColKey; label: string; visible: boolean; sortable: boolean; }

const DEFAULT_WL_COLS: WLCol[] = [
  { key: "price",     label: "price",   visible: true, sortable: false },
  { key: "change",    label: "change",  visible: true, sortable: false },
  { key: "changePct", label: "chg %",   visible: true, sortable: true  },
  { key: "perf5d",    label: "5d %",    visible: true, sortable: true  },
  { key: "perf1m",    label: "1m %",    visible: true, sortable: true  },
  { key: "perf3m",    label: "3m %",    visible: true, sortable: true  },
  { key: "perf6m",    label: "6m %",    visible: true, sortable: true  },
  { key: "perfYtd",   label: "ytd %",   visible: true, sortable: true  },
  { key: "perf1y",    label: "1y %",    visible: true, sortable: true  },
  { key: "perf3y",    label: "3y %",    visible: true, sortable: true  },
  { key: "volume",    label: "volume",  visible: true, sortable: false },
];

const WL_LS_KEY = "watchlist-columns";

function loadWLCols(): WLCol[] {
  try {
    const saved = localStorage.getItem(WL_LS_KEY);
    if (saved) {
      const parsed: WLCol[] = JSON.parse(saved);
      const keys = new Set(parsed.map((c) => c.key));
      return [...parsed, ...DEFAULT_WL_COLS.filter((c) => !keys.has(c.key))];
    }
  } catch {}
  return DEFAULT_WL_COLS;
}

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
  const [activeTab, setActiveTab] = useState<"watchlist" | "positions">("watchlist");
  const [sortKey, setSortKey] = useState("ticker");
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [wlCols, setWLCols] = useState<WLCol[]>(loadWLCols);
  const [showWLPanel, setShowWLPanel] = useState(false);
  const [wlPanelPos, setWLPanelPos] = useState<{ top: number; right: number } | null>(null);
  const wlColBtnRef = useRef<HTMLButtonElement>(null);
  const [wlDragKey, setWLDragKey] = useState<WLColKey | null>(null);
  const [wlDragOverKey, setWLDragOverKey] = useState<WLColKey | null>(null);
  // menu
  const menuRef = useRef<HTMLButtonElement>(null);
  const [menuPos, setMenuPos] = useState<{ top: number; right: number } | null>(null);

  // api key modal
  const [showApiKey, setShowApiKey] = useState(false);
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [apiKeyLoading, setApiKeyLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const fetchUserTickers = useCallback(async () => {
    const res = await fetch(`${API}/external/tickers/list`, { headers: authHeader });
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
    await fetch(`${API}/external/tickers/${ticker}`, { method: "POST", headers: authHeader });
    await fetchUserTickers();
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

  // WL column panel
  useEffect(() => {
    if (!showWLPanel) return;
    function close() { setShowWLPanel(false); }
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [showWLPanel]);

  function saveWLCols(next: WLCol[]) { localStorage.setItem(WL_LS_KEY, JSON.stringify(next)); setWLCols(next); }
  function toggleWLCol(key: WLColKey) { saveWLCols(wlCols.map((c) => c.key === key ? { ...c, visible: !c.visible } : c)); }
  function onWLDragStart(key: WLColKey) { setWLDragKey(key); }
  function onWLDragOver(e: React.DragEvent, key: WLColKey) { e.preventDefault(); setWLDragOverKey(key); }
  function onWLDrop(targetKey: WLColKey) {
    if (!wlDragKey || wlDragKey === targetKey) { setWLDragKey(null); setWLDragOverKey(null); return; }
    const next = [...wlCols];
    const from = next.findIndex((c) => c.key === wlDragKey);
    const to = next.findIndex((c) => c.key === targetKey);
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    saveWLCols(next);
    setWLDragKey(null); setWLDragOverKey(null);
  }
  function openWLPanel(e: React.MouseEvent) {
    e.stopPropagation();
    if (showWLPanel) { setShowWLPanel(false); return; }
    const rect = wlColBtnRef.current!.getBoundingClientRect();
    setWLPanelPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right });
    setShowWLPanel(true);
  }

  function toggleSort(key: string) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(key === "ticker" ? 1 : -1); }
  }

  const displayList = userTickers.slice().sort((a, b) => {
    if (sortKey === "ticker") return a.localeCompare(b) * sortDir;
    const va = (ticks[a] as Record<string, number | undefined>)?.[sortKey] ?? -Infinity;
    const vb = (ticks[b] as Record<string, number | undefined>)?.[sortKey] ?? -Infinity;
    return (va - vb) * sortDir;
  });

  const visibleWLCols = wlCols.filter((c) => c.visible);
  const noData = displayList.length === 0;

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="topbar">
        <div className="topbar-left">
          <Logo />
          <span className="logo-text">finpipe faucet</span>
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

      {/* Tab bar */}
      <div className="tab-bar">
        <button className={`tab${activeTab === "watchlist" ? " tab--active" : ""}`} onClick={() => setActiveTab("watchlist")}>watchlist</button>
        <button className={`tab${activeTab === "positions" ? " tab--active" : ""}`} onClick={() => setActiveTab("positions")}>positions</button>
      </div>

      {/* Main content */}
      <main className="main-content">
        {activeTab === "positions" ? (
          <PositionsTab token={token} ticks={ticks} />
        ) : noData ? (
          <div className="empty-state">
            <p className="empty-state__icon">⏳</p>
            <p className="empty-state__title">waiting for data…</p>
          </div>
        ) : (
          <div className="table-wrapper">
            <table className="stock-table">
              <colgroup>
                <col style={{ width: "70px" }} />
                {visibleWLCols.map((c) => <col key={c.key} style={{ width: "90px" }} />)}
                <col style={{ width: "36px" }} />
              </colgroup>
              <thead>
                <tr>
                  <th className={`th th--sortable${sortKey === "ticker" ? " th--active" : ""}`} onClick={() => toggleSort("ticker")}>
                    ticker {sortKey === "ticker" && sortDir === -1 ? "↓" : ""}
                  </th>
                  {visibleWLCols.map((c) => (
                    <th
                      key={c.key}
                      className={`th th--right${c.sortable ? " th--sortable" : ""}${sortKey === c.key ? " th--active" : ""}`}
                      onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                    >
                      {c.label} {c.sortable && sortKey === c.key ? (sortDir === 1 ? "↑" : "↓") : ""}
                    </th>
                  ))}
                  <th className="th">
                    <button ref={wlColBtnRef} className="col-config-btn" onClick={openWLPanel} title="configure columns">
                      <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor"><path d="M12.146.146a.5.5 0 0 1 .708 0l3 3a.5.5 0 0 1 0 .708l-10 10a.5.5 0 0 1-.168.11l-5 2a.5.5 0 0 1-.65-.65l2-5a.5.5 0 0 1 .11-.168l10-10zM11.207 2.5 13.5 4.793 14.793 3.5 12.5 1.207zm1.586 3L10.5 3.207 4 9.707V10h.5a.5.5 0 0 1 .5.5v.5h.5a.5.5 0 0 1 .5.5v.5h.293zm-9.761 5.175-.106.106-1.528 3.821 3.821-1.528.106-.106A.5.5 0 0 1 5 12.5V12h-.5a.5.5 0 0 1-.5-.5V11h-.5a.5.5 0 0 1-.468-.325z"/></svg>
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
              {displayList.map((ticker) => (
                <TickerRow
                  key={ticker}
                  ticker={ticker}
                  tick={ticks[ticker]}
                  prevPrice={prevPrices.current[ticker]}
                  visibleCols={visibleWLCols.map((c) => c.key)}
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

      {/* WL column panel */}
      {showWLPanel && wlPanelPos && createPortal(
        <div className="col-panel" style={{ position: "fixed", top: wlPanelPos.top, right: wlPanelPos.right }} onPointerDown={(e) => e.stopPropagation()}>
          <div className="col-panel__header">columns</div>
          {wlCols.map((c) => (
            <div key={c.key} className={`col-panel__row${wlDragOverKey === c.key ? " col-panel__row--over" : ""}`}
              onDragOver={(e) => onWLDragOver(e, c.key)} onDrop={() => onWLDrop(c.key)}>
              <span className="col-panel__drag" draggable onDragStart={() => onWLDragStart(c.key)} onDragEnd={() => { setWLDragKey(null); setWLDragOverKey(null); }}>⠿</span>
              <span className="col-panel__label">{c.label}</span>
              <input type="checkbox" className="col-panel__check" checked={c.visible} onChange={() => toggleWLCol(c.key)} />
            </div>
          ))}
          <button className="col-panel__revert" onClick={() => { saveWLCols(DEFAULT_WL_COLS); setShowWLPanel(false); }}>reset to default</button>
        </div>,
        document.body
      )}

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
