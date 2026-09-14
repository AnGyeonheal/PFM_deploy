import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AnalysisNotice, AnalysisPeriodLabel, Card, CustomTooltip, type AnalysisCoverage, type AnalysisOptions } from "../components/Shared";

type RiskMetrics = {
  totalReturnPct: number | null;
  annualizedReturnPct: number | null;
  maxDrawdownPct: number | null;
  currentDrawdownPct: number | null;
  volatilityPct: number | null;
};
type Diagnosis = {
  method: string;
  scopeName: string;
  analysis: AnalysisCoverage;
  portfolio: RiskMetrics;
  benchmark: RiskMetrics;
  relative: {
    excessReturnPp: number | null;
    trackingErrorPct: number | null;
    informationRatio: number | null;
    monthlyWinRatePct: number | null;
    winningMonths: number;
    comparableMonths: number;
  };
  sample: { start: string | null; end: string | null; calendarDays: number; observations: number };
  series: { date: string; portfolio: number; benchmark: number; portfolioDrawdown: number; benchmarkDrawdown: number; baseline: boolean }[];
  monthly: { month: string; portfolio: number; benchmark: number; excessPp: number; partial: boolean }[];
  tickers: { ticker: string; name: string }[];
  years: number[];
};

const numberText = (value: number | null, unit = "", signed = false) => {
  if (value == null || !Number.isFinite(value)) return "—";
  const rounded = Math.abs(value) < 0.005 ? 0 : value;
  return `${signed && rounded > 0 ? "+" : ""}${rounded.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${unit}`;
};
const tone = (value: number | null) => value == null || Math.abs(value) < 0.005 ? "text-[#a0a8c0]" : value > 0 ? "text-[#00d4a1]" : "text-[#ff5c6a]";
const tickStyle = { fill: "#6b7494", fontSize: 11, fontFamily: "JetBrains Mono" };

function comparisonLabel(report: Diagnosis) {
  const excess = report.relative.excessReturnPp;
  const mine = report.portfolio.maxDrawdownPct;
  const market = report.benchmark.maxDrawdownPct;
  if (excess == null || mine == null || market == null) return "비교 자료 부족";
  const growth = Math.abs(excess) < 0.005 ? "수익 유사" : excess > 0 ? "수익 우위" : "수익 열위";
  const defense = Math.abs(mine - market) < 0.005 ? "낙폭 유사" : mine > market ? "낙폭 억제" : "낙폭 확대";
  return `${growth} · ${defense}`;
}

