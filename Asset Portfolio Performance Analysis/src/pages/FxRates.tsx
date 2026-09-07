import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Card, CardHeader, CustomTooltip, formatKRW, PnLText } from "../components/Shared";

type FxStock = { ticker: string; name: string; avgBuyFx: number | null; evalKrw: number; fxPnL: number };
type FxData = { currentFx: number; avgBuyFx: number | null; fxPnlTotal: number; history: { month: string; fx: number; avgBuy?: number }[]; stocks: FxStock[] };

export default function FxRates() {
  const [d, setD] = useState<FxData | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch("/api/app/fx", { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("데이터를 불러오지 못했습니다"); return r.json(); })
      .then(j => { setD(j); setErr(""); })
      .catch(e => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center">불러오는 중…</div>;
  if (err) return <div className="text-[#ff5c6a] text-sm py-20 text-center">{err}</div>;
  if (!d) return null;

  const currentFx = d.currentFx;
  const avgBuyFx = d.avgBuyFx || 0;
  const fxGainPct = avgBuyFx ? ((currentFx - avgBuyFx) / avgBuyFx) * 100 : 0;
  const usdStocks = d.stocks;
  const totalFxGain = d.fxPnlTotal;
  const fxData = d.history;

  return (
    <div className="space-y-6">
      {/* H1/H2 Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "현재 환율", value: `${currentFx.toLocaleString()}원`, sub: "USD/KRW" },
          { label: "달러 평단가", value: `${avgBuyFx.toLocaleString()}원`, sub: "H2: 보유분 가중평균" },
          { label: "환차 효과", value: `${fxGainPct >= 0 ? "+" : ""}${fxGainPct.toFixed(2)}%`, sub: "현재환율 vs 평단가", positive: fxGainPct >= 0 },
          { label: "누적 환차손익", value: (totalFxGain >= 0 ? "+" : "") + formatKRW(totalFxGain), sub: "달러 자산 기준", positive: totalFxGain >= 0 },
        ].map(k => (
          <Card key={k.label} className="p-5">
            <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono mb-3">{k.label}</div>
            <div className={`font-['DM_Serif_Display',serif] text-2xl ${k.positive === undefined ? "text-[#e8eaf0]" : k.positive ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
              {k.value}
            </div>
            <div className="text-xs text-[#6b7494] mt-2 font-mono">{k.sub}</div>
          </Card>
        ))}
      </div>

      {/* H1 FX chart */}
      <Card>
        <CardHeader title="USD/KRW 환율 추이" sub="H1: 달러 평단가 비교" />
        <div className="p-5">
          <div className="flex items-center gap-4 mb-4 text-xs font-mono text-[#6b7494]">
            <div className="flex items-center gap-2"><span className="w-4 h-0.5 bg-[#fbbf24] inline-block" /><span>환율</span></div>
            <div className="flex items-center gap-2"><span className="w-4 h-0.5 bg-[#4f8cff] inline-block" style={{ borderTop: "2px dashed #4f8cff" }} /><span>달러 평단가</span></div>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={fxData} margin={{ top: 4, right: 4, bottom: 0, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="month" tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} domain={[1280, 1370]} unit="원" />
              <Tooltip content={<CustomTooltip />} />
              <Line type="monotone" dataKey="fx" stroke="#fbbf24" strokeWidth={2} dot={false} name="환율" activeDot={{ r: 4 }} />
              <Line type="monotone" dataKey="avgBuy" stroke="#4f8cff" strokeWidth={1.5} dot={false} name="평단가" strokeDasharray="5 3" activeDot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>

      {/* Per-stock FX analysis */}
      <Card>
        <CardHeader title="종목별 환차손익" sub="보유분 가중평균 매수환율 기준" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {["종목", "매수환율", "현재환율", "환율차이", "환차손익"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usdStocks.map((s, i) => {
                const abf = s.avgBuyFx || 0;
                const fxDiff = currentFx - abf;
                return (
                  <tr key={s.ticker} className={`border-b border-white/4 hover:bg-white/3 transition-colors ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{s.ticker}</div>
                      <div className="text-xs text-[#6b7494]">{s.name}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{abf ? abf.toLocaleString() : "—"}원</td>
                    <td className="px-4 py-3 font-mono text-xs text-[#e8eaf0]">{currentFx.toLocaleString()}원</td>
                    <td className="px-4 py-3">
                      <span className={`font-mono text-xs ${fxDiff >= 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
                        {fxDiff >= 0 ? "+" : ""}{fxDiff.toFixed(1)}원
                      </span>
                    </td>
                    <td className="px-4 py-3"><PnLText value={s.fxPnL} /></td>
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
