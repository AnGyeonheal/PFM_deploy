import { useState, useEffect } from "react";
import {
  AreaChart, Area, LineChart, Line, BarChart, Bar, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { Card, CardHeader, CustomTooltip, ReturnBadge, formatKRW, type AnalysisOptions } from "../components/Shared";

type Summary = { portfolioReturn: number | null; sp500Return: number | null; alpha: number | null; beta: number | null; corr: number | null; sharpe: number | null; twrReturn: number | null };
type PerStock = { ticker: string; name: string; returnPct: number; alpha: number; beta: number; alphaContrib: number; betaContrib: number };
type Sim = { startYm: string; startKrw: number; myProfit: number; spyProfit: number; diff: number } | null;
type BenchData = {
  summary: Summary;
  growth: { month: string; portfolio: number; sp500: number; principal: number; portfolioPct: number | null; sp500Pct: number | null; alpha: number | null; beta: number | null }[];
  rollingBeta: { month: string; beta: number }[];
  monthlyAlpha: { month: string; alpha: number }[];
  perStock: PerStock[];
  simulation: Sim;
  tickers?: { ticker: string; name: string }[];
};

const simStartOptions = ["2024-01", "2024-04", "2024-07", "2024-10"];

const ChartTooltip = ({ active, payload, label, isPct }: any) => {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload || {};
  return (
    <div className="bg-[#161c2d] border border-white/10 rounded p-3 text-xs font-mono shadow-xl">
      <div className="text-[#6b7494] mb-2">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 mb-1">
          <span className="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ background: p.color }} />
          <span className="text-[#a0a8c0]">{p.name}</span>
          <span className="text-[#e8eaf0] ml-auto pl-4">{isPct ? `${p.value >= 0 ? "+" : ""}${p.value}%` : formatKRW(p.value)}</span>
        </div>
      ))}
      {(row.alpha != null || row.beta != null) && (
        <div className="mt-2 pt-2 border-t border-white/10 flex gap-3">
          {row.alpha != null && <span className="text-[#a78bfa]">α {row.alpha >= 0 ? "+" : ""}{row.alpha}%p</span>}
          {row.beta != null && <span className="text-[#fbbf24]">β {row.beta}</span>}
        </div>
      )}
    </div>
  );
};

