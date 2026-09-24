import { useState } from "react";

import Coach from "./pages/Coach";
import Dashboard from "./pages/Dashboard";
import Log from "./pages/Log";
import Settings from "./pages/Settings";
import Trends from "./pages/Trends";

const TABS = ["Dashboard", "Log", "Trends", "Coach", "Settings"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const [tab, setTab] = useState<Tab>("Dashboard");

  return (
    <div className="app">
      <header>
        <h1>Aura</h1>
        <nav>
          {TABS.map((name) => (
            <button
              key={name}
              className={name === tab ? "active" : ""}
              onClick={() => setTab(name)}
            >
              {name}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === "Dashboard" && <Dashboard onStart={() => setTab("Log")} />}
        {tab === "Log" && <Log />}
        {tab === "Trends" && <Trends />}
        {tab === "Coach" && <Coach />}
        {tab === "Settings" && <Settings />}
      </main>
    </div>
  );
}
