import { useState, useEffect, useRef } from "react";
import { Card, CardHeader } from "../components/Shared";

type Src = { name: string; count: number };
type DSData = { tossConnected: boolean; txCount: number; divCount: number; tickerCount: number; mappedCount: number; unmappedCount: number; sources: Src[] };
type ImportResult = { transactions: number; dividends: number; txPreview: any[]; divPreview: any[] };

export default function DataSources() {
  const [d, setD] = useState<DSData | null>(null);
  const [broker, setBroker] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [uploadErr, setUploadErr] = useState("");
  const [clearing, setClearing] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const loadData = () => {
    fetch("/api/app/datasources", { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(j => setD(j))
      .catch(() => {});
  };
  useEffect(() => { loadData(); }, []);

  const addFiles = (fl: FileList | null) => {
    if (!fl) return;
    setFiles(prev => [...prev, ...Array.from(fl)]);
  };

  const doUpload = async () => {
    if (files.length === 0) { setUploadErr("업로드할 파일을 선택하세요."); return; }
    setUploading(true); setUploadErr(""); setResult(null);
    const fd = new FormData();
    fd.append("broker", broker.trim() || "증권사");
    files.forEach(f => fd.append("files", f));
    try {
      const r = await fetch("/api/app/import", { method: "POST", body: fd, credentials: "include" });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.ok) {
        setResult(j);
        setFiles([]);
        loadData();
      } else {
        setUploadErr(j.error || "업로드/분석에 실패했습니다.");
      }
    } catch {
      setUploadErr("서버에 연결할 수 없습니다.");
    } finally {
      setUploading(false);
    }
  };

  const doClear = async (brokerName?: string) => {
    const label = brokerName ? `${brokerName} 임포트 데이터` : "전체 임포트 데이터";
    if (!window.confirm(`${label}를 삭제하시겠습니까?\n(삭제 내역은 백업되어 복구할 수 있습니다.)`)) return;
    setClearing(brokerName || "__all__");
    try {
      const fd = new FormData();
      if (brokerName) fd.append("broker", brokerName);
      const r = await fetch("/api/app/datasources/clear", { method: "POST", body: fd, credentials: "include" });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.ok) { setResult(null); loadData(); }
    } catch {
      /* noop */
    } finally {
      setClearing("");
    }
  };

  return (
    <div className="space-y-6">
      {/* B1 API connections */}
      <Card>
        <CardHeader title="데이터 소스" sub="B1: 증권사 API·거래내역 임포트 현황" />
        <div className="p-5 space-y-3">
          <div className="flex items-center gap-4 bg-[#0a0d14] border border-white/5 rounded-sm px-4 py-3">
            <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: d?.tossConnected ? "#00d4a1" : "#6b7494" }} />
            <div className="flex-1">
              <div className="text-sm text-[#e8eaf0]">토스증권 Open API</div>
              <div className="text-xs text-[#6b7494] font-mono mt-0.5">보유·거래·예수금·환율 자동 수집</div>
            </div>
            <span className="text-xs font-mono px-2 py-0.5 rounded-sm" style={{ color: d?.tossConnected ? "#00d4a1" : "#6b7494", background: (d?.tossConnected ? "#00d4a1" : "#6b7494") + "15" }}>
              {d?.tossConnected ? "연결됨" : "미연결"}
            </span>
          </div>
          {(d?.sources || []).map(s => (
            <div key={s.name} className="flex items-center gap-4 bg-[#0a0d14] border border-white/5 rounded-sm px-4 py-3">
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#4f8cff" }} />
              <div className="flex-1">
                <div className="text-sm text-[#e8eaf0]">{s.name}</div>
                <div className="text-xs text-[#6b7494] font-mono mt-0.5">임포트된 거래 {s.count}건</div>
              </div>
              <span className="text-xs font-mono px-2 py-0.5 rounded-sm text-[#4f8cff] bg-[#4f8cff]/10">거래내역</span>
              <button onClick={() => doClear(s.name)} disabled={!!clearing}
                className="text-xs font-mono px-2 py-0.5 rounded-sm text-[#ff5c6a] bg-[#ff5c6a]/10 hover:bg-[#ff5c6a]/20 transition-colors disabled:opacity-50">
                {clearing === s.name ? "삭제 중…" : "삭제"}
              </button>
            </div>
          ))}
          {(!d || (d.sources.length === 0 && !d.tossConnected)) && (
            <div className="text-xs text-[#6b7494] font-mono text-center py-2">연결된 데이터 소스가 없습니다</div>
          )}
          {d && d.sources.length > 0 && (
            <button onClick={() => doClear()} disabled={!!clearing}
              className="w-full mt-1 text-xs font-mono py-2 rounded-sm border border-[#ff5c6a]/30 text-[#ff5c6a]/80 hover:bg-[#ff5c6a]/10 transition-colors disabled:opacity-50">
              {clearing === "__all__" ? "삭제 중…" : "전체 임포트 데이터 삭제"}
            </button>
          )}
        </div>
      </Card>

      {/* B2 AI Import (single upload) */}
      <Card>
        <CardHeader title="거래내역 업로드 · AI 자동 분석" sub="증권사 파일(CSV·XLSX·PDF)을 올리면 AI가 거래·배당을 자동으로 정리합니다" />
        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-1.5">증권사 (선택)</label>
            <input value={broker} onChange={e => setBroker(e.target.value)} placeholder="예: 한화투자증권"
              className="w-full bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50" />
          </div>
          <div
            className={`border border-dashed rounded-sm py-8 text-center cursor-pointer transition-colors ${dragOver ? "border-[#00d4a1]/50 bg-[#00d4a1]/5" : "border-white/15 hover:border-white/25"}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={e => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files); }}>
            <div className="text-2xl text-[#6b7494] mb-2">⬆</div>
            <div className="text-sm text-[#a0a8c0]">파일을 드래그하거나 클릭하여 선택</div>
            <div className="text-xs text-[#6b7494] font-mono mt-1">CSV · XLSX · PDF · 여러 파일 가능</div>
            <input ref={inputRef} type="file" multiple accept=".csv,.xlsx,.xls,.pdf,.txt" className="hidden"
              onChange={e => { addFiles(e.target.files); if (inputRef.current) inputRef.current.value = ""; }} />
          </div>
          {files.length > 0 && (
            <div className="space-y-1.5">
              {files.map((f, i) => (
                <div key={i} className="flex items-center justify-between bg-[#0a0d14] border border-white/5 rounded-sm px-3 py-2">
                  <span className="text-xs text-[#a0a8c0] font-mono truncate">{f.name}</span>
                  <button onClick={() => setFiles(prev => prev.filter((_, idx) => idx !== i))}
                    className="text-xs text-[#ff5c6a]/70 hover:text-[#ff5c6a] font-mono ml-2">제거</button>
                </div>
              ))}
            </div>
          )}
          {uploadErr && <div className="text-xs text-[#ff5c6a] font-mono">{uploadErr}</div>}
          <button onClick={doUpload} disabled={uploading || files.length === 0}
            className="w-full bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm py-2.5 rounded-sm hover:bg-[#00d4a1]/90 transition-colors disabled:opacity-50">
            {uploading ? "AI가 분석 중…" : "업로드 & AI 분석"}
          </button>
          {result && (
            <div className="bg-[#00d4a1]/5 border border-[#00d4a1]/15 rounded-sm p-4 space-y-2">
              <div className="text-sm text-[#00d4a1] font-mono">✓ 거래 {result.transactions}건 · 배당 {result.dividends}건 저장됨</div>
              {result.txPreview && result.txPreview.length > 0 && (
                <div className="text-xs text-[#6b7494] font-mono leading-relaxed">
                  거래 예시: {result.txPreview.slice(0, 3).map((t: any) => `${t["일자"]} ${t["종목명"]} ${t["구분"]}`).join(" · ")}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* B5 Ticker enrichment */}
      <Card>
        <CardHeader title="종목명 자동 보강" sub="B5: 티커 → 한글 종목명 매핑" />
        <div className="p-5">
          <div className="grid grid-cols-3 gap-4 text-center">
            {[
              { label: "매핑 완료", value: String(d?.mappedCount ?? 0), color: "#00d4a1" },
              { label: "미매핑", value: String(d?.unmappedCount ?? 0), color: "#ff5c6a" },
              { label: "전체 종목", value: String(d?.tickerCount ?? 0), color: "#a0a8c0" },
            ].map(s => (
              <div key={s.label} className="bg-[#0a0d14] border border-white/5 rounded-sm p-4">
                <div className="font-['DM_Serif_Display',serif] text-2xl mb-1" style={{ color: s.color }}>{s.value}</div>
                <div className="text-xs text-[#6b7494] font-mono">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      {/* B6 Data merge */}
      <Card>
        <CardHeader title="데이터 통합 현황" sub="B6: 거래·배당 집계" />
        <div className="p-5 space-y-2 text-xs font-mono text-[#6b7494]">
          <div className="flex justify-between py-2 border-b border-white/5">
            <span>거래 내역</span>
            <span className="text-[#00d4a1]">{d?.txCount ?? 0}건</span>
          </div>
          <div className="flex justify-between py-2 border-b border-white/5">
            <span>배당 내역</span>
            <span className="text-[#a78bfa]">{d?.divCount ?? 0}건</span>
          </div>
          <div className="flex justify-between py-2">
            <span>보유 종목 수</span>
            <span className="text-[#4f8cff]">{d?.tickerCount ?? 0}종목</span>
          </div>
        </div>
      </Card>
    </div>
  );
}
