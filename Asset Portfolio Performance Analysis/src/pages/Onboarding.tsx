import { useState, useEffect } from "react";
import { Card, CardHeader } from "../components/Shared";
import DataSources from "./DataSources";

type DS = { tossConnected: boolean; txCount: number; divCount: number; tickerCount: number };

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const [d, setD] = useState<DS | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [mode, setMode] = useState<"decide" | "import">("decide");

  const load = () => {
    setLoading(true);
    fetch("/api/app/datasources", { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then((j) => setD(j))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const hasData = !!d && (d.txCount > 0 || d.divCount > 0 || d.tossConnected);

  const clearAll = async () => {
    if (!window.confirm("기존 임포트 데이터를 모두 삭제하고 새로 시작할까요? (삭제 내역은 백업되어 복구할 수 있습니다)")) return;
    setClearing(true);
    try {
      await fetch("/api/app/datasources/clear", { method: "POST", body: new FormData(), credentials: "include" });
      setMode("import");
      load();
    } finally { setClearing(false); }
  };

  if (loading) return <div className="text-[#6b7494] text-sm py-20 text-center max-w-3xl mx-auto">불러오는 중…</div>;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {hasData && mode === "decide" ? (
        <Card>
          <CardHeader title="기존 데이터가 있습니다" sub="이 데이터로 계속할지, 삭제하고 새로 시작할지 선택하세요" />
          <div className="p-5 space-y-5">
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-[#0a0d14] border border-white/5 rounded-sm p-4"><div className="text-xs text-[#6b7494] font-mono mb-1">거래</div><div className="text-xl font-['DM_Serif_Display',serif]">{d!.txCount}건</div></div>
              <div className="bg-[#0a0d14] border border-white/5 rounded-sm p-4"><div className="text-xs text-[#6b7494] font-mono mb-1">배당</div><div className="text-xl font-['DM_Serif_Display',serif]">{d!.divCount}건</div></div>
              <div className="bg-[#0a0d14] border border-white/5 rounded-sm p-4"><div className="text-xs text-[#6b7494] font-mono mb-1">토스 연동</div><div className="text-xl font-['DM_Serif_Display',serif]">{d!.tossConnected ? "됨" : "안됨"}</div></div>
            </div>
            <div className="flex gap-3">
              <button onClick={onDone} className="flex-1 bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm py-2.5 rounded-sm hover:bg-[#00d4a1]/90 transition-colors">이 데이터로 계속 →</button>
              <button onClick={clearAll} disabled={clearing} className="px-5 border border-white/10 text-[#ff5c6a] text-sm py-2.5 rounded-sm hover:border-[#ff5c6a]/40 transition-colors disabled:opacity-50">{clearing ? "삭제 중…" : "삭제하고 새로 시작"}</button>
            </div>
            <button onClick={() => setMode("import")} className="text-xs text-[#6b7494] hover:text-[#a0a8c0] font-mono">+ 데이터를 더 임포트하기</button>
          </div>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader title="① 데이터 준비" sub="토스 API 연동 또는 거래내역을 임포트하세요" />
            <div className="p-5 text-sm text-[#a0a8c0]">
              증권사 거래내역·잔고·배당을 임포트하거나 토스 연동 상태를 확인하세요. 준비되면 아래 <b className="text-[#e8eaf0]">다음</b>을 눌러 검증 단계로 이동합니다.
            </div>
          </Card>
          <DataSources />
          <div className="flex justify-between">
            {hasData
              ? <button onClick={() => setMode("decide")} className="text-xs px-4 py-2 border border-white/10 rounded-sm text-[#6b7494] hover:text-[#a0a8c0]">← 데이터 결정으로</button>
              : <span />}
            <button onClick={onDone} className="bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm px-6 py-2.5 rounded-sm hover:bg-[#00d4a1]/90 transition-colors">다음: 데이터 검증 →</button>
          </div>
        </>
      )}
    </div>
  );
}
