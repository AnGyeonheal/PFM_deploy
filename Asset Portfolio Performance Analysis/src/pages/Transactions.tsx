import { useState, useEffect } from "react";
import { Card, CardHeader } from "../components/Shared";

type Tab = "transactions" | "dividends";
type Tx = { date: string; ticker: string; name: string; market: string; type: string; quantity: number; price: number; currency: string; broker: string; account?: string; source?: "manual" | "toss"; sourceId?: string; revision?: string; edited?: boolean; deleted?: boolean; reset?: boolean };
type Div = { date: string; ticker: string; name: string; amount: number; currency: string; broker: string; account?: string; exDate?: string; recordDate?: string; eventId?: string };
type EstDiv = Div & { shares?: number | null; dateSource?: string; status?: string };
type Snap = { id: string; label: string; time: string; tx: number; div: number };

const emptyTx = (): Tx => ({ date: "", ticker: "", name: "", market: "", type: "buy", quantity: 0, price: 0, currency: "KRW", broker: "", account: "", source: "manual" });
const emptyDiv = (): Div => ({ date: "", ticker: "", name: "", amount: 0, currency: "KRW", broker: "", account: "", exDate: "", recordDate: "", eventId: "" });

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
  const [saveError, setSaveError] = useState("");

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
    const payload = await r.json();
    if (!r.ok || !payload.ok) throw new Error(payload.error || "저장에 실패했습니다.");
    return payload;
  };

  const saveTransactions = async () => {
    setSaving(true); setSaveError(""); setMsg("");
    try {
      const j = await post("/api/app/edit/transactions", { rows: transactions });
      if (!j.ok) throw new Error();
      flash(`거래 ${j.count}건 저장됨`);
      load();
    } catch (error) { setSaveError(error instanceof Error ? error.message : "저장 실패"); } finally { setSaving(false); }
  };

  const saveDividends = async () => {
    setSaving(true); setSaveError(""); setMsg("");
    try {
      const j = await post("/api/app/edit/dividends", { rows: dividends });
      if (!j.ok) throw new Error();
      flash(`배당 ${j.count}건 저장됨`);
      load();
    } catch (error) { setSaveError(error instanceof Error ? error.message : "저장 실패"); } finally { setSaving(false); }
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
    setDividends(prev => e.eventId && prev.some(row => row.eventId === e.eventId) ? prev : [...prev, { ...e }]);
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
      {saveError && <div role="alert" className="text-sm text-[#ff5c6a] space-y-2">
        <p>{saveError}</p>
        <button disabled={saving} title="미저장 변경을 취소하고 최신 데이터를 불러옵니다." onClick={() => { setSaveError(""); setMsg(""); load(); }} className="text-xs text-[#4f8cff]">다시 불러오기</button>
      </div>}
      {msg && (
        <div role="status" className="fixed top-4 right-4 z-50 bg-[#00d4a1] text-[#0a0d14] text-sm font-medium px-4 py-2 rounded-sm shadow-lg">{msg}</div>
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
          <CardHeader title="거래 내역 편집" sub="임포트 · 토스 API" />
          <div className="p-5">
            <div className="overflow-x-auto">
              <table aria-label="전체 출처 거래 편집" className="w-full min-w-[1280px] text-sm">
                <thead>
                  <tr className="border-b border-white/7">
                    {["출처", "날짜", "티커", "종목명", "시장", "유형", "수량", "단가", "통화", "증권사", "계좌", ""].map(h => (
                      <th key={h} className="px-2 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((t, i) => (
                    <tr key={t.sourceId || `manual-${i}`} className={`border-b border-white/4 ${t.deleted || t.reset ? "opacity-60" : ""}`}>
                      <td className="px-2 py-1 text-xs whitespace-nowrap"><div className={t.source === "toss" ? "text-[#4f8cff]" : "text-[#a0a8c0]"}>{t.source === "toss" ? "토스 API" : "임포트"}</div><div className="text-[#6b7494]">{t.reset ? "복원 예정" : t.deleted ? "제외됨" : t.edited ? "수정 적용" : ""}</div></td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} aria-label={`거래 ${i + 1} 날짜`} className={inputCls} type="date" value={t.date} onChange={e => updTx(i, "date", e.target.value)} /></td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} className={inputCls} value={t.ticker} onChange={e => updTx(i, "ticker", e.target.value)} placeholder="AAPL / 005930" /></td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} className={inputCls} value={t.name} onChange={e => updTx(i, "name", e.target.value)} /></td>
                      <td className="px-1 py-1">
                        <select disabled={saving || t.deleted || t.reset} className={inputCls} value={t.market} onChange={e => updTx(i, "market", e.target.value)}>
                          <option value="">-</option><option value="KOSPI">KOSPI</option><option value="KOSDAQ">KOSDAQ</option><option value="US">US</option>
                        </select>
                      </td>
                      <td className="px-1 py-1">
                        <select disabled={saving || t.deleted || t.reset} className={inputCls} value={t.type} onChange={e => updTx(i, "type", e.target.value)}>
                          <option value="buy">매수</option><option value="sell">매도</option>
                        </select>
                      </td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} aria-label={`거래 ${i + 1} 수량`} className={inputCls} type="number" step="any" value={t.quantity} onChange={e => updTx(i, "quantity", parseFloat(e.target.value) || 0)} /></td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} aria-label={`거래 ${i + 1} 단가`} className={inputCls} type="number" step="any" value={t.price} onChange={e => updTx(i, "price", parseFloat(e.target.value) || 0)} /></td>
                      <td className="px-1 py-1">
                        <select disabled={saving || t.deleted || t.reset} className={inputCls} value={t.currency} onChange={e => updTx(i, "currency", e.target.value)}>
                          <option value="KRW">KRW</option><option value="USD">USD</option>
                        </select>
                      </td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} className={inputCls} value={t.broker} onChange={e => updTx(i, "broker", e.target.value)} placeholder="증권사" /></td>
                      <td className="px-1 py-1"><input disabled={saving || t.deleted || t.reset} className={inputCls} value={t.account ?? ""} onChange={e => updTx(i, "account", e.target.value)} aria-label={`거래 ${i + 1} 계좌`} title="동일 증권사 내 계좌 식별자" /></td>
                      <td className="px-1 py-1 text-center whitespace-nowrap">
                        <button disabled={saving || t.deleted || t.reset} onClick={() => t.source === "toss" ? updTx(i, "deleted", true) : setTransactions(prev => prev.filter((_, idx) => idx !== i))}
                          className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono disabled:opacity-40">{t.source === "toss" ? "제외" : "삭제"}</button>
                        {t.source === "toss" && <button disabled={saving} onClick={() => setTransactions(prev => prev.map((row, index) => index === i ? { ...row, reset: !row.reset } : row))}
                          title="저장하면 토스 원본 거래로 복원됩니다." className="block text-xs text-[#4f8cff] font-mono mt-1">{t.reset ? "복원 취소" : "원본 복원"}</button>}
                      </td>
                    </tr>
                  ))}
                  {transactions.length === 0 && (
                    <tr><td colSpan={12} className="px-2 py-6 text-center text-xs text-[#6b7494] font-mono">거래 내역이 없습니다.</td></tr>
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
              <CardHeader title="추정 배당·분배금" sub="세전 추정액 · 수령일 미확인/미도래분은 수령 손익에서 제외" />
              <div className="p-5 space-y-2">
                {estimated.map((e, i) => (
                  <div key={e.eventId || i} className="grid grid-cols-1 sm:grid-cols-[1fr_1.2fr_auto] gap-3 border-b border-white/7 py-3 text-xs" aria-label={`${e.ticker} 추정 배당`}>
                    <div className="min-w-0 break-words"><div className="font-mono text-[#00d4a1]">{e.ticker}</div><div className="text-[#a0a8c0]">{e.name}</div><div className="text-[#6b7494] break-all">{e.broker} · {e.account || "계좌 미지정"}</div></div>
                    <div className="min-w-0 text-[#a0a8c0] space-y-1">
                      <div>수령일: {e.date || "미확인"} · {e.dateSource === "announced" ? "공시" : e.dateSource === "estimated" ? "예상" : "정보 없음"}</div>
                      <div title="일반 배당은 배당락일 직전 보유수량으로 권리를 계산합니다. 배당락일 매수는 제외됩니다.">배당락일: {e.exDate || "미확인"} · 권리수량 {e.shares ?? "—"}</div>
                      <div>기준일: {e.recordDate || "제공 안 됨"}</div>
                      <div className="text-[#6b7494]">{e.status}</div>
                    </div>
                    <div className="text-right sm:min-w-32"><div className="font-mono text-[#e8eaf0]">{e.currency === "USD" ? "$" : ""}{e.amount.toLocaleString(undefined, { maximumFractionDigits: 2 })}{e.currency === "KRW" ? "원" : ""}</div>
                      <button disabled={saving} onClick={() => confirmEstimated(e, i)} className="mt-2 text-xs text-[#00d4a1]/80 hover:text-[#00d4a1] font-mono">입금 내역으로 추가</button>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <Card>
            <CardHeader title="배당 내역 편집" sub="C2: 배당 추가·수정·삭제" />
            <div className="p-5">
              <div className="overflow-x-auto">
                <table aria-label="실제 배당 입금 편집" className="w-full min-w-[1050px] text-sm">
                  <thead>
                    <tr className="border-b border-white/7">
                      {["수령일", "배당락일", "기준일", "티커", "종목명", "통화", "실제 입금액", "증권사", "계좌", ""].map(h => (
                        <th key={h} className="px-2 py-2 text-left text-[11px] text-[#6b7494] font-mono uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dividends.map((d, i) => (
                      <tr key={i} className="border-b border-white/4">
                        <td className="px-1 py-1"><input aria-label={`배당 ${i + 1} 수령일`} className={inputCls} type="date" value={d.date} onChange={e => updDiv(i, "date", e.target.value)} /></td>
                        <td className="px-1 py-1"><input aria-label={`배당 ${i + 1} 배당락일`} className={inputCls} type="date" value={d.exDate || ""} onChange={e => updDiv(i, "exDate", e.target.value)} /></td>
                        <td className="px-1 py-1"><input aria-label={`배당 ${i + 1} 기준일`} className={inputCls} type="date" value={d.recordDate || ""} onChange={e => updDiv(i, "recordDate", e.target.value)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.ticker} onChange={e => updDiv(i, "ticker", e.target.value)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.name} onChange={e => updDiv(i, "name", e.target.value)} /></td>
                        <td className="px-1 py-1">
                          <select className={inputCls} value={d.currency} onChange={e => updDiv(i, "currency", e.target.value)}>
                            <option value="KRW">KRW</option><option value="USD">USD</option>
                          </select>
                        </td>
                        <td className="px-1 py-1"><input aria-label={`배당 ${i + 1} 입금액`} className={inputCls} type="number" step="any" value={d.amount} onChange={e => updDiv(i, "amount", parseFloat(e.target.value) || 0)} /></td>
                        <td className="px-1 py-1"><input className={inputCls} value={d.broker} onChange={e => updDiv(i, "broker", e.target.value)} /></td>
                        <td className="px-1 py-1"><input aria-label={`배당 ${i + 1} 계좌`} className={inputCls} value={d.account || ""} onChange={e => updDiv(i, "account", e.target.value)} /></td>
                        <td className="px-1 py-1 text-center">
                          <button onClick={() => setDividends(prev => prev.filter((_, idx) => idx !== i))}
                            className="text-xs text-[#ff5c6a]/60 hover:text-[#ff5c6a] font-mono">삭제</button>
                        </td>
                      </tr>
                    ))}
                    {dividends.length === 0 && (
                      <tr><td colSpan={10} className="px-2 py-6 text-center text-xs text-[#6b7494] font-mono">배당 기록이 없습니다.</td></tr>
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
