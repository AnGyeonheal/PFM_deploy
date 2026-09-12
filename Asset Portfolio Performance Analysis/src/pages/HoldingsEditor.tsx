import { useState, useEffect } from "react";
import { Card, CardHeader, formatKRW } from "../components/Shared";

type Stock = {
  ticker: string; name: string; currency: string; quantity: number;
  currentPrice: number | null; avgPrice: number; unrealizedPnL: number | null; returnPct: number | null; status: string;
};

const inputCls = "w-full bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1.5 text-xs text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors";

export default function HoldingsEditor() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => {
    setLoading(true);
    fetch("/api/app/dashboard?div=1&fx=1", { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(j => { setStocks((j?.stocks || []).filter((s: Stock) => s.status === "보유중")); setEdits({}); })
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const upd = (tk: string, k: string, v: string) => setEdits(e => ({ ...e, [tk]: { ...(e[tk] || {}), [k]: v } }));
  const val = (s: Stock, k: keyof Stock) => {
    const e = edits[s.ticker]?.[k];
    return e !== undefined ? e : (s[k] ?? "");
  };
  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 2500); };

  const save = async () => {
    const rows = Object.keys(edits).map(tk => {
      const s = stocks.find(x => x.ticker === tk)!;
      const cur = String(val(s, "currentPrice"));
      return {
        티커: tk, 종목명: String(val(s, "name")), 통화: s.currency,
        수량: parseFloat(String(val(s, "quantity"))) || 0,
        평단가: parseFloat(String(val(s, "avgPrice"))) || 0,
        현재가: cur === "" ? "" : parseFloat(cur),
      };
    }).filter(r => r.티커);
    if (!rows.length) { flash("변경 사항이 없습니다"); return; }
    setSaving(true);
    try {
      const r = await fetch("/holdings/override", {
        method: "POST", headers: { "Content-Type": "application/json" },
        credentials: "include", body: JSON.stringify({ rows }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error();
      flash(`${j.count}개 종목 수정됨`);
      load();
    } catch { flash("저장 실패"); } finally { setSaving(false); }
  };

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center">불러오는 중…</div>;

  return (
    <Card>
      {msg && <div className="fixed top-4 right-4 z-50 bg-[#00d4a1] text-[#0a0d14] text-sm font-medium px-4 py-2 rounded-sm shadow-lg">{msg}</div>}
      <CardHeader title="종목별 관리" sub="보유 수량·평단가·현재가·종목명을 수정하면 전체 성과가 재계산됩니다 (토스 API 종목 포함)" />
      <div className="p-5">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/7">
                {["종목명", "티커", "통화", "수량", "평단가", "현재가", "평가손익", "수익률"].map(h => (
                  <th key={h} className="px-2 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stocks.map(s => (
                <tr key={s.ticker} className="border-b border-white/4">
                  <td className="px-1 py-1" style={{ minWidth: 120 }}><input className={inputCls} value={String(val(s, "name"))} onChange={e => upd(s.ticker, "name", e.target.value)} /></td>
                  <td className="px-2 py-1 font-mono text-xs text-[#00d4a1] whitespace-nowrap">{s.ticker}</td>
                  <td className="px-2 py-1 font-mono text-xs text-[#6b7494]">{s.currency}</td>
                  <td className="px-1 py-1" style={{ minWidth: 90 }}><input className={inputCls + " text-end"} type="number" step="any" value={String(val(s, "quantity"))} onChange={e => upd(s.ticker, "quantity", e.target.value)} /></td>
                  <td className="px-1 py-1" style={{ minWidth: 100 }}><input className={inputCls + " text-end"} type="number" step="any" value={String(val(s, "avgPrice"))} onChange={e => upd(s.ticker, "avgPrice", e.target.value)} /></td>
                  <td className="px-1 py-1" style={{ minWidth: 100 }}><input className={inputCls + " text-end"} type="number" step="any" value={String(val(s, "currentPrice"))} onChange={e => upd(s.ticker, "currentPrice", e.target.value)} /></td>
                  <td className={`px-2 py-1 font-mono text-xs text-end whitespace-nowrap ${s.unrealizedPnL == null ? "text-[#6b7494]" : s.unrealizedPnL >= 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>{formatKRW(s.unrealizedPnL, true)}</td>
                  <td className={`px-2 py-1 font-mono text-xs text-end whitespace-nowrap ${s.returnPct == null ? "text-[#6b7494]" : s.returnPct >= 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>{s.returnPct == null ? "—" : `${s.returnPct >= 0 ? "+" : ""}${s.returnPct.toFixed(2)}%`}</td>
                </tr>
              ))}
              {stocks.length === 0 && (
                <tr><td colSpan={8} className="px-2 py-6 text-center text-xs text-[#6b7494] font-mono">보유 종목이 없습니다. '거래·배당 수정' 탭에서 거래를 입력하세요.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between mt-4">
          <p className="text-xs text-[#6b7494] font-mono">수정한 종목은 해당 거래가 입력값 1건으로 대체되어 성과에 반영됩니다.</p>
          <button onClick={save} disabled={saving} className="text-xs font-mono px-5 py-2 bg-[#00d4a1] text-[#0a0d14] font-semibold rounded-sm hover:bg-[#00d4a1]/90 transition-colors disabled:opacity-50">{saving ? "저장 중…" : "종목 수정 저장"}</button>
        </div>
      </div>
    </Card>
  );
}
