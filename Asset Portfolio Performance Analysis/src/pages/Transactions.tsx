import { useState, useEffect } from "react";
import { Card, CardHeader, formatKRW } from "../components/Shared";

type Tab = "transactions" | "dividends";

type Tx = { date: string; ticker: string; name: string; type: string; quantity: number; price: number; currency: string; amount: number; broker: string };
type Div = { date: string; ticker: string; name: string; amount: number; currency: string; amountKRW: number; verified: boolean; status: string };

const TYPE_LABEL: Record<string, string> = { buy: "매수", sell: "매도", dividend: "배당" };
const TYPE_COLOR: Record<string, string> = { buy: "#00d4a1", sell: "#ff5c6a", dividend: "#a78bfa" };

export default function Transactions() {
  const [tab, setTab] = useState<Tab>("transactions");
  const [showAdd, setShowAdd] = useState(false);
  const [transactions, setTransactions] = useState<Tx[]>([]);
  const [dividends, setDividends] = useState<Div[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch("/api/app/transactions", { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("데이터를 불러오지 못했습니다"); return r.json(); })
      .then(d => { setTransactions(d.transactions || []); setDividends(d.dividends || []); setErr(""); })
      .catch(e => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      {/* Tab */}
      <div className="flex items-center gap-1 border-b border-white/7">
        {(["transactions", "dividends"] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === t ? "border-[#00d4a1] text-[#00d4a1]" : "border-transparent text-[#6b7494] hover:text-[#a0a8c0]"}`}>
            {t === "transactions" ? "거래 내역" : "배당 내역"}
          </button>
        ))}
        <button onClick={() => setShowAdd(true)}
          className="ml-auto mb-1 text-xs font-mono px-3 py-1.5 bg-[#00d4a1]/15 text-[#00d4a1] rounded-sm hover:bg-[#00d4a1]/25 transition-colors">
          + 추가
        </button>
      </div>

      {/* Add modal (C1/C2) */}
      {showAdd && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center px-4" onClick={() => setShowAdd(false)}>
          <div className="bg-[#111520] border border-white/10 rounded-sm p-6 w-full max-w-md" onClick={e => e.stopPropagation()}>
            <div className="text-xs text-[#6b7494] font-mono uppercase tracking-widest mb-5">
              {tab === "transactions" ? "거래 추가 (C1)" : "배당 추가 (C2)"}
            </div>
            <div className="space-y-4">
              {[
                { label: "날짜", type: "date", placeholder: "2024-12-01" },
                { label: "티커", type: "text", placeholder: "AAPL" },
                { label: tab === "transactions" ? "유형" : "금액", type: "text", placeholder: tab === "transactions" ? "buy / sell" : "0" },
                { label: "수량", type: "number", placeholder: "0" },
                { label: "단가", type: "number", placeholder: "0" },
              ].map(f => (
                <div key={f.label}>
                  <label className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-1.5">{f.label}</label>
                  <input type={f.type} placeholder={f.placeholder}
                    className="w-full bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors" />
                </div>
              ))}
            </div>
            <div className="flex gap-3 mt-6">
              <button className="flex-1 bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm py-2.5 rounded-sm hover:bg-[#00d4a1]/90 transition-colors">저장</button>
              <button onClick={() => setShowAdd(false)} className="flex-1 border border-white/10 text-[#a0a8c0] text-sm py-2.5 rounded-sm hover:border-white/20 transition-colors">취소</button>
            </div>
          </div>
        </div>
      )}

      {tab === "transactions" && (
        <Card>
          <CardHeader title="거래 내역" sub="C1: 조회·추가·수정·삭제" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/7">
                  {["날짜", "종목", "유형", "수량", "단가", "금액(원)", "출처", ""].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {transactions.map((t, i) => (
                  <tr key={`tx-${i}`} className={`border-b border-white/4 hover:bg-white/3 transition-colors group ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3 font-mono text-xs text-[#6b7494]">{t.date}</td>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{t.ticker}</div>
                      <div className="text-xs text-[#6b7494]">{t.name}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded-sm" style={{ color: TYPE_COLOR[t.type], background: TYPE_COLOR[t.type] + "15" }}>
                        {TYPE_LABEL[t.type]}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">{t.quantity || "—"}</td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">
                      {t.price ? (t.currency === "USD" ? `$${t.price}` : `${t.price.toLocaleString()}원`) : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#e8eaf0]">{formatKRW(t.amount, true)}</td>
                    <td className="px-4 py-3">
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded-sm bg-white/5 text-[#6b7494]">{t.broker || "—"}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button className="text-xs text-[#a0a8c0] hover:text-[#e8eaf0] font-mono">수정</button>
                        <button className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono">삭제</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {tab === "dividends" && (
        <Card>
          <CardHeader title="배당 내역" sub="C2: 추정 배당 → 검증 확정 전환" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/7">
                  {["날짜", "종목", "주당배당", "배당금(원)", "검증상태", ""].map(h => (
                    <th key={h} className="px-4 py-3 text-left text-xs text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dividends.map((d, i) => (
                  <tr key={`div-${i}`} className={`border-b border-white/4 hover:bg-white/3 transition-colors group ${i % 2 === 0 ? "" : "bg-white/[0.015]"}`}>
                    <td className="px-4 py-3 font-mono text-xs text-[#6b7494]">{d.date}</td>
                    <td className="px-4 py-3">
                      <div className="font-mono text-xs text-[#00d4a1]">{d.ticker}</div>
                      <div className="text-xs text-[#6b7494]">{d.name}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#a0a8c0]">
                      {d.currency === "USD" ? `$${d.amount}` : `${d.amount.toLocaleString()}원`}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-[#e8eaf0]">{formatKRW(d.amountKRW, true)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-mono px-1.5 py-0.5 rounded-sm ${d.verified ? "bg-[#00d4a1]/10 text-[#00d4a1]" : "bg-[#fbbf24]/10 text-[#fbbf24]"}`}>
                        {d.verified ? "검증됨" : "추정"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        {!d.verified && <button className="text-xs text-[#00d4a1]/70 hover:text-[#00d4a1] font-mono">확정</button>}
                        <button className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono">삭제</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* C5 Snapshot notice */}
      <div className="flex items-center gap-3 bg-[#1a2035] border border-white/5 rounded-sm px-4 py-3 text-xs font-mono text-[#6b7494]">
        <span className="text-[#4f8cff]">C5</span>
        삭제·편집 전 자동 스냅샷이 저장됩니다. &nbsp;
        <button className="text-[#4f8cff] hover:text-[#4f8cff]/80 underline">스냅샷 복구</button>
        &nbsp;|&nbsp;
        <button className="text-[#6b7494] hover:text-[#a0a8c0] underline">원본 데이터 원장 보기 (C6)</button>
      </div>
    </div>
  );
}
