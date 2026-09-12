import { useState, useEffect } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { Card, CardHeader, formatKRW, ReturnBadge, PnLText, CustomTooltip, AnalysisNotice, type AnalysisCoverage, type AnalysisOptions } from "../components/Shared";

type Metrics = {
  totalBuy: number; unrealizedPnL: number | null; realizedPnL: number | null;
  dividendPnL: number | null; fxPnL: number | null; pureStockPnL: number | null;
  totalPnL: number | null; returnPct: number | null;
};
type StockRow = {
  ticker: string; name: string; buyTotal: number; unrealizedPnL: number | null;
  realizedPnL: number | null; dividend: number | null; returnPct: number | null; status: string;
  analysis?: AnalysisCoverage;
};

export default function Performance({ opts, onTickers }: { opts: AnalysisOptions; onTickers?: (t: { ticker: string; name: string }[]) => void }) {
  const [m, setM] = useState<Metrics | null>(null);
  const [rows, setRows] = useState<StockRow[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisCoverage>();
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const stockQ = opts.scope === "stock" && opts.ticker ? `&ticker=${encodeURIComponent(opts.ticker)}` : "";
    fetch(`/api/app/dashboard?div=${opts.includeDividend ? 1 : 0}&fx=${opts.includeFx ? 1 : 0}${stockQ}`, { credentials: "include", signal: controller.signal })
      .then(r => { if (!r.ok) throw new Error("데이터를 불러오지 못했습니다"); return r.json(); })
      .then(d => { setM(d.metrics); setRows(d.stocks || []); setAnalysis(d.analysis); setErr(""); if (d?.tickers?.length && onTickers) onTickers(d.tickers); })
      .catch(e => { if (!controller.signal.aborted) setErr(String(e.message || e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [opts.includeDividend, opts.includeFx, opts.scope, opts.ticker]);

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center">불러오는 중…</div>;
  if (err) return <div className="text-[#ff5c6a] text-sm py-20 text-center">{err}</div>;
  if (!m) return null;

  const unrealized = m.unrealizedPnL;
  const realized = m.realizedPnL;
  const dividend = m.dividendPnL;
  const fxPnL = m.fxPnL;
  const pureStock = m.pureStockPnL;
  const totalPnL = m.totalPnL;
  const totalReturn = m.returnPct;

  // E1 breakdown data — 총손익 = 주가손익 + 환차손익 + 배당 (환차 막대는 항상 표시, 제외 시 0)
  const breakdownData = [
    { label: "주가 손익", value: pureStock, color: "#00d4a1" },
    { label: "환차손익", value: fxPnL, color: "#fbbf24" },
    { label: "배당", value: dividend, color: "#a78bfa" },
  ].filter((entry): entry is { label: string; value: number; color: string } => entry.value != null)
    .filter(entry => opts.includeDividend || entry.label !== "배당");
  const chartData = [
    { name: "주가 손익", amount: pureStock, color: "#00d4a1" },
    { name: "환차손익", amount: fxPnL, color: "#fbbf24" },
    { name: "실현 손익", amount: realized, color: "#4f8cff" },
    { name: "배당", amount: dividend, color: "#a78bfa" },
  ].filter((entry): entry is { name: string; amount: number; color: string } => entry.amount != null)
    .map(entry => ({ ...entry, value: entry.amount / 1_000_000 }));

  return (
    <div className="space-y-6">
      <AnalysisNotice analysis={analysis} />
      {/* E2 Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "총 손익", value: totalPnL, isKRW: true, positive: (totalPnL ?? 0) >= 0 },
          { label: "총 수익률", value: totalReturn, isKRW: false, positive: (totalReturn ?? 0) >= 0 },
          { label: "평가손익", value: unrealized, isKRW: true, positive: (unrealized ?? 0) >= 0 },
          { label: "실현손익", value: realized, isKRW: true, positive: (realized ?? 0) >= 0 },
        ].map(k => (
          <Card key={k.label} className="p-5">
            <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono mb-3">{k.label}</div>
            <div className={`font-['DM_Serif_Display',serif] text-2xl ${k.positive ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
              {k.value == null ? "—" : k.isKRW ? `${k.value >= 0 ? "+" : ""}${formatKRW(k.value)}` : `${k.value >= 0 ? "+" : ""}${k.value.toFixed(2)}%`}
            </div>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* E1 P&L Breakdown */}
        <Card>
          <CardHeader title="손익 구성 분해" sub="E1: 주가손익 + 환차손익 + 배당 = 총손익" />
          <div className="p-5 space-y-3">
            {breakdownData.map(d => (
              <div key={d.label}>
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-sm" style={{ background: d.color }} />
                    <span className="text-sm text-[#a0a8c0]">{d.label}</span>
                  </div>
                  <PnLText value={d.value} />
                </div>
                <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{
                    width: `${Math.min(100, Math.abs(d.value) / (breakdownData.reduce((total, item) => total + Math.abs(item.value), 0) || 1) * 100)}%`,
                    background: d.color,
                    opacity: d.value < 0 ? 0.5 : 1
                  }} />
                </div>
              </div>
            ))}
            <div className="pt-3 border-t border-white/7 flex items-center justify-between">
              <span className="text-sm text-[#a0a8c0]">합계</span>
              <PnLText value={totalPnL} />
            </div>
          </div>
        </Card>

        {/* E5 Pure stock vs FX */}
        <Card>
          <CardHeader title="주가 손익 vs 환차손익" sub="E5: 순수 주가성과 분리" />
          <div className="p-5">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                <XAxis dataKey="name" tick={{ fill: "#6b7494", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#6b7494", fontSize: 10, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} unit="M" />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" name="손익(백만원)" radius={[2, 2, 0, 0]}>
                  {chartData.map(entry => (
                    <Cell key={entry.name} fill={entry.amount >= 0 ? entry.color : "#ff5c6a"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* E3 Per-stock */}
      <Card>
        <CardHeader title="종목별 성과" sub="E3: 투자원금·손익·수익률·상태" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {["종목", "상태", "투자원가", "평가손익", "실현손익", opts.includeDividend ? "배당" : null, "총손익", "수익률"].filter(Boolean).map(h => (
                  <th key={h!} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...rows].map(s => {
                const div = opts.includeDividend ? s.dividend : 0;
                const total = s.unrealizedPnL == null || s.realizedPnL == null || div == null
                  ? null : s.unrealizedPnL + s.realizedPnL + div;
                return { s, div, total };
              }).sort((first, second) => (second.total ?? -Infinity) - (first.total ?? -Infinity)).map(({ s, div, total }, i) => {
                const holding = s.status !== "청산";
                return (
                  <tr key={s.ticker} className={`border-b border-white/4 hover:bg-white/3 transition-colors ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                      <div className="text-xs text-[#6b7494]">{s.name}</div>
                      {s.analysis && !["complete", "partial"].includes(s.analysis.status) && <div className="text-xs text-[#fbbf24] mt-1" title={s.analysis.warnings.join("\n")}>성과 계산 불가</div>}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-mono px-1.5 py-0.5 rounded-sm ${holding ? "bg-[#00d4a1]/10 text-[#00d4a1]" : "bg-white/5 text-[#6b7494]"}`}>
                        {holding ? "보유" : "청산"}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{formatKRW(s.buyTotal, true)}</td>
                    <td className="px-4 py-3"><PnLText value={s.unrealizedPnL} /></td>
                    <td className="px-4 py-3"><PnLText value={s.realizedPnL} /></td>
                    {opts.includeDividend && <td className="px-4 py-3"><PnLText value={div} /></td>}
                    <td className="px-4 py-3"><PnLText value={total} /></td>
                    <td className="px-4 py-3"><ReturnBadge value={s.returnPct} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