export default function Benchmark({ opts, onTickers }: { opts: AnalysisOptions; onTickers?: (t: { ticker: string; name: string }[]) => void }) {
  const [simStart, setSimStart] = useState("");
  const [chartMode, setChartMode] = useState<"amount" | "pct">("amount");
  const [d, setD] = useState<BenchData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    setLoading(true);
    const stockQ = opts.scope === "stock" && opts.ticker ? `&ticker=${encodeURIComponent(opts.ticker)}` : "";
    const qs = `div=${opts.includeDividend ? 1 : 0}&fx=${opts.includeFx ? 1 : 0}${simStart ? `&start=${simStart}` : ""}${stockQ}&period=${opts.period}`;
    fetch(`/api/app/benchmark?${qs}`, { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("데이터를 불러오지 못했습니다"); return r.json(); })
      .then(j => { setD(j); setErr(""); if (j?.tickers?.length && onTickers) onTickers(j.tickers); })
      .catch(e => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  }, [opts.includeDividend, opts.includeFx, simStart, opts.scope, opts.ticker, opts.period]);

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center">불러오는 중…</div>;
  if (err) return <div className="text-[#ff5c6a] text-sm py-20 text-center">{err}</div>;
  if (!d) return null;

  const performanceData = d.growth;
  const rollingBeta = d.rollingBeta;
  const monthlyAlpha = d.monthlyAlpha;
  const portfolioReturn = d.summary.portfolioReturn ?? 0;
  const sp500Return = d.summary.sp500Return ?? 0;
  const alpha = d.summary.alpha ?? 0;
  const beta = d.summary.beta ?? 0;
  const correlation = d.summary.corr ?? 0;
  const sharpe = d.summary.sharpe ?? 0;
  const twrReturn = d.summary.twrReturn ?? 0;
  const sim = d.simulation;

  return (
    <div className="space-y-6">
      {/* F1/F2 Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {[
          { label: "포트폴리오 수익률", value: `${portfolioReturn >= 0 ? "+" : ""}${portfolioReturn}%`, color: "#00d4a1" },
          { label: "S&P500 수익률", value: `${sp500Return >= 0 ? "+" : ""}${sp500Return}%`, color: "#4f8cff" },
          { label: "알파 (초과수익)", value: `${alpha >= 0 ? "+" : ""}${alpha.toFixed(1)}%p`, color: "#a78bfa" },
          { label: "베타 (시장민감도)", value: beta.toFixed(2), color: "#fbbf24" },
          { label: "TWR (시간가중)", value: `${twrReturn >= 0 ? "+" : ""}${twrReturn}%`, color: "#00d4a1" },
        ].map(k => (
          <Card key={k.label} className="p-4">
            <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono mb-2.5">{k.label}</div>
            <div className="font-['DM_Serif_Display',serif] text-2xl" style={{ color: k.color }}>{k.value}</div>
          </Card>
        ))}
      </div>

      {/* F1 Growth comparison */}
      <Card>
        <CardHeader title={chartMode === "amount" ? "자산 성장 추이 vs S&P500" : "수익률 추이 vs S&P500"}
          sub={chartMode === "amount"
            ? "같은 시점·금액으로 S&P500을 매매했다면의 내 자산가치(원) 비교"
            : "투입자본 대비 누적 수익률(%) · 매도 회수금 반영"} />
        <div className="p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4 text-xs font-mono text-[#6b7494]">
              <div className="flex items-center gap-2"><span className="w-4 h-0.5 bg-[#00d4a1] inline-block" /><span>{chartMode === "amount" ? "내 자산가치" : "내 수익률"}</span></div>
              <div className="flex items-center gap-2"><span className="w-4 h-0.5 bg-[#4f8cff] inline-block" style={{ borderTop: "2px dashed #4f8cff" }} /><span>{chartMode === "amount" ? "S&P500 동일매매" : "S&P500 수익률"}</span></div>
              {chartMode === "amount" && <div className="flex items-center gap-2"><span className="w-4 h-0.5 inline-block" style={{ borderTop: "2px dashed #9aa4ae" }} /><span>순투자원금</span></div>}
            </div>
            <div className="flex gap-0 border border-white/10 rounded-sm overflow-hidden">
              {(["amount", "pct"] as const).map(m => (
                <button key={m} onClick={() => setChartMode(m)}
                  className={`text-xs font-mono px-2.5 py-1 transition-colors ${chartMode === m ? "bg-white/10 text-[#e8eaf0]" : "text-[#6b7494] hover:text-[#a0a8c0]"}`}>
                  {m === "amount" ? "금액(원)" : "수익률(%)"}
                </button>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={performanceData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="pGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00d4a1" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#00d4a1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="month" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} tickFormatter={(v: number) => chartMode === "amount" ? formatKRW(v, true) : `${v}%`} width={54} />
              <Tooltip content={<ChartTooltip isPct={chartMode === "pct"} />} />
              {chartMode === "amount" ? (
                <>
                  <Area type="monotone" dataKey="portfolio" stroke="#00d4a1" strokeWidth={2} fill="url(#pGrad)" name="내 자산가치" dot={false} activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="sp500" stroke="#4f8cff" strokeWidth={1.5} fill="none" name="S&P500 동일매매" dot={false} strokeDasharray="5 3" activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="principal" stroke="#9aa4ae" strokeWidth={1.2} fill="none" name="순투자원금" dot={false} strokeDasharray="2 2" activeDot={{ r: 4 }} />
                </>
              ) : (
                <>
                  <Area type="monotone" dataKey="portfolioPct" stroke="#00d4a1" strokeWidth={2} fill="url(#pGrad)" name="내 수익률" dot={false} activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="sp500Pct" stroke="#4f8cff" strokeWidth={1.5} fill="none" name="S&P500 수익률" dot={false} strokeDasharray="5 3" activeDot={{ r: 4 }} />
                </>
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* F5 Rolling beta */}
        <Card>
          <CardHeader title="롤링 베타 추이" sub="F5: 시간에 따른 시장 민감도 변화" />
          <div className="p-5">
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={rollingBeta} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="month" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                <Tooltip content={<CustomTooltip />} />
                {/* Beta=1 reference line */}
                <Line type="monotone" dataKey={() => 1} stroke="rgba(255,255,255,0.15)" strokeWidth={1} dot={false} name="기준(β=1)" strokeDasharray="4 2" />
                <Line type="monotone" dataKey="beta" stroke="#fbbf24" strokeWidth={2} dot={false} name="롤링 베타" activeDot={{ r: 4, fill: "#fbbf24" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Monthly alpha - F7 */}
        <Card>
          <CardHeader title="월별 알파" sub="F7: 초과수익 시계열" />
          <div className="p-5">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={monthlyAlpha} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="month" tick={{ fill: "#6b7494", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#6b7494", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} unit="%" />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="alpha" name="알파(%p)" radius={[2, 2, 0, 0]}>
                  {monthlyAlpha.map((d, i) => (
                    <Cell key={i} fill={d.alpha >= 0 ? "#00d4a1" : "#ff5c6a"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* F3 Key stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "알파 (연율화)", value: `${alpha >= 0 ? "+" : ""}${alpha.toFixed(1)}%`, desc: "초과 수익률", color: "#a78bfa" },
          { label: "베타", value: beta.toFixed(2), desc: "시장 민감도", color: "#fbbf24" },
          { label: "상관계수 (ρ)", value: correlation.toFixed(2), desc: "vs S&P500", color: "#4f8cff" },
          { label: "샤프 지수", value: sharpe.toFixed(2), desc: "무위험수익률 3.5%", color: "#00d4a1" },
        ].map(k => (
          <Card key={k.label} className="p-4">
            <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono mb-2">{k.label}</div>
            <div className="font-['DM_Serif_Display',serif] text-3xl mb-1" style={{ color: k.color }}>{k.value}</div>
            <div className="text-xs text-[#6b7494] font-mono">{k.desc}</div>
          </Card>
        ))}
      </div>

      {/* F6 Simulation */}
      <Card>
        <CardHeader title="지수 일시투자 시뮬레이션" sub="F6: 특정 시작월에 전액 S&P500 투자 시 비교" />
        <div className="p-5">
          <div className="flex items-center gap-3 mb-6">
            <span className="text-xs text-[#6b7494] font-mono">시작 시점:</span>
            {simStartOptions.map(s => (
              <button key={s} onClick={() => setSimStart(s)}
                className={`text-xs font-mono px-3 py-1.5 rounded-sm border transition-colors ${simStart === s ? "border-[#a78bfa]/40 bg-[#a78bfa]/10 text-[#a78bfa]" : "border-white/10 text-[#6b7494] hover:text-[#a0a8c0]"}`}>
                {s}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-6">
            <div className="bg-[#0a0d14] rounded-sm p-5 border border-white/5">
              <div className="text-xs text-[#6b7494] font-mono uppercase tracking-wider mb-3">내 포트폴리오 수익</div>
              <div className="font-['DM_Serif_Display',serif] text-3xl text-[#00d4a1]">{sim ? `${sim.myProfit >= 0 ? "+" : ""}${(sim.myProfit / 1_000_000).toFixed(1)}백만원` : "—"}</div>
              <div className="text-xs text-[#6b7494] font-mono mt-2">{sim ? `시작금액 ${(sim.startKrw / 1_000_000).toFixed(1)}백만원` : ""}</div>
            </div>
            <div className="bg-[#0a0d14] rounded-sm p-5 border border-white/5">
              <div className="text-xs text-[#6b7494] font-mono uppercase tracking-wider mb-3">S&P500 일시투자 시</div>
              <div className="font-['DM_Serif_Display',serif] text-3xl text-[#4f8cff]">{sim ? `${sim.spyProfit >= 0 ? "+" : ""}${(sim.spyProfit / 1_000_000).toFixed(1)}백만원` : "—"}</div>
              <div className="text-xs text-[#6b7494] font-mono mt-2">{sim ? `시작월 ${sim.startYm}` : ""}</div>
            </div>
          </div>
          {sim && (
            <div className="mt-4 bg-[#00d4a1]/5 border border-[#00d4a1]/15 rounded-sm px-4 py-3 text-xs text-[#00d4a1] font-mono">
              {sim.diff >= 0 ? "↑ 내 포트폴리오가 S&P500 대비 " : "↓ S&P500이 내 포트폴리오 대비 "}
              {(Math.abs(sim.diff) / 1_000_000).toFixed(1)}백만원 더 벌었습니다
            </div>
          )}
        </div>
      </Card>

      {/* F4 Per-stock alpha/beta */}
      <Card>
        <CardHeader title="종목별 알파·베타" sub="F4: 알파기여도·베타기여도" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {["종목", "수익률", "알파", "베타", "알파기여도", "베타기여도"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...d.perStock].sort((a, b) => b.alpha - a.alpha).map((s, i) => (
                <tr key={s.ticker} className={`border-b border-white/4 hover:bg-white/3 transition-colors ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                  <td className="px-4 py-3">
                    <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                    <div className="text-xs text-[#6b7494]">{s.name}</div>
                  </td>
                  <td className="px-4 py-3"><ReturnBadge value={s.returnPct} /></td>
                  <td className="px-4 py-3">
                    <span className={`font-mono text-xs ${s.alpha >= 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
                      {s.alpha >= 0 ? "+" : ""}{s.alpha.toFixed(1)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{s.beta.toFixed(2)}</td>
                  <td className="px-4 py-3">
                    <span className={`font-mono text-xs ${s.alphaContrib >= 0 ? "text-[#a78bfa]" : "text-[#ff5c6a]"}`}>
                      {s.alphaContrib >= 0 ? "+" : ""}{s.alphaContrib.toFixed(2)}%p
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#fbbf24]">{s.betaContrib.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
