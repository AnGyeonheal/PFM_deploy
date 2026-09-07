import { useState, useEffect } from "react";
import { AnalysisBar, type AnalysisOptions } from "./components/Shared";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Verify from "./pages/Verify";
import Dashboard from "./pages/Dashboard";
import Performance from "./pages/Performance";
import Benchmark from "./pages/Benchmark";
import FxRates from "./pages/FxRates";
import AIAssistant from "./pages/AIAssistant";

type Phase = "onboard" | "verify" | "analysis";
type Page = "dashboard" | "performance" | "benchmark" | "fx" | "ai";

const NAV: { id: Page; label: string; sub: string; icon: string; badge?: string }[] = [
  { id: "dashboard", label: "대시보드", sub: "자산 현황", icon: "◈" },
  { id: "performance", label: "성과 분석", sub: "손익 분해", icon: "▲" },
  { id: "benchmark", label: "벤치마크", sub: "S&P500 비교", icon: "⊿", badge: "핵심" },
  { id: "fx", label: "환율", sub: "USD/KRW", icon: "$" },
  { id: "ai", label: "AI 진단", sub: "진단·Q&A", icon: "✦" },
];
const PAGE_LABELS: Record<Page, string> = {
  dashboard: "대시보드", performance: "성과 분석", benchmark: "벤치마크 비교", fx: "환율", ai: "AI 진단",
};
const ANALYSIS_PAGES: Page[] = ["dashboard", "performance", "benchmark"];
const STEPS: { id: Phase; label: string }[] = [
  { id: "onboard", label: "데이터 준비" },
  { id: "verify", label: "검증·수정" },
  { id: "analysis", label: "분석" },
];

const Logo = () => (
  <div className="w-7 h-7 rounded bg-[#00d4a1] flex items-center justify-center flex-shrink-0">
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
      <path d="M2 10L5 6L8 8L12 3" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  </div>
);

