import { useState, useEffect, useRef } from "react";
import { Card, CardHeader } from "../components/Shared";

type Src = { name: string; count: number };
type UnmappedTicker = { ticker: string; name: string; reason: string };
type ImportIssue = { kind: "transaction" | "dividend"; responseRow: number | null; date: string; ticker: string; name: string; fields: string[]; reasons: string[]; source: { file: string; sheet: string; chunk: number } };
type ImportFailure = { code: string; action: string; stage?: string; source?: { file: string; sheet?: string; chunk?: number } | null; providerStatus?: number | null; elapsedSeconds: number; requestId?: string; httpStatus?: number; rayId?: string };
type DSData = { tossConnected: boolean; txCount: number; divCount: number; tickerCount: number; mappedCount: number; unmappedCount: number; unmappedTickers?: UnmappedTicker[]; sources: Src[] };
type ImportResult = { draftId: string; saved: boolean; transactions: number; dividends: number; txPreview: Record<string, string | number>[]; divPreview: Record<string, string | number>[] };
type ImportProgress = { jobId: string; stage: string; source?: { file: string; sheet?: string; chunk?: number } | null; completedSteps: number; totalSteps: number; elapsedSeconds: number; requestId?: string };
type Connections = { geminiAvailable: boolean; tossConfigured: boolean; account: string; outboundIp: string; aiRequestsPerHour: number };
const fieldClass = "w-full min-w-0 bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50";
const importStages: Record<string, string> = { admission: "요청 확인", read: "파일 읽기", split: "파일 분할", transactions: "거래내역 AI 분석", dividends: "배당내역 AI 분석", validation: "분석 결과 검증", processing: "서버 전처리" };
const importJobStorageKey = "portfolio-lens-import-job";

function importHttpFailure(status: number): [string, string, string] {
  if (status === 524) return ["CLOUDFLARE_TIMEOUT", "Cloudflare의 응답 대기 시간이 초과됐습니다.", "서버에서는 분석이 계속될 수 있습니다. 즉시 반복 요청하지 말고 잠시 기다린 뒤 파일을 기간별로 나누어 시도하세요. 저장 확정은 실행되지 않았습니다."];
  if (status === 504 || status === 408) return ["HTTP_TIMEOUT", "서버 또는 중계 구간에서 응답 시간이 초과됐습니다.", "잠시 기다린 뒤 파일을 작게 나누어 시도하세요. 이 응답만으로 Gemini 오류인지는 확정할 수 없습니다."];
  if (status === 401) return ["AUTH_REQUIRED", "로그인이 만료됐거나 로그인이 필요합니다.", "다시 로그인한 뒤 업로드하세요."];
  if (status === 403) return ["ACCESS_DENIED", "서버 또는 중계 서비스가 요청을 거부했습니다.", "현재 접속 주소와 접근 권한을 확인하세요. 반복되면 운영자에게 문의하세요."];
  if (status === 413) return ["UPLOAD_TOO_LARGE", "업로드 용량 제한을 초과했습니다.", "파일당 5MB, 전체 요청 12MB 이내로 나누어 업로드하세요."];
  if (status === 429) return ["REQUEST_LIMIT", "요청 또는 사용량 제한에 도달했습니다.", "잠시 후 다시 시도하세요. 운영자는 앱과 Gemini의 사용량 제한을 확인해야 합니다."];
  if (status === 400 || status === 422) return ["INVALID_IMPORT", "업로드 입력 또는 파일을 검증하지 못했습니다.", "파일 형식과 필수 항목을 확인하세요. 세부 내역이 없으면 문의 코드를 운영자에게 전달하세요."];
  if (status >= 500) return ["SERVER_ERROR", `서버 또는 중계 서비스에서 오류가 발생했습니다. (HTTP ${status})`, "잠시 후 다시 시도하고 반복되면 문의 코드를 운영자에게 전달하세요."];
  return ["INVALID_SERVER_RESPONSE", "서버가 읽을 수 있는 분석 결과를 반환하지 않았습니다.", "새로고침 후 다시 로그인하고, 반복되면 문의 코드를 운영자에게 전달하세요."];
}

