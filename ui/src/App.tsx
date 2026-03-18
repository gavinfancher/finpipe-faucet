import { useState, useEffect } from "react";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";
import { getCurrentUsername, getToken, clearCurrentUsername, clearToken } from "./store/userStore";

type View = "login" | "dashboard";

export default function App() {
  const [view, setView] = useState<View>("login");
  const [username, setUsername] = useState<string>("");
  const [token, setToken] = useState<string>("");

  useEffect(() => {
    const existingUser = getCurrentUsername();
    const existingToken = getToken();
    if (existingUser && existingToken) {
      setUsername(existingUser);
      setToken(existingToken);
      setView("dashboard");
    }
  }, []);

  if (view === "login") {
    return (
      <Login
        onLogin={(name, tok) => {
          setUsername(name);
          setToken(tok);
          setView("dashboard");
        }}
      />
    );
  }

  return (
    <Dashboard
      username={username}
      token={token}
      onLogout={() => {
        clearCurrentUsername();
        clearToken();
        setUsername("");
        setToken("");
        setView("login");
      }}
    />
  );
}
