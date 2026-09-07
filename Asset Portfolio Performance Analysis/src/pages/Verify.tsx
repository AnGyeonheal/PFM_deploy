import { useState } from "react";
import { Card, CardHeader } from "../components/Shared";
import Transactions from "./Transactions";
import HoldingsEditor from "./HoldingsEditor";

export default function Verify({ onDone, onBack }: { onDone: () => void; onBack: () => void }) {
  const [tab, setTab] = useState<"holdings" | "tx">("holdings");

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <Card>
        <CardHeader title="② 데이터 검증·수정" sub="전처리된 데이터에 이상이 없는지 확인하고 직접 수정하세요" />
        <div className="p-5 flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-1">
            <button onClick={() => setTab("holdings")} className={`px-4 py-2 text-sm rounded-sm transition-colors ${tab === "holdings" ? "bg-white/8 text-[#00d4a1]" : "text-[#6b7494] hover:text-[#a0a8c0]"}`}>종목별 관리</button>
            <button onClick={() => setTab("tx")} className={`px-4 py-2 text-sm rounded-sm transition-colors ${tab === "tx" ? "bg-white/8 text-[#00d4a1]" : "text-[#6b7494] hover:text-[#a0a8c0]"}`}>거래·배당 수정</button>
          </div>
          <div className="flex gap-2">
            <button onClick={onBack} className="text-xs px-4 py-2 border border-white/10 rounded-sm text-[#6b7494] hover:text-[#a0a8c0] transition-colors">← 데이터 준비</button>
            <button onClick={onDone} className="text-xs px-5 py-2 bg-[#00d4a1] text-[#0a0d14] font-semibold rounded-sm hover:bg-[#00d4a1]/90 transition-colors">검증 완료 · 분석 →</button>
          </div>
        </div>
      </Card>
      {tab === "holdings" ? <HoldingsEditor /> : <Transactions />}
    </div>
  );
}
