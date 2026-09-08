import { useState, useEffect } from "react";
import { PieChart, Pie, Cell, AreaChart, Area, BarChart, Bar, LabelList, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Card, CardHeader, formatKRW, ReturnBadge, PnLText, CustomTooltip, type AnalysisOptions } from "../components/Shared";

const ALLOC_COLORS = ["#00d4a1", "#4f8cff", "#6b7494", "#a78bfa", "#f0a500", "#ff5c6a", "#12b981", "#ff9f40"];

export default function Dashboard({ opts, onTickers }: { opts: AnalysisOptions; onTickers?: (t: { ticker: string; name: string }[]) => void }) {
  const [d, setD] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [projRate, setProjRate] = useState<number | null>(null);  // 장기 예측 연성장률(%), null이면 과거 CAGR 사용

  useEffect(() => {
    setLoading(true);
    setError(false);
    const stockQ = opts.scope === "stock" && opts.ticker ? `&ticker=${encodeURIComponent(opts.ticker)}` : "";
    const q = `div=${opts.includeDividend ? 1 : 0}&fx=${opts.includeFx ? 1 : 0}${stockQ}&period=${opts.period}`;
    fetch(`/api/app/dashboard?${q}`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => { setD(data); if (data?.tickers?.length && onTickers) onTickers(data.tickers); })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [opts.includeDividend, opts.includeFx, opts.scope, opts.ticker, opts.period]);

  if (loading) return <div className="text-[#6b7494] text-sm p-10 text-center font-mono">불러오는 중…</div>;
  if (error || !d) return <div className="text-[#ff5c6a] text-sm p-10 text-center font-mono">데이터를 불러오지 못했습니다. 로그인 상태를 확인하세요.</div>;

  const m = d.metrics;
  const stocks = d.stocks || [];
  const allocationData = (d.allocation || []).map((a: any, i: number) => ({ ...a, color: ALLOC_COLORS[i % ALLOC_COLORS.length] }));
  const effectivePnL = m.totalPnL;
  const effectiveReturn = m.returnPct;

  // 장기 자산 예측: 현재 총자산에 과거 연평균 성장률(CAGR)을 복리 적용
  const parseYm = (s: string) => { const p = String(s).split("/"); return (+p[0]) * 12 + (+p[1]); };
  const gArr = d.growth || [];
  const projYears = gArr.length >= 2 ? Math.max((parseYm(gArr[gArr.length - 1].month) - parseYm(gArr[0].month)) / 12, 0.25) : 1;
  const cagr = Math.pow(1 + Math.max(effectiveReturn / 100, -0.99), 1 / projYears) - 1;
  const projRatePct = projRate != null ? projRate : +(cagr * 100).toFixed(2);
  const rate = projRatePct / 100;
  const projData = [0, 5, 10, 20, 30, 40].map(y => ({
    label: y === 0 ? "현재" : `${y}년`, year: y,
    asset: Math.round(m.totalAsset * Math.pow(1 + rate, y)),
  }));

  return (
    <div className="space-y-6">
      {/* KPI Row - D1 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: "총 자산", value: formatKRW(m.totalAsset),
            sub: `현금 ${formatKRW(m.cash, true)} 포함`, highlight: false,
          },
          {
            label: "총 손익", value: (effectivePnL >= 0 ? "+" : "") + formatKRW(effectivePnL),
            sub: `수익률 ${effectiveReturn >= 0 ? "+" : ""}${effectiveReturn.toFixed(2)}%`,
            highlight: true, positive: effectivePnL >= 0,
          },
          {
            label: "주식 평가액", value: formatKRW(m.totalCurrent),
            sub: `매입원가 ${formatKRW(m.totalBuy, true)}`, highlight: false,
          },
          {
            label: "환율 (USD/KRW)", value: Math.round(d.fx).toLocaleString(),
            sub: opts.includeFx ? "환차손익 반영됨" : "환차손익 제외",
            highlight: false,
          },
        ].map((kpi) => (
          <Card key={kpi.label} className="p-5 hover:border-white/15 transition-colors">
            <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono mb-3">{kpi.label}</div>
            <div className={`font-['DM_Serif_Display',serif] text-2xl md:text-3xl ${kpi.highlight ? (kpi.positive ? "text-[#00d4a1]" : "text-[#ff5c6a]") : "text-[#e8eaf0]"}`}>
              {kpi.value}
            </div>
            <div className="text-xs text-[#6b7494] mt-2 font-mono">{kpi.sub}</div>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Performance Chart */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader title="자산 성장 추이" sub="기준가 100" />
            <div className="p-5">
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={d.growth || []} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                  <defs>
                    <linearGradient id="portGrad2" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00d4a1" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#00d4a1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="month" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="portfolio" stroke="#00d4a1" strokeWidth={2} fill="url(#portGrad2)" name="포트폴리오" dot={false} activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="sp500" stroke="#4f8cff" strokeWidth={1.5} fill="none" name="S&P500" dot={false} strokeDasharray="4 2" activeDot={{ r: 4 }} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        {/* Allocation - D2 */}
        <Card>
          <CardHeader title="자산 배분" />
          <div className="p-5">
            <ResponsiveContainer width="100%" height={140}>
              <PieChart>
                <Pie data={allocationData} cx="50%" cy="50%" innerRadius={48} outerRadius={68} paddingAngle={3} dataKey="value" stroke="none">
                  {allocationData.map(e => <Cell key={e.name} fill={e.color} />)}
                </Pie>
                <Tooltip content={<CustomTooltip />} formatter={(v: any) => `${v}%`} />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-2 mt-2">
              {allocationData.map(item => (
                <div key={item.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ background: item.color }} />
                    <span className="text-xs text-[#a0a8c0]">{item.name}</span>
                  </div>
                  <span className="font-mono text-xs text-[#e8eaf0]">{item.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* 장기 자산 예측 */}
      <Card>
        <CardHeader title="장기 자산 예측" sub={`현재 자산 ${formatKRW(m.totalAsset, true)} · 연 ${projRatePct.toFixed(1)}% 복리 가정`} />
        <div className="p-5 space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-[#6b7494] font-mono uppercase tracking-wider">연평균 성장률</span>
            <input type="number" step="0.1" value={projRatePct}
              onChange={e => setProjRate(parseFloat(e.target.value))}
              className="w-24 bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50" />
            <span className="text-sm text-[#a0a8c0]">%</span>
            <button onClick={() => setProjRate(null)}
              className="text-xs font-mono px-2.5 py-1 rounded-sm border border-white/10 text-[#6b7494] hover:text-[#a0a8c0] transition-colors">
              자동 {(cagr * 100).toFixed(1)}% (과거 연평균)
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {projData.filter(p => p.year > 0).map(p => (
              <div key={p.year} className="bg-[#0a0d14] border border-white/5 rounded-sm p-3">
                <div className="text-xs text-[#6b7494] font-mono mb-1">{p.year}년 후</div>
                <div className="font-['DM_Serif_Display',serif] text-lg text-[#00d4a1]">{formatKRW(p.asset, true)}</div>
                <div className="text-[10px] text-[#6b7494] font-mono mt-0.5">{m.totalAsset > 0 ? (p.asset / m.totalAsset).toFixed(1) : "-"}배</div>
              </div>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={projData} margin={{ top: 20, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="label" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: any) => formatKRW(Number(v), true)} tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} width={56} />
              <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} formatter={(v: any) => [formatKRW(Number(v)), "예상 자산"]}
                contentStyle={{ background: "#161c2d", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, fontSize: 12, fontFamily: "JetBrains Mono" }}
                labelStyle={{ color: "#6b7494" }} itemStyle={{ color: "#e8eaf0" }} />
              <Bar dataKey="asset" radius={[4, 4, 0, 0]}>
                {projData.map((p, i) => <Cell key={i} fill={p.year === 0 ? "#4f8cff" : "#00d4a1"} />)}
                <LabelList dataKey="asset" position="top" formatter={(v: any) => formatKRW(Number(v), true)} style={{ fill: "#a0a8c0", fontSize: 10, fontFamily: "JetBrains Mono" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <p className="text-xs text-[#6b7494] font-mono leading-relaxed">
            ※ 과거 연평균 성장률(CAGR)을 그대로 복리 적용한 단순 추정입니다. 실제 수익률은 매년 달라지며, 높은 성장률을 장기 적용하면 과대추정될 수 있습니다. 성장률을 직접 바꿔 보수적 시나리오와 비교해 보세요.
          </p>
        </div>
      </Card>

      {/* Holdings - D2, D3 */}
      <Card>
        <CardHeader title="보유 종목" sub={`${stocks.length}개 종목`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {["종목", "현재가", "평단가", "매입환율", "수량", "평가액", "매입원가", "평가손익", "수익률"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stocks.map((s: any, i: number) => (
                  <tr key={s.ticker} className={`border-b border-white/4 hover:bg-white/3 transition-colors ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                      <div className="text-xs text-[#6b7494] mt-0.5">{s.name}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#e8eaf0]">
                      {s.currentPrice == null ? "-" : (s.currency === "USD" ? `$${s.currentPrice.toLocaleString()}` : `${Math.round(s.currentPrice).toLocaleString()}원`)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {s.currency === "USD" ? (
                        <div>
                          <div className="text-[#e8eaf0]">${s.avgPrice?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</div>
                          <div className="text-[#6b7494] mt-0.5">{s.avgPriceKrw ? `${Math.round(s.avgPriceKrw).toLocaleString()}원` : "-"}</div>
                        </div>
                      ) : (
                        <span className="text-[#e8eaf0]">{s.avgPrice ? `${Math.round(s.avgPrice).toLocaleString()}원` : "-"}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">
                      {s.currency === "USD" && s.avgBuyFx ? `${s.avgBuyFx.toLocaleString()}원` : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{s.quantity}</td>
                    <td className="px-4 py-3 font-mono text-xs text-[#e8eaf0]">{formatKRW(s.currentTotal, true)}</td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{formatKRW(s.buyTotal, true)}</td>
                    <td className="px-4 py-3"><PnLText value={s.unrealizedPnL} /></td>
                    <td className="px-4 py-3"><ReturnBadge value={s.returnPct} /></td>
                  </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
