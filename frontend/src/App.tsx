import { useState } from "react";
import { UploadPage } from "./pages/UploadPage";
import { QAPage } from "./pages/QAPage";
import { SummaryPage } from "./pages/SummaryPage";
import "./App.css";

type Tab = "upload" | "qa" | "summary";

const TABS: { id: Tab; label: string }[] = [
  { id: "upload", label: "Upload" },
  { id: "qa", label: "Q&A" },
  { id: "summary", label: "Summary" },
];

function App() {
  const [tab, setTab] = useState<Tab>("upload");

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Construction RAG</h1>
        <nav className="tab-nav">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab-button ${tab === t.id ? "tab-active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main">
        {tab === "upload" && <UploadPage />}
        {tab === "qa" && <QAPage />}
        {tab === "summary" && <SummaryPage />}
      </main>
    </div>
  );
}

export default App;
