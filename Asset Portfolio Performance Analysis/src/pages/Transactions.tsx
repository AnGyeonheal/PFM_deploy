import { useState, useEffect } from "react";
import { Card, CardHeader } from "../components/Shared";

type Tab = "transactions" | "dividends";
type Tx = { date: string; ticker: string; name: string; market: string; type: string; quantity: number; price: number; currency: string; broker: string; account?: string };
type Div = { date: string; ticker: string; name: string; amount: number; currency: string; broker: string };
type EstDiv = { date: string; ticker: string; name: string; amount: number; currency: string };
type Snap = { id: string; label: string; time: string; tx: number; div: number };

const emptyTx = (): Tx => ({ date: "", ticker: "", name: "", market: "", type: "buy", quantity: 0, price: 0, currency: "KRW", broker: "", account: "" });
const emptyDiv = (): Div => ({ date: "", ticker: "", name: "", amount: 0, currency: "KRW", broker: "" });

const inputCls = "w-full bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1.5 text-xs text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors";

export default function Transactions() {
  const [tab, setTab] = useState<Tab>("transactions");
  const [transactions, setTransactions] = useState<Tx[]>([]);
  const [dividends, setDividends] = useState<Div[]>([]);
  const [estimated, setEstimated] = useState<EstDiv[]>([]);
  const [snapshots, setSnapshots] = useState<Snap[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () => {
    setLoading(true);
    fetch("/api/app/edit/data", { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("데이터를 불러오지 못했습니다"); return r.json(); })
      .then(d => {
        setTransactions(d.transactions || []);
        setDividends(d.dividends || []);
        setEstimated(d.estimatedDividends || []);
        setSnapshots(d.snapshots || []);
        setErr("");
      })
      .catch(e => setErr(String(e.message || e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const flash = (t: string) => { setMsg(t); setTimeout(() => setMsg(""), 3000); };

  const post = async (url: string, body: any) => {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "include", body: JSON.stringify(body),
    });
    return r.json();
  };

  const saveTransactions = async () => {
    setSaving(true);
    try {
      const j = await post("/api/app/edit/transactions", { rows: transactions });
      if (!j.ok) throw new Error();
      flash(`거래 ${j.count}건 저장됨`);
      load();
    } catch { flash("저장 실패"); } finally { setSaving(false); }
  };

  const saveDividends = async () => {
    setSaving(true);
    try {
      const j = await post("/api/app/edit/dividends", { rows: dividends });
      if (!j.ok) throw new Error();
      flash(`배당 ${j.count}건 저장됨`);
      load();
    } catch { flash("저장 실패"); } finally { setSaving(false); }
  };

  const restore = async (snapId: string) => {
    if (!window.confirm("이 시점으로 복구할까요? 현재 상태는 자동 백업됩니다.")) return;
    try {
      const j = await post("/api/app/edit/restore", { snapId });
      if (j.ok) { flash("복구되었습니다"); load(); }
      else flash("복구할 백업을 찾지 못했습니다");
    } catch { flash("복구 실패"); }
  };

  // 추정 배당 → 편집 목록으로 확정(이동). 저장 시 검증 배당으로 기록됨.
  const confirmEstimated = (e: EstDiv, idx: number) => {
    setDividends(prev => [...prev, { ...e, broker: "" }]);
    setEstimated(prev => prev.filter((_, i) => i !== idx));
    setTab("dividends");
  };

  const updTx = (i: number, k: keyof Tx, v: any) =>
    setTransactions(prev => prev.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));
  const updDiv = (i: number, k: keyof Div, v: any) =>
    setDividends(prev => prev.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center">불러오는 중…</div>;
  if (err) return <div className="text-[#ff5c6a] text-sm py-20 text-center">{err}</div>;

  return (
    <div className="space-y-6">
      {msg && (
        <div className="fixed top-4 right-4 z-50 bg-[#00d4a1] text-[#0a0d14] text-sm font-medium px-4 py-2 rounded-sm shadow-lg">{msg}</div>
      )}

      <div className="flex items-center gap-1 border-b border-white/7">
        {(["transactions", "dividends"] as Tab[]).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === t ? "border-[#00d4a1] text-[#00d4a1]" : "border-transparent text-[#6b7494] hover:text-[#a0a8c0]"}`}>
            {t === "transactions" ? "거래 내역" : "배당 내역"}
          </button>
        ))}
      </div>

      {tab === "transactions" && (
        <Card>
          <CardHeader title="거래 내역 편집" sub="C1: 수동 거래 추가·수정·삭제 (토스 API 거래는 자동 수집·읽기전용)" />
          <div className="p-5">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1100px] text-sm">
                <thead>
                  <tr className="border-b border-white/7">
                    {["날짜", "티커", "종목명", "시장", "유형", "수량", "단가", "통화", "증권사", "계좌", ""].map(h => (
                      <th key={h} className="px-2 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((t, i) => (
                    <tr key={i} className="border-b border-white/4">
                      <td className="px-1 py-1"><input className={inputCls} type="date" value={t.date} onChange={e => updTx(i, "date", e.target.value)} /></td>
                      <td className="px-1 py-1"><input className={inputCls} value={t.ticker} onChange={e => updTx(i, "ticker", e.target.value)} placeholder="AAPL / 005930" /></td>
                      <td className="px-1 py-1"><input className={inputCls} value={t.name} onChange={e => updTx(i, "name", e.target.value)} /></td>
                      <td className="px-1 py-1">
                        <select className={inputCls} value={t.market} onChange={e => updTx(i, "market", e.target.value)}>
                          <option value="">-</option><option value="KOSPI">KOSPI</option><option value="KOSDAQ">KOSDAQ</option><option value="US">US</option>
                        </select>
                      </td>
                      <td className="px-1 py-1">
                        <select className={inputCls} value={t.type} onChange={e => updTx(i, "type", e.target.value)}>
                          <option value="buy">매수</option><option value="sell">매도</option>
                        </select>
                      </td>
                      <td className="px-1 py-1"><input className={inputCls} type="number" step="any" value={t.quantity} onChange={e => updTx(i, "quantity", parseFloat(e.target.value) || 0)} /></td>
                      <td className="px-1 py-1"><input className={inputCls} type="number" step="any" value={t.price} onChange={e => updTx(i, "price", parseFloat(e.target.value) || 0)} /></td>
                      <td className="px-1 py-1">
                        <select className={inputCls} value={t.currency} onChange={e => updTx(i, "currency", e.target.value)}>
                          <option value="KRW">KRW</option><option value="USD">USD</option>
                        </select>
                      </td>
                      <td className="px-1 py-1"><input className={inputCls} value={t.broker} onChange={e => updTx(i, "broker", e.target.value)} placeholder="증권사" /></td>
                      <td className="px-1 py-1"><input className={inputCls} value={t.account ?? ""} onChange={e => updTx(i, "account", e.target.value)} aria-label={`거래 ${i + 1} 계좌`} title="동일 증권사 내 계좌 식별자" /></td>
                      <td className="px-1 py-1 text-center">
                        <button onClick={() => setTransactions(prev => prev.filter((_, idx) => idx !== i))}
                          className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono">삭제</button>
                      </td>
                    </tr>
                  ))}
                  {transactions.length === 0 && (
                    <tr><td colSpan={11} className="px-2 py-6 text-center text-xs text-[#6b7494] font-mono">수동 거래가 없습니다. "거래 추가"로 입력하세요.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex gap-3 mt-4">
              <button onClick={() => setTransactions(prev => [...prev, emptyTx()])}
                className="text-xs font-mono px-3 py-2 bg-white/5 text-[#a0a8c0] rounded-sm hover:bg-white/10 transition-colors">+ 거래 추가</button>
              <button onClick={saveTransactions} disabled={saving}
                className="text-xs font-mono px-4 py-2 bg-[#00d4a1] text-[#0a0d14] font-semibold rounded-sm hover:bg-[#00d4a1]/90 transition-colors disabled:opacity-50">
                {saving ? "저장 중…" : "저장"}
              </button>
            </div>
          </div>
        </Card>
      )}

      {tab === "dividends" && (
        <>
          {estimated.length > 0 && (
            <Card>
              <CardHeader title="추정 배당" sub="C2: yfinance 기반 추정 · '확정'을 누르면 편집 목록으로 이동합니다" />
              <div className="p-5 space-y-2">
                {estimated.map((e, i) => (
                  <div key={i} className="flex items-center gap-3 bg-[#0a0d14] border border-white/5 rounded-sm px-3 py-2">
                    <span className="font-mono text-xs text-[#00d4a1] w-24">{e.ticker}</span>
                    <span className="text-xs text-[#a0a8c0] flex-1">{e.name}</span>
                    <span className="font-mono text-xs text-[#e8eaf0]">{e.currency === "USD" ? `$${e.amount}` : `${e.amount.toLocaleString()}원`}</span>
                    <button onClick={() => confirmEstimated(e, i)}
                      className="text-xs text-[#00d4a1]/80 hover:text-[#00d4a1] font-mono">확정 →</button>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card>
            <CardHeader title="배당 내역 편집" sub="C2: 배당 추가·수정·삭제" />
            <div className="p-5">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/7">
                      {["날짜", "티커", "종목명", "통화", "배당금", "증권사", ""].map(h => (
                        <th key={h} className="px-2 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dividends.map((d, i) => (
                      <tr key={i} className="border-b border-white/4">
                        <td className="px-1 py-1"><input className={inputCls} type="date" value={d.date} onChange={e => updDiv(i, "date", e.target.value)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.ticker} onChange={e => updDiv(i, "ticker", e.target.value)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.name} onChange={e => updDiv(i, "name", e.target.value)} /></td>
                        <td className="px-1 py-1">
                          <select className={inputCls} value={d.currency} onChange={e => updDiv(i, "currency", e.target.value)}>
                            <option value="KRW">KRW</option><option value="USD">USD</option>
                          </select>
                        </td>
                        <td className="px-1 py-1"><input className={inputCls} type="number" step="any" value={d.amount} onChange={e => updDiv(i, "amount", parseFloat(e.target.value) || 0)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.broker} onChange={e => updDiv(i, "broker", e.target.value)} /></td>
                        <td className="px-1 py-1 text-center">
                          <button onClick={() => setDividends(prev => prev.filter((_, idx) => idx !== i))}
                            className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono">삭제</button>
                        </td>
                      </tr>
                    ))}
                    {dividends.length === 0 && (
                      <tr><td colSpan={7} className="px-2 py-6 text-center text-xs text-[#6b7494] font-mono">배당 기록이 없습니다.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="flex gap-3 mt-4">
                <button onClick={() => setDividends(prev => [...prev, emptyDiv()])}
                  className="text-xs font-mono px-3 py-2 bg-white/5 text-[#a0a8c0] rounded-sm hover:bg-white/10 transition-colors">+ 배당 추가</button>
                <button onClick={saveDividends} disabled={saving}
                  className="text-xs font-mono px-4 py-2 bg-[#00d4a1] text-[#0a0d14] font-semibold rounded-sm hover:bg-[#00d4a1]/90 transition-colors disabled:opacity-50">
                  {saving ? "저장 중…" : "저장"}
                </button>
              </div>
            </div>
          </Card>
        </>
      )}

      <Card>
        <CardHeader title="스냅샷 복구" sub="C5: 편집·삭제 직전 자동 백업 시점으로 되돌리기" />
        <div className="p-5">
          {snapshots.length === 0 ? (
            <p className="text-xs text-[#6b7494] font-mono">복구 지점이 없습니다. 편집·저장 시 자동으로 백업됩니다.</p>
          ) : (
            <div className="space-y-1.5 max-h-64 overflow-auto">
              {snapshots.map(s => (
                <div key={s.id} className="flex items-center gap-3 bg-[#0a0d14] border border-white/5 rounded-sm px-3 py-2">
                  <span className="font-mono text-[11px] text-[#6b7494] w-36">{s.time}</span>
                  <span className="text-xs text-[#a0a8c0] flex-1">{s.label || "자동 백업"}</span>
                  <span className="font-mono text-[11px] text-[#6b7494]">거래 {s.tx} · 배당 {s.div}</span>
                  <button onClick={() => restore(s.id)}
                    className="text-xs text-[#4f8cff]/80 hover:text-[#4f8cff] font-mono">복구</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
