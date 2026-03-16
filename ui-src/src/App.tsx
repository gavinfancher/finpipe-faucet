import { useState, useEffect } from "react";
import Login from "./components/Login";
import Dashboard from "./components/Dashboard";
import { getCurrentUsername } from "./store/userStore";

type View = "login" | "dashboard";

export default function App() {
  const [view, setView] = useState<View>("login");
  const [username, setUsername] = useState<string>("");

  useEffect(() => {
    const existing = getCurrentUsername();
    if (existing) {
      setUsername(existing);
      setView("dashboard");
    }
  }, []);

  if (view === "login") {
    return (
      <Login
        onLogin={(name) => {
          setUsername(name);
          setView("dashboard");
        }}
      />
    );
  }

  return (
    <Dashboard
      username={username}
      onLogout={() => {
        setUsername("");
        setView("login");
      }}
    />
  );
}
