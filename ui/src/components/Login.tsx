import { useState, type FormEvent } from "react";
import { setCurrentUsername, setToken } from "../store/userStore";

const API = `http://${window.location.hostname}:8080`;

interface Props {
  onLogin: (username: string, token: string) => void;
}

type Mode = "login" | "register";

export default function Login({ onLogin }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function resetForm() {
    setUsername("");
    setPassword("");
    setConfirm("");
    setError("");
  }

  function switchMode(m: Mode) {
    setMode(m);
    resetForm();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");

    if (!username.trim() || !password) return;

    if (mode === "register") {
      if (!/^[a-zA-Z0-9_-]{1,32}$/.test(username)) {
        setError("only letters, numbers, underscores, and hyphens (max 32 chars).");
        return;
      }
      if (password.length < 6) {
        setError("password must be at least 6 characters.");
        return;
      }
      if (password !== confirm) {
        setError("passwords do not match.");
        return;
      }
    }

    setLoading(true);
    try {
      const res = await fetch(`${API}/external/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim().toLowerCase(), password }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail ?? "something went wrong.");
        return;
      }
      setCurrentUsername(data.access_token ? username.trim().toLowerCase() : "");
      setToken(data.access_token);
      onLogin(username.trim().toLowerCase(), data.access_token);
    } catch {
      setError("could not reach server.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <span className="logo-text">finpipe</span>
        </div>
        <p className="login-subtitle">real-time market data</p>

        <div className="login-tabs">
          <button
            className={`login-tab ${mode === "login" ? "login-tab--active" : ""}`}
            onClick={() => switchMode("login")}
            type="button"
          >
            sign in
          </button>
          <button
            className={`login-tab ${mode === "register" ? "login-tab--active" : ""}`}
            onClick={() => switchMode("register")}
            type="button"
          >
            register
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="username" className="field-label">username</label>
          <input
            id="username"
            type="text"
            className="text-input"
            placeholder="e.g. trader_joe"
            value={username}
            onChange={(e) => { setUsername(e.target.value); setError(""); }}
            autoFocus
            autoComplete="off"
          />

          <label htmlFor="password" className="field-label">password</label>
          <input
            id="password"
            type="password"
            className="text-input"
            placeholder="••••••••"
            value={password}
            onChange={(e) => { setPassword(e.target.value); setError(""); }}
            autoComplete="off"
          />

          {mode === "register" && (
            <>
              <label htmlFor="confirm" className="field-label">confirm password</label>
              <input
                id="confirm"
                type="password"
                className="text-input"
                placeholder="••••••••"
                value={confirm}
                onChange={(e) => { setConfirm(e.target.value); setError(""); }}
                autoComplete="off"
              />
            </>
          )}

          {error && <p className="field-error">{error}</p>}

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "…" : mode === "login" ? "sign in" : "create account"}
          </button>
        </form>
      </div>
    </div>
  );
}
