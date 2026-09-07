import { useState, useEffect } from "react";
import { AnalysisBar, type AnalysisOptions } from "./components/Shared";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Performance from "./pages/Performance";
import Benchmark from "./pages/Benchmark";
import Transactions from "./pages/Transactions";
import FxRates from "./pages/FxRates";
import DataSources from "./pages/DataSources";
import AIAssistant from "./pages/AIAssistant";

type Page = "dashboard" | "performance" | "benchmark" | "transactions" | "fx" | "datasources" | "ai";

const NAV: { id: Page; label: string; sub: string; icon: string; badge?: string }[] = [
  { id: "dashboard", label: "대시보드", sub: "자산 현황", icon: "◈" },
  { id: "performance", label: "성과 분석", sub: "손익 분해", icon: "▲" },
  { id: "benchmark", label: "벤치마크", sub: "S&P500 비교", icon: "⊿", badge: "핵심" },
  { id: "transactions", label: "거래·배당", sub: "내역 관리", icon: "↕" },
  { id: "fx", label: "환율", sub: "USD/KRW", icon: "$" },
  { id: "datasources", label: "데이터 연동", sub: "API·CSV", icon: "⊞" },
  { id: "ai", label: "AI 어시스턴트", sub: "진단·Q&A", icon: "✦" },
];

const PAGE_LABELS: Record<Page, string> = {
  dashboard: "대시보드",
  performance: "성과 분석",
  benchmark: "벤치마크 비교",
  transactions: "거래·배당 내역",
  fx: "환율",
  datasources: "데이터 연동",
  ai: "AI 어시스턴트",
};

