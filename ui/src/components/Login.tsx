import { useState, type FormEvent } from "react";
import { setCurrentUsername } from "../store/userStore";

interface Props {
  onLogin: (username: string) => void;
}

export default function Login({ onLogin }: Props) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const name = value.trim().toLowerCase();
    if (!name) {
      setError("username cannot be empty.");
      return;
    }
    if (!/^[a-zA-Z0-9_-]{1,32}$/.test(name)) {
      setError("only letters, numbers, underscores, and hyphens allowed (max 32 chars).");
      return;
    }
    setCurrentUsername(name);
    onLogin(name);
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <span className="logo-text">finpipe</span>
        </div>
        <p className="login-subtitle">real-time market data</p>
        <form onSubmit={handleSubmit} className="login-form">
          <label htmlFor="username" className="field-label">username</label>
          <input
            id="username"
            type="text"
            className="text-input"
            placeholder="e.g. trader_joe"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError("");
            }}
            autoFocus
            autoComplete="username"
          />
          {error && <p className="field-error">{error}</p>}
          <button type="submit" className="btn-primary">
            enter
          </button>
        </form>
      </div>
    </div>
  );
}