export default function DataSources({ onChanged }: { onChanged?: (data: DSData) => void }) {
  const [d, setD] = useState<DSData | null>(null);
  const [connections, setConnections] = useState<Connections | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [account, setAccount] = useState("1");
  const [connecting, setConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [connectionMessage, setConnectionMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [dataError, setDataError] = useState("");
  const [broker, setBroker] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [uploadErr, setUploadErr] = useState("");
  const [importFailure, setImportFailure] = useState<ImportFailure | null>(null);
  const [importIssues, setImportIssues] = useState<ImportIssue[]>([]);
  const [importProgress, setImportProgress] = useState<ImportProgress | null>(null);
  const [clearing, setClearing] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<AbortController | null>(null);

  const loadData = (changed = false) => {
    fetch("/api/app/datasources", { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("데이터 현황을 불러오지 못했습니다."); return r.json(); })
      .then(j => { setD(j); setDataError(""); if (changed) onChanged?.(j); })
      .catch(error => setDataError(error.message));
  };
  const loadConnections = () => {
    fetch("/api/app/connections", { credentials: "include" })
      .then(r => { if (!r.ok) throw new Error("연결 상태를 불러오지 못했습니다."); return r.json(); })
      .then(j => { setConnections(j); setAccount(j.account || "1"); })
      .catch(error => setConnectionError(error.message));
  };
  useEffect(() => { loadData(); loadConnections(); }, []);
  useEffect(() => () => pollingRef.current?.abort(), []);

  const connectToss = async (event: React.FormEvent) => {
    event.preventDefault();
    setConnecting(true); setConnectionError(""); setConnectionMessage("");
    try {
      const response = await fetch("/api/app/connections/toss", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clientId, clientSecret, account }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.detail || "연결에 실패했습니다.");
      setConnectionMessage("계좌 조회 확인 · 키 저장 완료");
      loadConnections(); loadData(true);
    } catch (error) { setConnectionError(error instanceof Error ? error.message : "연결에 실패했습니다."); }
    finally { setClientSecret(""); setClientId(""); setConnecting(false); }
  };

  const disconnectToss = async () => {
    if (!window.confirm("본인 계정에 저장된 토스 API 키를 삭제하고 연결을 해제할까요?")) return;
    setConnecting(true); setConnectionError(""); setConnectionMessage("");
    try {
      const response = await fetch("/api/app/connections/toss", { method: "DELETE", credentials: "include" });
      if (!response.ok) throw new Error("연결 해제에 실패했습니다.");
      setConnectionMessage("토스 키 삭제 완료"); loadConnections(); loadData(true);
    } catch (error) { setConnectionError(error instanceof Error ? error.message : "연결 해제에 실패했습니다."); }
    finally { setConnecting(false); }
  };

  const addFiles = (fl: FileList | null) => {
    if (!fl) return;
    const selected = [...files, ...Array.from(fl)];
    if (selected.length > 5 || selected.some(file => file.size > 5 * 1024 * 1024)) {
      setImportFailure(null);
      setUploadErr("최대 5개, 파일당 5MB까지 선택할 수 있습니다."); return;
    }
    setFiles(selected); setResult(null); setUploadErr(""); setImportIssues([]); setImportFailure(null);
  };

  const showImportFailure = (payload: Record<string, any>, httpStatus: number, started: number, headers?: Headers) => {
    const [code, message, action] = importHttpFailure(httpStatus);
    const knownFailure = payload.failure && typeof payload.failure.code === "string" && typeof payload.failure.action === "string" ? payload.failure : null;
    setUploadErr(typeof payload.error === "string" ? payload.error : typeof payload.detail === "string" ? payload.detail : message);
    setImportFailure({ code, action, ...knownFailure, elapsedSeconds: knownFailure?.elapsedSeconds ?? (performance.now() - started) / 1000,
      httpStatus: payload.httpStatus || httpStatus, requestId: knownFailure?.requestId || headers?.get("x-request-id") || undefined,
      rayId: headers?.get("cf-ray") || undefined });
    setImportIssues(Array.isArray(payload.issues) ? payload.issues : []);
  };

  const pollImportJob = async (jobId: string, started: number) => {
    pollingRef.current?.abort();
    const controller = new AbortController();
    pollingRef.current = controller;
    let networkFailures = 0;
    try {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(`/api/app/import/jobs/${encodeURIComponent(jobId)}`, {
            credentials: "include", signal: controller.signal,
          });
          const decoded = await response.json().catch(() => null);
          const payload = decoded && typeof decoded === "object" && !Array.isArray(decoded) ? decoded : {};
          if (!response.ok) {
            sessionStorage.removeItem(importJobStorageKey);
            showImportFailure(payload, response.status, started, response.headers);
            return;
          }
          networkFailures = 0;
          if (payload.status === "processing") {
            setImportProgress({ jobId, stage: payload.stage || "processing", source: payload.source,
              completedSteps: Number(payload.completedSteps) || 0, totalSteps: Number(payload.totalSteps) || 0,
              elapsedSeconds: Number(payload.elapsedSeconds) || 0, requestId: payload.requestId });
          } else {
            sessionStorage.removeItem(importJobStorageKey);
            setImportProgress(null);
            if (payload.status === "complete" && payload.ok && typeof payload.draftId === "string") {
              setResult(payload); setFiles([]); setUploadErr(""); setImportFailure(null); setImportIssues([]);
            } else {
              showImportFailure(payload, Number(payload.httpStatus) || 500, started, response.headers);
            }
            return;
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          networkFailures += 1;
          if (networkFailures >= 6) throw error;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch {
      sessionStorage.removeItem(importJobStorageKey);
      setImportProgress(null);
      setUploadErr("분석 상태를 서버에서 확인하지 못했습니다.");
      setImportFailure({ code: "NETWORK_ERROR", action: "인터넷·서버·터널 연결을 확인하세요. 분석은 서버에서 계속될 수 있으며, 화면을 새로고침하면 진행 중인 작업 확인을 다시 시도할 수 있습니다.", elapsedSeconds: (performance.now() - started) / 1000 });
    } finally {
      if (pollingRef.current === controller) pollingRef.current = null;
      setUploading(false);
    }
  };

  useEffect(() => {
    const jobId = sessionStorage.getItem(importJobStorageKey);
    if (!jobId) return;
    setUploading(true);
    void pollImportJob(jobId, performance.now());
  }, []);

  const doUpload = async () => {
    setImportFailure(null);
    if (files.length === 0) { setUploadErr("업로드할 파일을 선택하세요."); return; }
    if (!consent) { setUploadErr("Google Gemini 전송에 동의해 주세요."); return; }
    setUploading(true); setUploadErr(""); setResult(null); setImportIssues([]);
    const fd = new FormData();
    fd.append("broker", broker.trim() || "증권사");
    fd.append("consent", "true");
    fd.append("background", "true");
    files.forEach(f => fd.append("files", f));
    const started = performance.now();
    try {
      const r = await fetch("/api/app/import", { method: "POST", body: fd, credentials: "include" });
      const decoded = await r.json().catch(() => null);
      const j = decoded && typeof decoded === "object" && !Array.isArray(decoded) ? decoded : {};
      if (r.status === 202 && j.status === "processing" && typeof j.jobId === "string") {
        sessionStorage.setItem(importJobStorageKey, j.jobId);
        setImportProgress({ jobId: j.jobId, stage: "read", completedSteps: 0, totalSteps: 0,
          elapsedSeconds: 0, requestId: j.requestId });
        await pollImportJob(j.jobId, started);
      } else if (r.ok && j.ok && typeof j.draftId === "string") {
        setResult(j);
        setFiles([]);
      } else {
        showImportFailure(j, r.status, started, r.headers);
      }
    } catch {
      setUploadErr("분석 요청의 응답을 받지 못했습니다.");
      setImportFailure({ code: "NETWORK_ERROR", action: "인터넷·서버·터널 연결 상태를 확인하세요. 서버에서 분석이 진행 중일 수 있으므로 즉시 반복 업로드하지 마세요.", elapsedSeconds: (performance.now() - started) / 1000 });
    } finally { if (!pollingRef.current) setUploading(false); }
  };

  const confirmImport = async () => {
    if (!result?.draftId) return;
    setConfirming(true); setUploadErr(""); setImportFailure(null);
    try {
      const response = await fetch("/api/app/import/confirm", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draftId: result.draftId }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || payload.detail || "저장에 실패했습니다.");
      setResult(previous => previous ? { ...previous, ...payload } : null);
      loadData(true);
    } catch (error) { setUploadErr(error instanceof Error ? error.message : "저장에 실패했습니다."); }
    finally { setConfirming(false); }
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
      if (r.ok && j.ok) { setResult(null); loadData(true); }
    } catch {
      /* noop */
    } finally {
      setClearing("");
    }
  };

  return (
    <div className="space-y-6">
      {dataError && <div role="alert" className="text-xs text-[#ff5c6a]">{dataError}</div>}
      {/* B1 API connections */}
      <Card>
        <CardHeader title="데이터 소스" sub="B1: 증권사 API·거래내역 임포트 현황" />
        <div className="p-5 space-y-3">
          <div className="flex items-center gap-4 bg-[#0a0d14] border border-white/5 rounded-sm px-4 py-3">
            <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: d?.tossConnected ? "#00d4a1" : "#6b7494" }} />
            <div className="flex-1">
              <div className="text-sm text-[#e8eaf0]">토스증권 Open API</div>
              <div className="text-xs text-[#6b7494] font-mono mt-0.5">개인 계좌 연결</div>
            </div>
            <span className="text-xs font-mono px-2 py-0.5 rounded-sm" style={{ color: d?.tossConnected ? "#00d4a1" : "#6b7494", background: (d?.tossConnected ? "#00d4a1" : "#6b7494") + "15" }}>
              {d?.tossConnected ? "연결됨" : "미연결"}
            </span>
          </div>
          <form onSubmit={connectToss} aria-label="개인 토스 API 연결" className="space-y-3 py-3 border-b border-white/10">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="text-xs text-[#a0a8c0] min-w-0">Client ID
                <input required value={clientId} onChange={event => setClientId(event.target.value)} className={`${fieldClass} mt-1`} autoComplete="off" maxLength={4096} />
              </label>
              <label className="text-xs text-[#a0a8c0] min-w-0">Client Secret
                <input required type="password" value={clientSecret} onChange={event => setClientSecret(event.target.value)} className={`${fieldClass} mt-1`} autoComplete="off" maxLength={4096} />
              </label>
              <label className="text-xs text-[#a0a8c0] min-w-0">토스 계좌 식별자
                <input required value={account} onChange={event => setAccount(event.target.value)} className={`${fieldClass} mt-1`} maxLength={128} />
              </label>
              <div className="text-xs text-[#a0a8c0] min-w-0">토스 등록 대상 서버 IP
                <div className="mt-2 font-mono break-all" title="본인 토스 개발자 콘솔의 허용 IP에 등록해야 합니다.">{connections?.outboundIp || "서버 운영자에게 확인"}</div>
              </div>
            </div>
            <p className="text-xs text-[#6b7494]">키는 본인 계정의 서버 저장소에 보관됩니다. 테스트 운영자는 서버 파일에 접근할 수 있습니다.</p>
            <div className="flex flex-wrap gap-3 items-center">
              <button type="submit" disabled={connecting || !clientId.trim() || !clientSecret.trim()} className="px-4 py-2 text-xs rounded-sm bg-[#4f8cff] text-white disabled:opacity-50">
                {connecting ? "처리 중…" : "연결 확인 및 저장"}
              </button>
              {connections?.tossConfigured && <button type="button" onClick={disconnectToss} disabled={connecting} className="px-3 py-2 text-xs text-[#ff5c6a] disabled:opacity-50">연결 해제</button>}
            </div>
            {connectionError && <p role="alert" className="text-xs text-[#ff5c6a]">{connectionError}</p>}
            {connectionMessage && <p role="status" className="text-xs text-[#00d4a1]">{connectionMessage}</p>}
          </form>
          <div className="flex flex-wrap justify-between gap-2 py-2 text-xs" role="status" aria-label="공용 Gemini 상태">
            <span className="text-[#a0a8c0]">Google Gemini · 서버 공용</span>
            <span className={connections?.geminiAvailable ? "text-[#00d4a1]" : "text-[#6b7494]"}>{!connections ? "확인 중" : connections.geminiAvailable ? `사용 가능 · 사용자당 ${connections.aiRequestsPerHour}회/시간` : "서버 키 미설정"}</span>
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
            <label htmlFor="import-broker" className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-1.5">증권사 (선택)</label>
            <input id="import-broker" value={broker} onChange={e => setBroker(e.target.value)} placeholder="예: 한화투자증권"
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
          <label className="flex items-start gap-2 text-xs leading-relaxed text-[#a0a8c0]">
            <input type="checkbox" checked={consent} onChange={event => setConsent(event.target.checked)} className="mt-0.5 accent-[#00d4a1]" />
            <span>거래내역을 Google Gemini에 전송하여 분석하는 데 동의합니다. API 키·비밀번호·불필요한 개인정보가 포함된 파일은 제외합니다.</span>
          </label>
          {uploadErr && <section role="alert" aria-label="임포트 실패 상세" className="border-l-2 border-[#ff5c6a] pl-3 space-y-2 text-xs leading-relaxed">
            <p className="text-[#ff5c6a] font-medium">{uploadErr}</p>
            {importFailure && <>
              <p className="text-[#a0a8c0]">{importFailure.action}</p>
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[#6b7494]">
                {importFailure.stage && <><dt>실패 단계</dt><dd>{importStages[importFailure.stage] || "알 수 없음"}</dd></>}
                {importFailure.source && <><dt>파일 · 구간</dt><dd className="min-w-0 break-all">{[importFailure.source.file, importFailure.source.sheet, importFailure.source.chunk ? `분할 ${importFailure.source.chunk}` : ""].filter(Boolean).join(" · ")}</dd></>}
                <dt>응답 대기</dt><dd>{importFailure.elapsedSeconds.toFixed(1)}초</dd>
                <dt>오류 코드</dt><dd className="min-w-0 break-all font-mono">{importFailure.code}{importFailure.httpStatus ? ` · HTTP ${importFailure.httpStatus}` : ""}{importFailure.providerStatus ? ` · Google ${importFailure.providerStatus}` : ""}</dd>
                {importFailure.requestId && <><dt>문의 코드</dt><dd className="min-w-0 break-all font-mono select-all">{importFailure.requestId}</dd></>}
                {importFailure.rayId && <><dt>Cloudflare Ray</dt><dd className="min-w-0 break-all font-mono select-all">{importFailure.rayId}</dd></>}
              </dl>
              <p className="text-[#6b7494]">저장 확정 전이므로 기존 거래·배당 내역은 변경되지 않았습니다.</p>
            </>}
          </section>}
          {importIssues.length > 0 && (
            <section aria-label="미매핑 및 전처리 확인 내역" className="space-y-3 border-t border-white/10 pt-3">
              <h3 className="text-sm font-medium text-[#e8eaf0]">미매핑·검증 필요 {importIssues.length}건</h3>
              <div className="text-xs text-[#6b7494]">티커 미매핑 {importIssues.filter(issue => issue.fields.includes("티커")).length}건 · 전체 업로드 미저장</div>
              <div className="overflow-x-auto max-h-80">
                <table aria-label="전처리 확인 내역" className="w-full min-w-[760px] text-xs">
                  <thead className="text-[#6b7494]"><tr>
                    {["파일 · 시트", "AI 결과 행", "일자 · 유형", "종목명 · 티커", "확인 필드", "사유"].map(label => <th key={label} className="p-2 text-left font-normal">{label}</th>)}
                  </tr></thead>
                  <tbody>{importIssues.map((issue, index) => (
                    <tr key={index} className="border-t border-white/7 align-top">
                      <td className="p-2 min-w-36 max-w-48 break-all text-[#a0a8c0]">
                        <div>{issue.source.file}</div>
                        {issue.source.sheet && <div>{issue.source.sheet}</div>}
                        <div className="text-[#6b7494]">분할 {issue.source.chunk}</div>
                      </td>
                      <td className="p-2 font-mono" title="해당 분할 구간의 AI 응답 순서입니다. 원본 Excel 행 번호가 아닙니다.">{issue.responseRow ?? "—"}</td>
                      <td className="p-2 min-w-28 max-w-40 break-all text-[#a0a8c0]">
                        <div>{issue.date || "일자 미확인"}</div>
                        <div>{issue.kind === "dividend" ? "배당" : "거래"}</div>
                      </td>
                      <td className="p-2 min-w-36 max-w-48 break-words">
                        <div>{issue.name || "종목명 미확인"}</div>
                        <div className="mt-1 font-mono break-all text-[#6b7494]">{issue.ticker || "티커 없음"}</div>
                      </td>
                      <td className="p-2 max-w-32 break-words text-[#ff5c6a]">{issue.fields.join(", ")}</td>
                      <td className="p-2 min-w-52 max-w-72 text-[#a0a8c0]"><ul className="space-y-1">{issue.reasons.map((reason, reasonIndex) => <li key={reasonIndex}>{reason}</li>)}</ul></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </section>
          )}
          {importProgress && (
            <section role="status" aria-label="AI 분석 진행 상태" className="border-l-2 border-[#4f8cff] pl-3 space-y-1 text-xs leading-relaxed">
              <p className="text-[#a0c4ff]">서버에서 분석 중입니다. 다른 메뉴로 이동해도 작업은 계속됩니다.</p>
              <p className="text-[#6b7494]">
                {importStages[importProgress.stage] || "분석 중"}
                {importProgress.source?.file ? ` · ${importProgress.source.file}` : ""}
                {importProgress.source?.sheet ? ` · ${importProgress.source.sheet}` : ""}
                {importProgress.source?.chunk ? ` · 분할 ${importProgress.source.chunk}` : ""}
              </p>
              <p className="font-mono text-[#6b7494]">
                {importProgress.totalSteps > 0 ? `${importProgress.completedSteps}/${importProgress.totalSteps} 단계 · ` : ""}
                {importProgress.elapsedSeconds.toFixed(0)}초
                {importProgress.requestId ? ` · 문의 ${importProgress.requestId}` : ""}
              </p>
            </section>
          )}
          <button onClick={doUpload} disabled={uploading || confirming || files.length === 0 || !consent || !connections?.geminiAvailable}
            className="w-full bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm py-2.5 rounded-sm hover:bg-[#00d4a1]/90 transition-colors disabled:opacity-50">
            {uploading ? "서버에서 AI 분석 중…" : "업로드 & AI 분석"}
          </button>
          {result && (
            <div className="border-t border-white/10 pt-4 space-y-3">
              <div role="status" className="text-sm text-[#00d4a1] font-mono">거래 {result.transactions}건 · 배당 {result.dividends}건 {result.saved ? "추가 저장 완료" : "분석 완료 · 미저장"}</div>
              {!result.saved && <>
                <div className="overflow-x-auto max-h-72">
                  <table className="w-full min-w-[480px] text-xs font-mono" aria-label="임포트 미리보기">
                    <thead><tr>{["일자", "종목", "계좌", "유형", "수량", "단가 / 배당", "통화"].map(label => <th key={label} className="text-left p-2 text-[#6b7494]">{label}</th>)}</tr></thead>
                    <tbody>{[...result.txPreview, ...result.divPreview].map((row, index) => <tr key={index} className="border-t border-white/5">
                      {[row["일자"], row["티커"], row["계좌"] || "", row["구분"] || "배당", row["수량"] ?? "", row["단가"] ?? row["배당금"], row["통화"]].map((value, column) => <td key={column} className="p-2 whitespace-nowrap">{String(value ?? "")}</td>)}
                    </tr>)}</tbody>
                  </table>
                </div>
                <p className="text-xs text-[#6b7494]">미리보기는 유형별 최대 30건 · 확정 대기 15분 · 기존 내역은 유지됩니다.</p>
                <div className="flex gap-3">
                  <button onClick={confirmImport} disabled={confirming} className="px-4 py-2 text-sm rounded-sm bg-[#00d4a1] text-[#0a0d14] disabled:opacity-50">{confirming ? "저장 중…" : "저장 확정"}</button>
                  <button onClick={() => setResult(null)} disabled={confirming} className="px-3 py-2 text-sm text-[#6b7494]">취소</button>
                </div>
              </>}
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
          {d && d.unmappedCount > 0 && (
            <section aria-label="미매핑 종목" className="mt-4 border-t border-white/10 pt-3">
              <h3 className="text-sm font-medium text-[#e8eaf0] mb-2">미매핑 종목 {d.unmappedCount}개</h3>
              <div className="overflow-x-auto max-h-64">
                <table aria-label="미매핑 종목 목록" className="w-full min-w-[360px] text-xs">
                  <thead><tr>{["티커", "사유"].map(label => <th key={label} className="p-2 text-left font-normal text-[#6b7494]">{label}</th>)}</tr></thead>
                  <tbody>{(d.unmappedTickers || []).map(row => (
                    <tr key={row.ticker} className="border-t border-white/7 align-top">
                      <td className="p-2 font-mono text-[#ff5c6a] max-w-40 break-all">{row.ticker}</td>
                      <td className="p-2 text-[#a0a8c0]">{row.reason}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </section>
          )}
          {d && d.unmappedCount === 0 && <p role="status" className="mt-3 text-xs text-[#6b7494]">{d.tickerCount ? "미매핑 종목이 없습니다." : "매핑할 종목이 없습니다."}</p>}
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