// Pages where analysis options bar is shown
const ANALYSIS_PAGES: Page[] = ["dashboard", "performance", "benchmark"];

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [user, setUser] = useState("");
  const [checking, setChecking] = useState(true);
  const [page, setPage] = useState<Page>("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [opts, setOpts] = useState<AnalysisOptions>({
    includeDividend: true,
    includeFx: true,
    period: "1Y",
    scope: "total",
    ticker: "",
  });
  const [tickers, setTickers] = useState<{ ticker: string; name: string }[]>([]);

  useEffect(() => {
    fetch("/api/app/me", { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (d && d.ok) { setUser(d.user); setLoggedIn(true); } })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    fetch("/api/app/tickers", { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(j => { if (j) setTickers(j.tickers || []); })
      .catch(() => {});
  }, [loggedIn]);

  const handleLogout = () => {
    fetch("/api/app/logout", { method: "POST", credentials: "include" })
      .finally(() => { setLoggedIn(false); setUser(""); });
  };

  if (checking) return <div className="min-h-full bg-[#0a0d14]" />;
  if (!loggedIn) return <Login onLogin={(u) => { setUser(u); setLoggedIn(true); }} />;

  return (
    <div className="min-h-full bg-[#0a0d14] text-[#e8eaf0] font-['Outfit',sans-serif] flex">
      {/* Sidebar */}
      <aside className={`${sidebarOpen ? "w-56" : "w-14"} flex-shrink-0 bg-[#0d1019] border-r border-white/7 flex flex-col transition-all duration-200 overflow-hidden`}>
        {/* Logo */}
        <div className={`flex items-center gap-3 px-4 h-14 border-b border-white/7 ${!sidebarOpen && "justify-center"}`}>
          <div className="w-7 h-7 rounded bg-[#00d4a1] flex items-center justify-center flex-shrink-0">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
              <path d="M2 10L5 6L8 8L12 3" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          {sidebarOpen && <span className="font-['DM_Serif_Display',serif] text-base tracking-tight whitespace-nowrap">PortfolioAI</span>}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 space-y-0.5 px-2">
          {NAV.map(item => (
            <button key={item.id} onClick={() => setPage(item.id)}
              className={`w-full flex items-center gap-3 px-2.5 py-2.5 rounded-sm text-left transition-colors relative group ${page === item.id ? "bg-white/8 text-[#e8eaf0]" : "text-[#6b7494] hover:text-[#a0a8c0] hover:bg-white/4"}`}>
              <span className={`text-base flex-shrink-0 w-5 text-center ${page === item.id ? "text-[#00d4a1]" : ""}`}>{item.icon}</span>
              {sidebarOpen && (
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium leading-tight flex items-center gap-2">
                    {item.label}
                    {item.badge && <span className="text-[10px] px-1 py-0 rounded bg-[#00d4a1]/15 text-[#00d4a1] font-mono">{item.badge}</span>}
                  </div>
                  <div className="text-xs text-[#6b7494] mt-0.5">{item.sub}</div>
                </div>
              )}
              {page === item.id && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-[#00d4a1] rounded-full" />}
              {/* Tooltip when collapsed */}
              {!sidebarOpen && (
                <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 bg-[#161c2d] border border-white/10 rounded px-2.5 py-1.5 text-xs text-[#e8eaf0] whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none z-20 transition-opacity">
                  {item.label}
                </div>
              )}
            </button>
          ))}
        </nav>

        {/* User + logout */}
        <div className={`border-t border-white/7 px-3 py-4 ${!sidebarOpen && "flex justify-center"}`}>
          {sidebarOpen ? (
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-full bg-[#00d4a1]/20 flex items-center justify-center flex-shrink-0">
                <span className="text-xs text-[#00d4a1] font-mono">{(user[0] || "U").toUpperCase()}</span>
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-[#e8eaf0] truncate">{user || "사용자"}</div>
                <button onClick={handleLogout} className="text-xs text-[#6b7494] hover:text-[#ff5c6a] transition-colors font-mono">로그아웃</button>
              </div>
            </div>
          ) : (
            <div className="w-7 h-7 rounded-full bg-[#00d4a1]/20 flex items-center justify-center cursor-pointer" onClick={handleLogout}>
              <span className="text-xs text-[#00d4a1] font-mono">{(user[0] || "U").toUpperCase()}</span>
            </div>
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-14 border-b border-white/7 flex items-center gap-4 px-6 flex-shrink-0 bg-[#0a0d14]/80 backdrop-blur-sm sticky top-0 z-10">
          <button onClick={() => setSidebarOpen(o => !o)} className="text-[#6b7494] hover:text-[#e8eaf0] transition-colors text-lg">
            ☰
          </button>
          <div className="flex-1">
            <h1 className="text-sm font-medium text-[#e8eaf0]">{PAGE_LABELS[page]}</h1>
          </div>
          {/* Report buttons - I1/I2 */}
          <div className="flex items-center gap-2">
            <button className="text-xs font-mono px-3 py-1.5 border border-white/10 rounded-sm text-[#6b7494] hover:text-[#a0a8c0] hover:border-white/20 transition-colors">
              Excel 내보내기 (I1)
            </button>
            <button className="text-xs font-mono px-3 py-1.5 border border-white/10 rounded-sm text-[#6b7494] hover:text-[#a0a8c0] hover:border-white/20 transition-colors">
              PDF 리포트 (I2)
            </button>
            <div className="w-2 h-2 rounded-full bg-[#00d4a1] animate-pulse ml-1" />
          </div>
        </header>

        {/* Analysis bar (G) — only on analysis pages */}
        {ANALYSIS_PAGES.includes(page) && (
          <div className="px-6 pt-4">
            <AnalysisBar opts={opts} setOpts={setOpts} tickers={tickers} showPeriod={page === "dashboard" || page === "benchmark"} />
          </div>
        )}

        {/* Page content */}
        <main className="flex-1 overflow-y-auto px-6 py-6">
          {page === "dashboard" && <Dashboard opts={opts} onTickers={setTickers} />}
          {page === "performance" && <Performance opts={opts} onTickers={setTickers} />}
          {page === "benchmark" && <Benchmark opts={opts} onTickers={setTickers} />}
          {page === "transactions" && <Transactions />}
          {page === "fx" && <FxRates />}
          {page === "datasources" && <DataSources />}
          {page === "ai" && <AIAssistant />}
        </main>
      </div>
    </div>
  );
}
