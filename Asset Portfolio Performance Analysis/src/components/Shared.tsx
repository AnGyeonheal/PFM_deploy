export type AnalysisOptions = {
  includeDividend: boolean;
  includeFx: boolean;
  period: "1M" | "3M" | "6M" | "1Y" | "5Y" | "ALL" | "YOY";
  year?: number;
  scope: "total" | "stock";
  ticker: string;
};

export const PERIODS: { key: AnalysisOptions["period"]; label: string }[] = [
  { key: "1M", label: "1개월" },
  { key: "3M", label: "3개월" },
  { key: "6M", label: "6개월" },
  { key: "1Y", label: "1년" },
  { key: "5Y", label: "5년" },
  { key: "ALL", label: "전체" },
  { key: "YOY", label: "연도별(YoY)" },
];

export type AnalysisCoverage = {
  status: "complete" | "partial" | "unavailable" | "no_data" | "no_period_data";
  includedSymbols: string[];
  excludedSymbols: string[];
  warnings: string[];
  asOf?: string | null;
  priceDates?: Record<string, string>;
  benchmarkAsOf?: string | null;
};

export function AnalysisPeriodLabel({ opts, asOf, benchmarkAsOf }: { opts: AnalysisOptions; asOf?: string | null; benchmarkAsOf?: string | null }) {
  if (opts.period !== "YOY" && !asOf) return null;
  return <div aria-label="분석 기간" className="text-xs text-[#a0a8c0] font-mono">
    {opts.period === "YOY" ? `${opts.year ?? new Date().getFullYear()}년 · ${opts.year ?? new Date().getFullYear()}-01-01 ~ ${asOf ?? "데이터 없음"}` : `평가 기준 ${asOf}`}
    {benchmarkAsOf && benchmarkAsOf !== asOf && ` · S&P500 종가 ${benchmarkAsOf}`}
  </div>;
}

export function AnalysisNotice({ analysis }: { analysis?: AnalysisCoverage }) {
  if (!analysis || analysis.status === "complete") return null;
  const included = analysis.includedSymbols.length;
  const total = included + analysis.excludedSymbols.length;
  const title = analysis.status === "partial" ? `일부 종목 기준 · ${included}/${total}종목 분석`
    : analysis.status === "no_period_data" ? "선택기간 데이터 없음" : "성과 계산 불가";
  return (
    <div role="status" aria-label="분석 데이터 상태" className="border-l-2 border-[#fbbf24] pl-3 py-2 text-xs text-[#fbbf24] space-y-2">
      <div className="font-medium">{title}</div>
      {analysis.status === "partial" && <div>미분석 종목의 거래·원금·배당 제외. 계좌 총자산은 전체 기준.</div>}
      {analysis.warnings.length > 0 && <details open={analysis.warnings.length <= 3}>
        <summary className="cursor-pointer">{analysis.status === "partial" ? "제외 사유" : "계산 불가 사유"}</summary>
        <ul className="mt-2 space-y-1 break-words">{analysis.warnings.map(message => <li key={message}>{message}</li>)}</ul>
      </details>}
    </div>
  );
}

export function formatKRW(n: number | null, compact = false): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (compact) {
    if (Math.abs(n) >= 100_000_000) return `${(n / 100_000_000).toFixed(1)}억`;
    if (Math.abs(n) >= 10_000) return `${(n / 10_000).toFixed(0)}만`;
    return n.toLocaleString();
  }
  if (Math.abs(n) >= 100_000_000) return `${(n / 100_000_000).toFixed(2)}억원`;
  if (Math.abs(n) >= 10_000) return `${(n / 10_000).toFixed(0)}만원`;
  return `${n.toLocaleString()}원`;
}

export function ReturnBadge({ value, size = "sm" }: { value: number | null; size?: "sm" | "md" | "lg" }) {
  if (value == null || !Number.isFinite(value)) return <span className="font-mono text-xs text-[#6b7494]">—</span>;
  const isPos = value >= 0;
  const sizes = { sm: "text-xs px-1.5 py-0.5", md: "text-sm px-2 py-1", lg: "text-base px-3 py-1.5" };
  return (
    <span className={`font-mono font-medium rounded-sm inline-flex items-center gap-0.5 ${sizes[size]} ${isPos ? "text-[#00d4a1] bg-[#00d4a1]/10" : "text-[#ff5c6a] bg-[#ff5c6a]/10"}`}>
      {isPos ? "▲" : "▼"} {Math.abs(value).toFixed(2)}%
    </span>
  );
}

