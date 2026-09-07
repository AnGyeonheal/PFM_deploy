import { useState } from "react";

type Props = { onLogin: (user: string) => void };

export default function Login({ onLogin }: Props) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    if (mode === "register" && password !== password2) {
      setErr("비밀번호가 일치하지 않습니다");
      return;
    }
    setBusy(true);
    try {
      const url = mode === "register" ? "/api/app/register" : "/api/app/login";
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
        credentials: "include",
      });
      if (r.ok) {
        onLogin(username.trim());
        return;
      }
      const j = await r.json().catch(() => ({}));
      setErr(j.error || (mode === "register" ? "회원가입에 실패했습니다" : "로그인에 실패했습니다"));
    } catch {
      setErr("서버에 연결할 수 없습니다");
    } finally {
      setBusy(false);
    }
  };

  const switchMode = (m: "login" | "register") => {
    setMode(m);
    setErr("");
    setPassword("");
    setPassword2("");
  };

  return (
    <div className="min-h-full bg-[#0a0d14] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-10">
          <div className="w-10 h-10 rounded bg-[#00d4a1] flex items-center justify-center mx-auto mb-4">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M2 13L6 8L10 11L15 4" stroke="#0a0d14" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 className="font-['DM_Serif_Display',serif] text-3xl text-[#e8eaf0] mb-1">PortfolioAI</h1>
          <p className="text-xs text-[#6b7494] font-mono">개인 자산관리 · 성과 분석</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-[#111520] border border-white/7 rounded-sm p-8 space-y-5">
          <div>
            <label className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-2">아이디</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              className="w-full bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2.5 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors"
              placeholder="아이디를 입력하세요"
            />
          </div>
          <div>
            <label className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-2">비밀번호</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              className="w-full bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2.5 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors"
              placeholder={mode === "register" ? "비밀번호 (4자 이상)" : "비밀번호를 입력하세요"}
            />
          </div>
          {mode === "register" && (
            <div>
              <label className="text-xs text-[#6b7494] font-mono uppercase tracking-wider block mb-2">비밀번호 확인</label>
              <input
                type="password"
                value={password2}
                onChange={(e) => setPassword2(e.target.value)}
                autoComplete="new-password"
                className="w-full bg-[#0a0d14] border border-white/10 rounded-sm px-3 py-2.5 text-sm text-[#e8eaf0] font-mono focus:outline-none focus:border-[#00d4a1]/50 transition-colors"
                placeholder="비밀번호를 다시 입력하세요"
              />
            </div>
          )}
          {err && <div className="text-xs text-[#ff5c6a] font-mono">{err}</div>}
          <button
            type="submit"
            disabled={busy}
            className="w-full bg-[#00d4a1] text-[#0a0d14] font-semibold text-sm py-3 rounded-sm hover:bg-[#00d4a1]/90 transition-colors mt-2 disabled:opacity-60"
          >
            {busy ? (mode === "register" ? "가입 중…" : "로그인 중…") : (mode === "register" ? "회원가입" : "로그인")}
          </button>
        </form>

        <p className="text-center text-xs text-[#6b7494] font-mono mt-6">
          {mode === "login" ? (
            <>
              계정이 없으신가요?{" "}
              <button type="button" onClick={() => switchMode("register")} className="text-[#00d4a1] hover:underline">회원가입</button>
            </>
          ) : (
            <>
              이미 계정이 있으신가요?{" "}
              <button type="button" onClick={() => switchMode("login")} className="text-[#00d4a1] hover:underline">로그인</button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
