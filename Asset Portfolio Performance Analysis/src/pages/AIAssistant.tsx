import { useState } from "react";
import { Card, CardHeader } from "../components/Shared";

const SUGGESTIONS = [
  "현재 포트폴리오의 알파·베타 관점에서 리밸런싱 제안해줘",
  "환차손익을 줄이려면 어떻게 해야 해?",
  "내 포트폴리오의 최대 리스크 요인은?",
  "가장 수익률이 높은 종목과 낮은 종목은?",
];

type Message = { role: "user" | "ai"; content: string };

export default function AIAssistant() {
  const [messages, setMessages] = useState<Message[]>([
    { role: "ai", content: "안녕하세요! 포트폴리오 AI 어시스턴트입니다. 알파/베타 분석, 리밸런싱 제안, 또는 포트폴리오에 대한 궁금한 점을 자연어로 질문해 주세요." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState("");
  const [reportLoading, setReportLoading] = useState(false);

  const send = async (text: string) => {
    if (!text.trim() || loading) return;
    const userMsg: Message = { role: "user", content: text };
    const history = messages.map(m => ({ role: m.role === "ai" ? "assistant" : "user", content: m.content }));
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history }),
        credentials: "include",
      });
      const j = await r.json().catch(() => ({}));
      const answer = r.ok ? (j.answer || "응답을 받지 못했습니다.") : (j.error || "오류가 발생했습니다.");
      setMessages(prev => [...prev, { role: "ai", content: answer }]);
    } catch {
      setMessages(prev => [...prev, { role: "ai", content: "서버에 연결할 수 없습니다." }]);
    } finally {
      setLoading(false);
    }
  };

  const genReport = async () => {
    setReportLoading(true);
    try {
      const r = await fetch("/api/rebalance", { method: "POST", credentials: "include" });
      const j = await r.json().catch(() => ({}));
      setReport(r.ok ? (j.report || "리포트를 생성하지 못했습니다.") : (j.error || "오류가 발생했습니다."));
    } catch {
      setReport("서버에 연결할 수 없습니다.");
    } finally {
      setReportLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* J1 AI Report */}
      <Card>
        <CardHeader title="AI 진단·리밸런싱 리포트" sub="J1: 알파·베타·수익률 기반 종합 분석" />
        <div className="p-5">
          {!report && !reportLoading && (
            <div className="text-center py-8">
              <p className="text-sm text-[#6b7494] mb-4">현재 포트폴리오의 알파·베타·수익률을 바탕으로 AI가 종합 진단과 리밸런싱 방향을 제안합니다.</p>
              <button onClick={genReport} className="px-5 py-2.5 bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm rounded-sm hover:bg-[#00d4a1]/90 transition-colors">
                AI 리포트 생성
              </button>
            </div>
          )}
          {reportLoading && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-[#6b7494]">
              <span className="w-2 h-2 bg-[#00d4a1] rounded-full animate-bounce" />
              리포트 생성 중…
            </div>
          )}
          {report && (
            <div className="space-y-4">
              <div className="whitespace-pre-line text-sm text-[#a0a8c0] leading-relaxed">{report}</div>
              <button onClick={genReport} className="text-xs font-mono text-[#6b7494] hover:text-[#a0a8c0] border border-white/10 rounded-sm px-3 py-1.5 hover:border-white/20 transition-colors">
                다시 생성
              </button>
            </div>
          )}
        </div>
      </Card>

      {/* J2 Chat */}
      <Card>
        <CardHeader title="포트폴리오 Q&A" sub="J2: 자연어 질의응답" />
        <div className="flex flex-col h-80">
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "ai" && (
                  <div className="w-7 h-7 rounded bg-[#00d4a1]/20 flex items-center justify-center flex-shrink-0 mr-2 mt-0.5">
                    <span className="text-[#00d4a1] text-xs">AI</span>
                  </div>
                )}
                <div className={`max-w-[75%] text-sm rounded-sm px-4 py-2.5 leading-relaxed whitespace-pre-line ${msg.role === "user" ? "bg-[#00d4a1]/15 text-[#e8eaf0]" : "bg-[#1a2035] text-[#a0a8c0]"}`}>
                  {msg.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded bg-[#00d4a1]/20 flex items-center justify-center flex-shrink-0">
                  <span className="text-[#00d4a1] text-xs">AI</span>
                </div>
                <div className="bg-[#1a2035] rounded-sm px-4 py-3 flex gap-1.5">
                  {[0, 1, 2].map(i => (
                    <span key={i} className="w-1.5 h-1.5 bg-[#6b7494] rounded-full animate-bounce" style={{ animationDelay: `${i * 150}ms` }} />
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="p-3 border-t border-white/7">
            <div className="flex gap-2 mb-2 flex-wrap">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => send(s)}
                  className="text-xs font-mono px-2.5 py-1 bg-white/5 text-[#6b7494] rounded-sm hover:bg-white/10 hover:text-[#a0a8c0] transition-colors">
                  {s.slice(0, 20)}…
                </button>
              ))}
            </div>
            <form onSubmit={e => { e.preventDefault(); send(input); }} className="flex gap-2">
              <input value={input} onChange={e => setInput(e.target.value)}
                placeholder="포트폴리오에 대해 자유롭게 질문하세요..."
                className="flex-1 bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors" />
              <button type="submit" className="px-4 py-2 bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm rounded-sm hover:bg-[#00d4a1]/90 transition-colors">
                전송
              </button>
            </form>
          </div>
        </div>
      </Card>
    </div>
  );
}
