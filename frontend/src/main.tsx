import React from "react";
import ReactDOM from "react-dom/client";
import { NavLink, Route, BrowserRouter as Router, Routes } from "react-router-dom";
import { BookOpen, FileText, Folder, Home, Languages, Repeat, ScrollText } from "lucide-react";
import { Dashboard } from "./pages/Dashboard";
import { Translate } from "./pages/Translate";
import { Convert } from "./pages/Convert";
import { Templates } from "./pages/Templates";
import { Glossary } from "./pages/Glossary";
import { Reviews } from "./pages/Reviews";
import "./styles.css";

const nav = [
  { to: "/", label: "总览", icon: Home },
  { to: "/translate", label: "文档翻译", icon: Languages },
  { to: "/convert", label: "格式转换", icon: Repeat },
  { to: "/templates", label: "模板", icon: Folder },
  { to: "/glossary", label: "术语表", icon: BookOpen },
  { to: "/reviews", label: "审校记录", icon: ScrollText }
];

function App() {
  return (
    <Router>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <FileText size={26} />
            <div>
              <strong>VoltDocs</strong>
              <span>Web V0.1.1</span>
            </div>
          </div>
          <nav>
            {nav.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                  <Icon size={18} />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/translate" element={<Translate />} />
            <Route path="/convert" element={<Convert />} />
            <Route path="/templates" element={<Templates />} />
            <Route path="/glossary" element={<Glossary />} />
            <Route path="/reviews" element={<Reviews />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