export function PnLText({ value }: { value: number | null }) {
  if (value == null || !Number.isFinite(value)) return <span className="font-mono text-sm text-[#6b7494]">—</span>;
  const isPos = value >= 0;
  return (
    <span className={`font-mono text-sm ${isPos ? "text-[#00d4a1]" : "text-[#ff5c6a]"}`}>
      {isPos ? "+" : ""}{formatKRW(value)}
    </span>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-[#111520] border border-white/7 rounded-sm ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="px-5 pt-5 pb-4 border-b border-white/7">
      <div className="text-xs text-[#6b7494] uppercase tracking-widest font-mono">{title}</div>
      {sub && <div className="text-xs text-[#6b7494]/60 font-mono mt-0.5">{sub}</div>}
    </div>
  );
}

export const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-[#161c2d] border border-white/10 rounded p-3 text-xs font-mono shadow-xl">
      <div className="text-[#6b7494] mb-2">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 mb-1 last:mb-0">
          <span className="w-2 h-2 rounded-full inline-block flex-shrink-0" style={{ background: p.color }} />
          <span className="text-[#a0a8c0]">{p.name}</span>
          <span className="text-[#e8eaf0] ml-auto pl-4">
            {typeof p.value === "number" ? p.value.toFixed(2) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
};

export function AnalysisBar({
  opts, setOpts, tickers = [], years = [], showPeriod = true,
}: {
  opts: AnalysisOptions;
  setOpts: (o: AnalysisOptions) => void;
  tickers?: { ticker: string; name: string }[];
  years?: number[];
  showPeriod?: boolean;
}) {
  const toggle = (key: keyof Pick<AnalysisOptions, "includeDividend" | "includeFx">) =>
    setOpts({ ...opts, [key]: !opts[key] });
  const selectedYear = opts.year ?? new Date().getFullYear();
  const yearOptions = [...new Set([selectedYear, ...years])].sort((first, second) => second - first);

  return (
    <div className="flex flex-wrap items-center gap-3 bg-[#111520] border border-white/7 rounded-sm px-4 py-2.5">
      <span className="text-xs text-[#6b7494] font-mono uppercase tracking-wider mr-1">분석 옵션</span>
      {/* G1 dividend */}
      <button
        onClick={() => toggle("includeDividend")}
        aria-pressed={opts.includeDividend}
        title="배당·분배금 수령액을 손익·수익률·알파에 반영(포함)하거나 제외합니다"
        className={`text-xs font-mono px-3 py-1.5 rounded-sm border transition-colors ${opts.includeDividend ? "border-[#00d4a1]/40 bg-[#00d4a1]/10 text-[#00d4a1]" : "border-white/10 text-[#6b7494] hover:text-[#a0a8c0]"}`}>
        배당 {opts.includeDividend ? "포함" : "제외"}
      </button>
      {/* G2 fx */}
      <button
        onClick={() => toggle("includeFx")}
        aria-pressed={opts.includeFx}
        title="달러 자산과 국내 상장 미국 ETF의 환율 변동을 포함하거나 매수환율로 고정합니다"
        className={`text-xs font-mono px-3 py-1.5 rounded-sm border transition-colors ${opts.includeFx ? "border-[#4f8cff]/40 bg-[#4f8cff]/10 text-[#4f8cff]" : "border-white/10 text-[#6b7494] hover:text-[#a0a8c0]"}`}>
        환차손익 {opts.includeFx ? "포함" : "제외"}
      </button>
      {showPeriod && <div className="w-px h-4 bg-white/10" />}
      {/* G3 period (성장 차트가 있는 페이지에서만) */}
      {showPeriod && PERIODS.map(p => (
        <button key={p.key} onClick={() => setOpts({ ...opts, period: p.key })}
          aria-pressed={opts.period === p.key}
          className={`text-xs font-mono px-2.5 py-1.5 rounded-sm transition-colors ${opts.period === p.key ? "bg-white/10 text-[#e8eaf0]" : "text-[#6b7494] hover:text-[#a0a8c0]"}`}>
          {p.label}
        </button>
      ))}
      {showPeriod && opts.period === "YOY" && (
        <select aria-label="분석 연도" value={selectedYear} onChange={event => setOpts({ ...opts, year: Number(event.target.value) })}
          className="text-xs font-mono bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1.5 text-[#e8eaf0] focus:outline-none focus:border-[#00d4a1]/50">
          {yearOptions.map(year => <option key={year} value={year}>{year}년{year === new Date().getFullYear() ? " (진행 중)" : ""}</option>)}
        </select>
      )}
      <div className="w-px h-4 bg-white/10" />
      {/* G5 scope */}
      <div className="flex gap-0 border border-white/10 rounded-sm overflow-hidden">
        {(["total", "stock"] as const).map(s => (
          <button key={s} onClick={() => setOpts({ ...opts, scope: s, ticker: s === "stock" ? (opts.ticker || tickers[0]?.ticker || "") : "" })}
            aria-pressed={opts.scope === s}
            className={`text-xs font-mono px-2.5 py-1.5 transition-colors ${opts.scope === s ? "bg-white/10 text-[#e8eaf0]" : "text-[#6b7494] hover:text-[#a0a8c0]"}`}>
            {s === "total" ? "전체" : "종목별"}
          </button>
        ))}
      </div>
      {opts.scope === "stock" && (
        <select aria-label="분석 종목" value={opts.ticker} onChange={e => setOpts({ ...opts, ticker: e.target.value })}
          className="text-xs font-mono bg-[#0a0d14] border border-white/10 rounded-sm px-2 py-1.5 text-[#e8eaf0] focus:outline-none focus:border-[#00d4a1]/50">
          {tickers.length === 0 && <option value="">종목 없음</option>}
          {tickers.map(t => <option key={t.ticker} value={t.ticker}>{t.name || t.ticker}</option>)}
        </select>
      )}
    </div>
  );
}