export default function PerformanceDiagnosis({ opts, onTickers, onYears }: {
  opts: AnalysisOptions;
  onTickers?: (tickers: { ticker: string; name: string }[]) => void;
  onYears?: (years: number[]) => void;
}) {
  const [report, setReport] = useState<Diagnosis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      div: opts.includeDividend ? "1" : "0", fx: opts.includeFx ? "1" : "0",
      period: opts.period, year: String(opts.year ?? new Date().getFullYear()),
      ticker: opts.scope === "stock" ? opts.ticker : "",
    });
    fetch(`/api/app/diagnosis?${params}`, { credentials: "include", signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(response.status === 401 ? "로그인이 필요합니다." : "성과 진단을 불러오지 못했습니다.");
        return response.json() as Promise<Diagnosis>;
      })
      .then(data => {
        if (controller.signal.aborted) return;
        setReport(data);
        onTickers?.(data.tickers);
        onYears?.(data.years);
      })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason.message || reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [opts.period, opts.year, opts.includeDividend, opts.includeFx, opts.scope, opts.ticker, attempt]);

  if (loading) return <div role="status" className="text-sm text-[#6b7494] py-16 text-center">성과 진단 계산 중…</div>;
  if (error) return <div role="alert" className="py-12 text-center space-y-4">
    <div className="text-sm text-[#ff5c6a]">{error}</div>
    <button onClick={() => setAttempt(value => value + 1)} className="text-sm px-4 py-2 border border-white/15 rounded-sm text-[#e8eaf0] hover:bg-white/5">다시 불러오기</button>
  </div>;
  if (!report) return null;

  const mine = report.portfolio;
  const market = report.benchmark;
  const relative = report.relative;
  const metrics = [
    { label: "연환산 TWR", value: mine.annualizedReturnPct, reference: market.annualizedReturnPct,
      color: "#00d4a1", unit: "%", signed: true, status: report.sample.calendarDays < 365 ? "365일 미만 · 연환산 보류" : "실제 경과일 기준",
      formula: "(1 + 누적 TWR)^(365 / 경과일) - 1. 365일 이상의 이력만 연환산합니다." },
    { label: "최대 낙폭", value: mine.maxDrawdownPct, reference: market.maxDrawdownPct,
      color: "#ff5c6a", unit: "%", signed: false, status: `현재 낙폭 ${numberText(mine.currentDrawdownPct, "%")}`,
      formula: "TWR 기준가 / 그 시점까지의 최고 기준가 - 1 중 최솟값. 입출금 때문에 생긴 평가액 감소는 제외합니다." },
    { label: "연변동성", value: mine.volatilityPct, reference: market.volatilityPct,
      color: "#fbbf24", unit: "%", signed: false, status: report.sample.observations < 20 ? "평일 관측 20개 미만" : `평일 관측 ${report.sample.observations.toLocaleString()}개`,
      formula: "일별 TWR의 표본 표준편차 × √252. 투자자산이 있는 평일 관측이 최소 20개 필요합니다." },
    { label: "정보비율", value: relative.informationRatio, reference: null,
      color: "#4f8cff", unit: "", signed: false, status: report.sample.observations < 60 ? "평일 관측 60개 미만" : relative.informationRatio == null ? "추적오차 0 · 비율 미정의" : "초과수익 / 추적오차",
      formula: "평균(내 일수익률 - SPY 일수익률) / 표본 표준편차(수익률 차이) × √252. 관측 60개 이상, 추적오차가 0보다 클 때 계산합니다." },
  ];

  return (
    <div className="space-y-6" aria-label="성과 진단 보고서">
      <AnalysisPeriodLabel opts={opts} asOf={report.analysis.asOf} benchmarkAsOf={report.analysis.benchmarkAsOf} />
      <AnalysisNotice analysis={report.analysis} />
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-white/10 pb-4">
        <div className="space-y-1.5 min-w-0">
          <h2 className="text-lg text-[#e8eaf0] font-medium">성장·위험 균형 진단</h2>
          <div className="text-xs text-[#a0a8c0]">{report.scopeName} · 동일 매매 시점 SPY · {opts.includeDividend ? "배당 포함" : "배당 제외"} · {opts.includeFx ? "환차 포함" : "환차 제외"}</div>
          <div className="text-xs text-[#6b7494] font-mono">{report.sample.start && report.sample.end ? `${report.sample.start} ~ ${report.sample.end} · ${report.sample.calendarDays.toLocaleString()}일` : "분석 가능한 투자기간 없음"}</div>
        </div>
        <div role="status" aria-label="성장과 낙폭 비교" className="text-sm text-[#e8eaf0] border-l-2 border-[#00d4a1] pl-3 py-1">
          {comparisonLabel(report)}
          <div className="text-xs text-[#6b7494] mt-1">관측기간 내 S&P500 대비</div>
        </div>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4" aria-label="성과 진단 핵심 지표">
        {metrics.map(metric => <Card key={metric.label} className="p-4 min-w-0">
          <div role="group" aria-label={metric.label}>
            <h3 title={metric.formula} className="text-xs text-[#a0a8c0] cursor-help">{metric.label}</h3>
            <div className="text-2xl font-mono tabular-nums break-all my-3" style={{ color: metric.value == null ? "#6b7494" : metric.color }}>
              {numberText(metric.value, metric.unit, metric.signed)}
            </div>
            <div className="text-xs font-mono text-[#a0a8c0] min-h-4">{metric.label === "정보비율" ? `추적오차 ${numberText(relative.trackingErrorPct, "%")}` : `S&P500 ${numberText(metric.reference, metric.unit, metric.signed)}`}</div>
            <div className="text-xs text-[#6b7494] mt-2">{metric.status}</div>
          </div>
        </Card>)}
      </div>

      <section aria-label="누적 TWR 비교" className="border-y border-white/10 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-5">
          <h3 className="text-sm font-medium text-[#e8eaf0]">누적 성과 <span className="text-xs text-[#6b7494] font-normal ml-2">TWR 기준가 100</span></h3>
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-xs font-mono">
            <div className="flex gap-2 text-[#00d4a1]"><dt>내 포트폴리오</dt><dd>{numberText(mine.totalReturnPct, "%", true)}</dd></div>
            <div className="flex gap-2 text-[#4f8cff]"><dt>S&P500</dt><dd>{numberText(market.totalReturnPct, "%", true)}</dd></div>
          </dl>
        </div>
        {report.series.length ? <ResponsiveContainer width="100%" height={280} minWidth={0}>
          <LineChart data={report.series} margin={{ left: 4, right: 40, top: 8, bottom: 4 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={tickStyle} tickFormatter={date => String(date).slice(2).replace(/-/g, "/")} minTickGap={30} axisLine={false} tickLine={false} />
            <YAxis width={62} tick={tickStyle} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={100} stroke="#6b7494" strokeDasharray="2 3" />
            <Line dataKey="portfolio" name="내 포트폴리오" stroke="#00d4a1" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="benchmark" name="S&P500" stroke="#4f8cff" strokeWidth={1.5} dot={false} strokeDasharray="5 3" isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer> : <div className="h-[280px] flex items-center justify-center text-sm text-[#6b7494]">선택 범위의 성과 데이터가 없습니다.</div>}
      </section>

      <section aria-label="낙폭 비교" className="border-b border-white/10 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h3 className="text-sm font-medium text-[#e8eaf0]">고점 대비 낙폭</h3>
          <span className="text-xs text-[#6b7494]">일별 관측 · %</span>
        </div>
        {report.series.length ? <ResponsiveContainer width="100%" height={210} minWidth={0}>
          <AreaChart data={report.series} margin={{ left: 4, right: 40, top: 8, bottom: 4 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={tickStyle} tickFormatter={date => String(date).slice(2).replace(/-/g, "/")} minTickGap={30} axisLine={false} tickLine={false} />
            <YAxis width={62} tick={tickStyle} axisLine={false} tickLine={false} domain={["auto", 0]} tickFormatter={value => `${value}%`} />
            <Tooltip content={<CustomTooltip />} />
            <Area dataKey="portfolioDrawdown" name="내 낙폭(%)" stroke="#00d4a1" fill="#00d4a1" fillOpacity={0.08} dot={false} isAnimationActive={false} />
            <Area dataKey="benchmarkDrawdown" name="S&P500 낙폭(%)" stroke="#4f8cff" fill="none" strokeDasharray="5 3" dot={false} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer> : <div className="h-[210px] flex items-center justify-center text-sm text-[#6b7494]">낙폭을 계산할 데이터가 없습니다.</div>}
      </section>

      <section aria-label="월별 성과 일관성" className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-sm font-medium text-[#e8eaf0]">월별 성과 일관성</h3>
          <span className="text-xs font-mono text-[#a0a8c0]">상회 {relative.winningMonths}/{relative.comparableMonths} 완료월 · {numberText(relative.monthlyWinRatePct, "%")}</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 border-y border-white/10 py-4 text-sm">
          <div className="flex justify-between gap-3"><span className="text-[#6b7494]">기간 초과 TWR</span><span className={`font-mono ${tone(relative.excessReturnPp)}`}>{numberText(relative.excessReturnPp, "%p", true)}</span></div>
          <div className="flex justify-between gap-3"><span className="text-[#6b7494]">현재 낙폭</span><span className="font-mono text-[#e8eaf0]">{numberText(mine.currentDrawdownPct, "%")}</span></div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-mono" aria-label="월별 TWR 비교표">
            <thead><tr className="border-b border-white/10 text-[#6b7494]">
              {["월", "내 TWR", "S&P500 TWR", "초과수익(%p)"].map(label => <th key={label} scope="col" className="px-3 py-3 text-right first:text-left whitespace-nowrap font-normal">{label}</th>)}
            </tr></thead>
            <tbody>{[...report.monthly].reverse().map(row => <tr key={row.month} className="border-b border-white/5 hover:bg-white/[0.02]">
              <th scope="row" className="px-3 py-3 text-left whitespace-nowrap text-[#a0a8c0] font-normal">{row.month}{row.partial && <span title="기간 시작 또는 종료로 일부 날짜만 포함된 달이며 월별 상회 비율에서는 제외됩니다." className="ml-2 text-[#6b7494]">일부</span>}</th>
              <td className={`px-3 py-3 text-right whitespace-nowrap ${tone(row.portfolio)}`}>{numberText(row.portfolio, "%", true)}</td>
              <td className="px-3 py-3 text-right whitespace-nowrap text-[#4f8cff]">{numberText(row.benchmark, "%", true)}</td>
              <td className={`px-3 py-3 text-right whitespace-nowrap ${tone(row.excessPp)}`}>{numberText(row.excessPp, "", true)}</td>
            </tr>)}</tbody>
          </table>
          {!report.monthly.length && <div className="text-center text-xs text-[#6b7494] py-8">비교할 월별 자료가 없습니다.</div>}
        </div>
      </section>

      <details className="border-t border-white/10 pt-4 text-xs text-[#a0a8c0]">
        <summary className="cursor-pointer text-[#e8eaf0]">산식과 평가 가정</summary>
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-5 mt-4 leading-relaxed">
          {metrics.map(metric => <div key={metric.label}><dt className="text-[#e8eaf0] mb-1">{metric.label}</dt><dd>{metric.formula}</dd></div>)}
        </dl>
        <p className="mt-4 leading-relaxed text-[#6b7494]">입출금은 일말 발생, 배당은 현금 보유로 가정합니다. SPY도 같은 납입과 비례 인출을 적용합니다. 한국·미국 종가 시차, 수수료·세금, 누락된 거래는 결과에 영향을 줄 수 있습니다. 월별 상회 비율은 완전한 달만 비교하며, 개별 지표를 임의로 합산한 점수나 미래 수익 보장은 제공하지 않습니다.</p>
      </details>
    </div>
  );
}