export default function App() {
  const [loggedIn, setLoggedIn] = useState(false);
  const [user, setUser] = useState("");
  const [checking, setChecking] = useState(true);
  const [phase, setPhase] = useState<Phase>("onboard");
  const [page, setPage] = useState<Page>("dashboard");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [opts, setOpts] = useState<AnalysisOptions>({ includeDividend: true, includeFx: true, period: "1Y", scope: "total", ticker: "" });
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
  }, [loggedIn, phase]);

  const handleLogout = () => {
    fetch("/api/app/logout", { method: "POST", credentials: "include" })
      .finally(() => { setLoggedIn(false); setUser(""); setPhase("onboard"); setPage("dashboard"); });
  };

  if (checking) return <div className="min-h-full bg-[#0a0d14]" />;
  if (!loggedIn) return <Login onLogin={(u) => { setUser(u); setLoggedIn(true); setPhase("onboard"); }} />;

  const StepHeader = () => {
    const cur = STEPS.findIndex(s => s.id === phase);
    return (
      <header className="h-14 border-b border-white/7 flex items-center gap-4 px-6 flex-shrink-0 bg-[#0d1019]">
        <Logo />
        <span className="font-['DM_Serif_Display',serif] text-base whitespace-nowrap">PortfolioAI</span>
        <div className="flex items-center gap-2 ml-4 flex-wrap">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex items-center gap-2">
              <span className={`text-xs font-mono px-2 py-1 rounded-sm ${phase === s.id ? "bg-[#00d4a1]/15 text-[#00d4a1]" : cur > i ? "text-[#00d4a1]" : "text-[#6b7494]"}`}>
                {i + 1}. {s.label}
              </span>
              {i < STEPS.length - 1 && <span className="text-[#6b7494] text-xs">→</span>}
            </div>
          ))}
        </div>
        <div className="flex-1" />
        <div className="text-xs text-[#a0a8c0]">{user}</div>
        <button onClick={handleLogout} className="text-xs text-[#6b7494] hover:text-[#ff5c6a] font-mono">로그아웃</button>
      </header>
    );
  };

  if (phase === "onboard" || phase === "verify") {
    return (
      <div className="min-h-full bg-[#0a0d14] text-[#e8eaf0] font-['Outfit',sans-serif] flex flex-col">
        <StepHeader />
        <main className="flex-1 overflow-y-auto px-6 py-8">
          {phase === "onboard"
            ? <Onboarding onDone={() => setPhase("verify")} />
            : <Verify onDone={() => setPhase("analysis")} onBack={() => setPhase("onboard")} />}
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-[#0a0d14] text-[#e8eaf0] font-['Outfit',sans-serif] flex">
      <aside className={`${sidebarOpen ? "w-56" : "w-14"} flex-shrink-0 bg-[#0d1019] border-r border-white/7 flex flex-col transition-all duration-200 overflow-hidden`}>
        <div className={`flex items-center gap-3 px-4 h-14 border-b border-white/7 ${!sidebarOpen && "justify-center"}`}>
          <Logo />
          {sidebarOpen && <span className="font-['DM_Serif_Display',serif] text-base tracking-tight whitespace-nowrap">PortfolioAI</span>}
        </div>
        <nav className="flex-1 py-4 space-y-0.5 px-2">
          {NAV.map(item => (
            <button key={item.id} onClick={() => setPage(item.id)}
              className={`w-full flex items-center gap-3 px-2.5 py-2.5 rounded-sm text-left transition-colors relative ${page === item.id ? "bg-white/8 text-[#e8eaf0]" : "text-[#6b7494] hover:text-[#a0a8c0] hover:bg-white/4"}`}>
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
            </button>
          ))}
        </nav>
        <div className="px-2 pb-2 border-t border-white/7 pt-2">
          <button onClick={() => setPhase("onboard")}
            className="w-full flex items-center gap-3 px-2.5 py-2.5 rounded-sm text-left text-[#6b7494] hover:text-[#a0a8c0] hover:bg-white/4 transition-colors">
            <span className="text-base w-5 text-center">⚙</span>
            {sidebarOpen && <div className="text-sm font-medium">데이터 관리</div>}
          </button>
        </div>
        <div className={`border-t border-white/7 px-3 py-4 ${!sidebarOpen && "flex justify-center"}`}>
          {sidebarOpen ? (
            <div className="flex items-center gap-3">
              <div className="w-7 h-7 rounded-full bg-[#00d4a1]/20 flex items-center justify-center flex-shrink-0"><span className="text-xs text-[#00d4a1] font-mono">{(user[0] || "U").toUpperCase()}</span></div>
              <div className="flex-1 min-w-0"><div className="text-xs text-[#e8eaf0] truncate">{user}</div><button onClick={handleLogout} className="text-xs text-[#6b7494] hover:text-[#ff5c6a] transition-colors font-mono">로그아웃</button></div>
            </div>
          ) : (
            <div className="w-7 h-7 rounded-full bg-[#00d4a1]/20 flex items-center justify-center cursor-pointer" onClick={handleLogout}><span className="text-xs text-[#00d4a1] font-mono">{(user[0] || "U").toUpperCase()}</span></div>
          )}
        </div>
      </aside>
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-white/7 flex items-center gap-4 px-6 flex-shrink-0 bg-[#0a0d14]/80 backdrop-blur-sm sticky top-0 z-10">
          <button onClick={() => setSidebarOpen(o => !o)} className="text-[#6b7494] hover:text-[#e8eaf0] transition-colors text-lg">☰</button>
          <div className="flex-1"><h1 className="text-sm font-medium text-[#e8eaf0]">{PAGE_LABELS[page]}</h1></div>
        </header>
        {ANALYSIS_PAGES.includes(page) && (
          <div className="px-6 pt-4"><AnalysisBar opts={opts} setOpts={setOpts} tickers={tickers} showPeriod={page === "dashboard" || page === "benchmark"} /></div>
        )}
        <main className="flex-1 overflow-y-auto px-6 py-6">
          {page === "dashboard" && <Dashboard opts={opts} onTickers={setTickers} />}
          {page === "performance" && <Performance opts={opts} onTickers={setTickers} />}
          {page === "benchmark" && <Benchmark opts={opts} onTickers={setTickers} />}
          {page === "fx" && <FxRates />}
          {page === "ai" && <AIAssistant />}
        </main>
      </div>
    </div>
  );
}
