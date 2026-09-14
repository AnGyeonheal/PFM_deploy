import { useState, useEffect } from "react";
import { PieChart, Pie, Cell, AreaChart, Area, BarChart, Bar, LabelList, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Card, CardHeader, formatKRW, ReturnBadge, PnLText, CustomTooltip, AnalysisNotice, AnalysisPeriodLabel, type AnalysisOptions } from "../components/Shared";

const ALLOC_COLORS = ["#00d4a1", "#4f8cff", "#6b7494", "#a78bfa", "#f0a500", "#ff5c6a", "#12b981", "#ff9f40"];

type CurrencyBalance = { krw: number | null; usd: number | null; totalKrw: number | null };
type AccountBalances = { cash: CurrencyBalance; invested: CurrencyBalance; total: CurrencyBalance; fxRate: number | null };

function CurrentAccountBalances({ balances }: { balances?: AccountBalances }) {
  if (!balances) return null;
  const formatBalance = (value: number | null, currency: "KRW" | "USD") => {
    if (value == null || !Number.isFinite(value)) return "미조회";
    return currency === "USD"
      ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value)
      : `${value.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}원`;
  };
  return (
    <section aria-label="현재 계좌 자산" className="border-y border-white/10 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
        <h2 className="text-sm font-medium text-[#e8eaf0]">현재 계좌 자산 <span className="text-xs font-normal text-[#6b7494] ml-2">전체 계좌 · 현재 기준</span></h2>
        <span className="text-xs text-[#6b7494] font-mono">{balances.fxRate == null ? "환율 미조회" : `$1 = ${balances.fxRate.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}원`}</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-white/10">
        {([
          { key: "cash", label: "예수금", detail: "연동 계좌 · 현금 주문가능금액", color: "#4f8cff" },
          { key: "invested", label: "투자 중인 금액", detail: "보유 종목의 현재 평가액", color: "#00d4a1" },
          { key: "total", label: "총 보유금액", detail: "예수금 + 투자 평가액", color: "#e8eaf0" },
        ] as const).map(item => {
          const balance = balances[item.key];
          return (
            <div key={item.key} role="group" aria-label={item.label} className="min-w-0 py-4 first:pt-0 last:pb-0 md:py-0 md:px-5 md:first:pl-0 md:last:pr-0">
              <h3 className="text-xs font-medium" style={{ color: item.color }}>{item.label}</h3>
              <div className="text-xs text-[#6b7494] mt-1">{item.detail}</div>
              <dl className="space-y-2 my-4 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="shrink-0 text-[#a0a8c0]">원화 <span className="text-[10px] font-mono text-[#6b7494]">KRW</span></dt>
                  <dd className="font-mono tabular-nums text-right break-all text-[#e8eaf0]">{formatBalance(balance.krw, "KRW")}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="shrink-0 text-[#a0a8c0]">달러 <span className="text-[10px] font-mono text-[#6b7494]">USD</span></dt>
                  <dd className="font-mono tabular-nums text-right break-all text-[#e8eaf0]">{formatBalance(balance.usd, "USD")}</dd>
                </div>
              </dl>
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-t border-white/7 pt-3">
                <span className="text-xs text-[#6b7494]">원화 환산</span>
                <span className="font-mono tabular-nums text-sm font-medium break-all" style={{ color: item.color }}>{formatBalance(balance.totalKrw, "KRW")}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

const DeltaText = ({ value, digits }: { value: number; digits: number }) => {
  if (!value) return <span className="font-mono text-xs text-[#6b7494]">±0</span>;
  const pos = value > 0;
  return <span className={`font-mono text-xs ${pos ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>{pos ? "▲" : "▼"} {Math.abs(value).toFixed(digits)}</span>;
};

export default function Dashboard({ opts, onTickers, onYears }: { opts: AnalysisOptions; onTickers?: (t: { ticker: string; name: string }[]) => void; onYears?: (years: number[]) => void }) {
  const [d, setD] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [projRate, setProjRate] = useState<number | null>(null);
  const [monthlyManwon, setMonthlyManwon] = useState<number>(0);  // 월 추가납입액(만원)

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    const stockQ = opts.scope === "stock" && opts.ticker ? `&ticker=${encodeURIComponent(opts.ticker)}` : "";
    const q = `div=${opts.includeDividend ? 1 : 0}&fx=${opts.includeFx ? 1 : 0}${stockQ}&period=${opts.period}&year=${opts.year ?? new Date().getFullYear()}`;
    fetch(`/api/app/dashboard?${q}`, { credentials: "include", signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data) => { if (controller.signal.aborted) return; setD(data); if (data?.tickers?.length && onTickers) onTickers(data.tickers); if (data?.years && onYears) onYears(data.years); })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [opts.includeDividend, opts.includeFx, opts.scope, opts.ticker, opts.period, opts.year]);

  if (loading) return <div className="text-[#6b7494] text-sm p-10 text-center font-mono">불러오는 중…</div>;
  if (error || !d) return <div className="text-[#ff5c6a] text-sm p-10 text-center font-mono">데이터를 불러오지 못했습니다. 로그인 상태를 확인하세요.</div>;

  const m = d.metrics;
  const stocks = d.stocks || [];
  const allocationData: { name: string; value: number; color: string }[] = (d.allocation || []).map((a: any, i: number) => ({ ...a, color: ALLOC_COLORS[i % ALLOC_COLORS.length] }));
  const effectivePnL = m.totalPnL;
  const effectiveReturn = m.returnPct;

  const historicalRate: number | null = Number.isFinite(m.projectionRate) ? m.projectionRate : null;
  const projRatePct = projRate ?? (historicalRate == null ? null : +historicalRate.toFixed(2));
  const projectionAvailable = projRatePct != null && Number.isFinite(projRatePct) && projRatePct > -100;
  const rate = (projRatePct ?? 0) / 100;
  const monthlyKRW = Math.max(0, monthlyManwon || 0) * 10000;  // 만원→원
  const rMonthly = Math.pow(1 + rate, 1 / 12) - 1;  // 연성장률의 월 환산
  const projData = (projectionAvailable ? [0, 5, 10, 20, 30, 40] : []).map(y => {
    const months = y * 12;
    const base = m.totalAsset * Math.pow(1 + rate, y);  // 현재 자산의 복리 성장
    const contrib = months === 0 ? 0
      : Math.abs(rMonthly) < 1e-9 ? monthlyKRW * months
        : monthlyKRW * (Math.pow(1 + rMonthly, months) - 1) / rMonthly;  // 매월 적립액의 미래가치(연금)
    return {
      label: y === 0 ? "현재" : `${y}년`, year: y,
      base: Math.round(base), contrib: Math.round(contrib),
      asset: Math.round(base + contrib),
      invested: Math.round(m.totalAsset + monthlyKRW * months),  // 납입원금(현재자산+누적 적립)
    };
  });

  return (
    <div className="space-y-6">
      <CurrentAccountBalances balances={d.accountBalances} />
      <AnalysisPeriodLabel opts={opts} asOf={d.analysis?.asOf} benchmarkAsOf={d.analysis?.benchmarkAsOf} />
      <AnalysisNotice analysis={d.analysis} />
      {/* KPI Row - D1 */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        {[
          {
            label: opts.period === "YOY" ? "총 자산 (현재)" : "총 자산", value: formatKRW(m.totalAsset),
            sub: d.changes && d.changes.totalAssetDelta != null
              ? `전일 대비 ${d.changes.totalAssetDelta >= 0 ? "+" : ""}${formatKRW(d.changes.totalAssetDelta, true)}${d.changes.totalAssetDeltaPct != null ? ` (${d.changes.totalAssetDeltaPct >= 0 ? "+" : ""}${d.changes.totalAssetDeltaPct}%)` : ""}`
              : `현금 ${formatKRW(m.cash, true)} 포함`,
            highlight: false,
          },
          {
            label: "총 손익", value: effectivePnL == null ? "—" : (effectivePnL >= 0 ? "+" : "") + formatKRW(effectivePnL),
            sub: effectiveReturn == null ? "수익률 —" : `수익률 ${effectiveReturn >= 0 ? "+" : ""}${effectiveReturn.toFixed(2)}%`,
            highlight: effectivePnL != null, positive: effectivePnL >= 0,
          },
          {
            label: "연평균 수익률", value: m.xirr != null ? `${m.xirr >= 0 ? "+" : ""}${m.xirr.toFixed(2)}%` : "—",
            sub: `${opts.period === "YOY" ? `${opts.year ?? new Date().getFullYear()}년 ` : ""}XIRR · ${d.analysis?.status === "partial" ? "일부 종목 기준" : "투자원금 흐름 반영"}`,
            highlight: m.xirr != null, positive: (m.xirr || 0) >= 0,
          },
          {
            label: opts.period === "YOY" ? "기말 주식 평가액" : d.analysis?.status === "partial" ? "분석 종목 평가액" : "주식 평가액", value: formatKRW(m.totalCurrent),
            sub: `매입원가 ${formatKRW(m.totalBuy, true)}${m.holdingReturnPct == null ? "" : ` · 보유분 ${m.holdingReturnPct >= 0 ? "+" : ""}${m.holdingReturnPct.toFixed(2)}%`}`, highlight: false,
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

      <section aria-label="손익 구분" className="border-y border-white/10 py-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
          <h2 className="text-sm font-medium text-[#e8eaf0]">손익 구분</h2>
          <span className="text-xs text-[#6b7494]">선택기간 · 원화 환산</span>
        </div>
        <dl className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-white/10">
          {[
            { label: "실현 손익", value: m.realizedPnL, title: "선택기간에 매도로 실현한 손익" },
            { label: "미실현 손익", value: m.unrealizedPnL, title: "선택기간 동안의 평가손익 변동. 전체기간 선택 시 현재 보유분 평가손익." },
            { label: "배당 손익", value: m.dividendPnL, title: "선택기간의 배당·분배금", excluded: !opts.includeDividend },
          ].map(item => {
            const value = typeof item.value === "number" && Number.isFinite(item.value) ? item.value : null;
            const displayed = value == null ? null : Math.round(value);
            return (
              <div key={item.label} role="group" aria-label={item.label} className="min-w-0 py-4 first:pt-0 last:pb-0 md:py-0 md:px-5 md:first:pl-0 md:last:pr-0">
                <dt title={item.title} className="flex items-center gap-2 text-xs text-[#a0a8c0]">
                  {item.label}
                  {item.excluded && <span className="text-[#6b7494]">(제외)</span>}
                </dt>
                <dd className={`mt-2 text-xl font-mono tabular-nums break-all ${value == null || displayed === 0 || item.excluded ? "text-[#a0a8c0]" : value > 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
                  {displayed == null ? "—" : `${displayed > 0 ? "+" : ""}${displayed.toLocaleString("ko-KR")}원`}
                </dd>
              </div>
            );
          })}
        </dl>
      </section>

      {/* 전일 대비 변동 */}
      {d.changes && (
        <Card>
          <CardHeader title="전일 대비 변동" sub={`${d.changes.asOf} 기준 대비`} />
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between bg-[#0a0d14] border border-white/5 rounded-sm px-4 py-3">
              <span className="text-sm text-[#a0a8c0]">전체 자산</span>
              <span className={`font-mono text-sm ${d.changes.totalAssetDelta >= 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
                {d.changes.totalAssetDelta >= 0 ? "▲ +" : "▼ "}{formatKRW(d.changes.totalAssetDelta)}
                {d.changes.totalAssetDeltaPct != null && ` (${d.changes.totalAssetDeltaPct >= 0 ? "+" : ""}${d.changes.totalAssetDeltaPct}%)`}
              </span>
            </div>
            {d.changes.stocks.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/7">
                      {["종목", "알파(연%)", "Δ 알파", "베타", "Δ 베타"].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.changes.stocks.map((s: any) => (
                      <tr key={s.ticker} className="border-b border-white/4">
                        <td className="px-3 py-2">
                          <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                          <div className="text-xs text-[#6b7494]">{s.name}</div>
                        </td>
                        <td className="px-3 py-2 font-mono text-xs text-[#e8eaf0]">{s.alpha.toFixed(2)}</td>
                        <td className="px-3 py-2"><DeltaText value={s.alphaDelta} digits={2} /></td>
                        <td className="px-3 py-2 font-mono text-xs text-[#e8eaf0]">{s.beta.toFixed(3)}</td>
                        <td className="px-3 py-2"><DeltaText value={s.betaDelta} digits={3} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-xs text-[#6b7494] font-mono">종목별 비교 데이터가 아직 없습니다.</p>
            )}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Performance Chart */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader title="자산 성장 추이" sub="기준가 100" />
            <div className="p-5">
              {!d.growth?.length ? <div className="h-[220px] flex items-center justify-center text-xs text-[#6b7494]">선택 범위의 성장 데이터가 없습니다.</div> : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={d.growth || []} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
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
              )}
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
        <CardHeader title="장기 자산 예측" sub={projectionAvailable ? `현재 자산 ${formatKRW(m.totalAsset, true)} · 연 ${projRatePct!.toFixed(1)}%${monthlyManwon > 0 ? ` · 월 ${monthlyManwon.toLocaleString()}만원 적립` : ""} 가정` : "예측 기준 수익률 없음"} />
        <div className="p-5 space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-[#6b7494] font-mono uppercase tracking-wider">연평균 성장률</span>
            <input type="number" aria-label="예측 연평균 성장률" step="0.1" min="-99.9" value={projRatePct ?? ""}
              onChange={event => setProjRate(Number.isFinite(event.target.valueAsNumber) ? event.target.valueAsNumber : null)}
              className="w-20 bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50" />
            <span className="text-sm text-[#a0a8c0]">%</span>
            <button onClick={() => setProjRate(null)} disabled={historicalRate == null}
              className="text-xs font-mono px-2.5 py-1 rounded-sm border border-white/10 text-[#6b7494] hover:text-[#a0a8c0] transition-colors disabled:opacity-50">
              {historicalRate == null ? "자동 계산 불가" : `자동 ${historicalRate.toFixed(1)}%`}
            </button>
            <span className="w-px h-5 bg-white/10 mx-1" />
            <span className="text-xs text-[#6b7494] font-mono uppercase tracking-wider">월 적립액</span>
            <input type="number" step="10" min="0" value={monthlyManwon}
              onChange={e => setMonthlyManwon(Math.max(0, parseFloat(e.target.value) || 0))}
              className="w-24 bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#4f8cff]/50" />
            <span className="text-sm text-[#a0a8c0]">만원</span>
          </div>
          {projectionAvailable ? <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {projData.filter(p => p.year > 0).map(p => (
              <div key={p.year} className="bg-[#0a0d14] border border-white/5 rounded-sm p-3">
                <div className="text-xs text-[#6b7494] font-mono mb-1">{p.year}년 후</div>
                <div className="font-['DM_Serif_Display',serif] text-lg text-[#00d4a1]">{formatKRW(p.asset, true)}</div>
                <div className="text-[10px] text-[#6b7494] font-mono mt-0.5">납입 {formatKRW(p.invested, true)} · {p.invested > 0 ? (p.asset / p.invested).toFixed(2) : "-"}배</div>
              </div>
            ))}
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={projData} margin={{ top: 20, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="label" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={(v: any) => formatKRW(Number(v), true)} tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} width={56} />
              <Tooltip cursor={{ fill: "rgba(255,255,255,0.03)" }} content={({ active, payload, label }: any) => {
                if (!active || !payload?.length) return null;
                const r0 = payload[0].payload;
                return (
                  <div className="bg-[#161c2d] border border-white/10 rounded p-3 text-xs font-mono shadow-xl">
                    <div className="text-[#6b7494] mb-2">{label}</div>
                    <div className="flex justify-between gap-6 mb-1"><span className="text-[#00d4a1]">현재자산 성장</span><span className="text-[#e8eaf0]">{formatKRW(r0.base)}</span></div>
                    {r0.contrib > 0 && <div className="flex justify-between gap-6 mb-1"><span className="text-[#4f8cff]">추가납입 성장</span><span className="text-[#e8eaf0]">{formatKRW(r0.contrib)}</span></div>}
                    <div className="flex justify-between gap-6 pt-1.5 mt-1 border-t border-white/10"><span className="text-[#a0a8c0]">총 예상자산</span><span className="text-[#e8eaf0]">{formatKRW(r0.asset)}</span></div>
                    <div className="flex justify-between gap-6 mt-1"><span className="text-[#6b7494]">납입원금</span><span className="text-[#6b7494]">{formatKRW(r0.invested)}</span></div>
                  </div>
                );
              }} />
              <Bar dataKey="base" stackId="a" fill="#00d4a1" name="현재자산 성장" />
              <Bar dataKey="contrib" stackId="a" radius={[4, 4, 0, 0]} fill="#4f8cff" name="추가납입 성장">
                <LabelList dataKey="asset" position="top" formatter={(v: any) => formatKRW(Number(v), true)} style={{ fill: "#a0a8c0", fontSize: 10, fontFamily: "JetBrains Mono" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          </> : <div className="text-xs text-[#6b7494]">전체 투자이력의 수익률이 없어 자동 예측을 표시하지 않습니다.</div>}
          <p className="text-xs text-[#6b7494] font-mono leading-relaxed">
            ※ 자동 성장률은 전체 투자이력의 XIRR입니다. 매월 말 추가납입과 일정한 수익률을 가정하며, 미래 수익을 보장하지 않습니다.
          </p>
        </div>
      </Card>

      {/* Holdings - D2, D3 */}
      <Card>
        <CardHeader title={opts.period === "YOY" ? "종목별 연간 성과" : "보유 종목"} sub={`${stocks.length}개 종목`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {(opts.period === "YOY" ? ["종목", "현재가", "현재 평단가", "매입환율", "현재 수량", "기말 평가액", "기말 원가", "기말 평가손익", "기말 보유분 수익률", "연간 투입금 대비 수익률"] : ["종목", "현재가", "평단가", "매입환율", "수량", "평가액", "매입원가", "보유분 평가손익", "보유분 수익률", "투입금 대비 총수익률"]).map(h => (
                  <th key={h} title={h.includes("보유분 수익률") ? "평가손익 / 잔여 보유원가. 실현손익과 배당은 제외." : h.includes("투입금") ? "선택기간의 기초 평가액과 총 매수금액 대비 실현손익·평가손익·배당 합계." : undefined} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stocks.map((s: any, i: number) => (
                  <tr key={s.ticker} className={`border-b border-white/4 hover:bg-white/3 transition-colors ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                      <div className="text-xs text-[#6b7494] mt-0.5">{s.name}</div>
                      {s.analysis && !["complete", "partial"].includes(s.analysis.status) && <div className="text-xs text-[#fbbf24] mt-1" title={s.analysis.warnings.join("\n")}>성과 계산 불가</div>}
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
                    <td className="px-4 py-3"><PnLText value={s.holdingUnrealizedPnL} /></td>
                    <td className="px-4 py-3"><ReturnBadge value={s.holdingReturnPct} /></td>
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
