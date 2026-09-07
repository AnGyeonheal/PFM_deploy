export type Stock = {
  ticker: string;
  name: string;
  nameKr: string;
  sector: string;
  currency: "KRW" | "USD";
  quantity: number;
  avgBuyPrice: number;
  avgBuyFx: number;
  currentPrice: number;
  currentFx: number;
  status: "holding" | "closed";
  dividendReceived: number;
};

export type Transaction = {
  id: string;
  date: string;
  ticker: string;
  name: string;
  type: "buy" | "sell" | "dividend";
  quantity: number;
  price: number;
  currency: "KRW" | "USD";
  fx: number;
  amount: number;
  source: "api" | "csv" | "manual";
};

export type DividendRecord = {
  id: string;
  date: string;
  ticker: string;
  name: string;
  amount: number;
  currency: "KRW" | "USD";
  fx: number;
  amountKRW: number;
  verified: boolean;
};

export const currentFx = 1345.5;

export const stocks: Stock[] = [
  { ticker: "AAPL", name: "Apple Inc.", nameKr: "애플", sector: "기술", currency: "USD", quantity: 50, avgBuyPrice: 168.4, avgBuyFx: 1312, currentPrice: 195.2, currentFx: 1345.5, status: "holding", dividendReceived: 148000 },
  { ticker: "MSFT", name: "Microsoft Corp.", nameKr: "마이크로소프트", sector: "기술", currency: "USD", quantity: 30, avgBuyPrice: 342.1, avgBuyFx: 1298, currentPrice: 415.3, currentFx: 1345.5, status: "holding", dividendReceived: 98000 },
  { ticker: "NVDA", name: "NVIDIA Corp.", nameKr: "엔비디아", sector: "기술", currency: "USD", quantity: 40, avgBuyPrice: 412.0, avgBuyFx: 1325, currentPrice: 875.4, currentFx: 1345.5, status: "holding", dividendReceived: 12000 },
  { ticker: "005930", name: "Samsung Electronics", nameKr: "삼성전자", sector: "기술", currency: "KRW", quantity: 200, avgBuyPrice: 71500, avgBuyFx: 1, currentPrice: 74200, currentFx: 1, status: "holding", dividendReceived: 360000 },
  { ticker: "GOOGL", name: "Alphabet Inc.", nameKr: "알파벳", sector: "기술", currency: "USD", quantity: 25, avgBuyPrice: 138.5, avgBuyFx: 1310, currentPrice: 172.8, currentFx: 1345.5, status: "holding", dividendReceived: 0 },
  { ticker: "035420", name: "NAVER Corp.", nameKr: "네이버", sector: "인터넷", currency: "KRW", quantity: 30, avgBuyPrice: 195000, avgBuyFx: 1, currentPrice: 182000, currentFx: 1, status: "holding", dividendReceived: 75000 },
  { ticker: "AMZN", name: "Amazon.com Inc.", nameKr: "아마존", sector: "유통/클라우드", currency: "USD", quantity: 20, avgBuyPrice: 176.2, avgBuyFx: 1308, currentPrice: 202.3, currentFx: 1345.5, status: "holding", dividendReceived: 0 },
  { ticker: "TSLA", name: "Tesla Inc.", nameKr: "테슬라", sector: "전기차", currency: "USD", quantity: 15, avgBuyPrice: 245.3, avgBuyFx: 1335, currentPrice: 189.4, currentFx: 1345.5, status: "holding", dividendReceived: 0 },
];

export const closedStocks: Stock[] = [
  { ticker: "META", name: "Meta Platforms", nameKr: "메타", sector: "기술", currency: "USD", quantity: 0, avgBuyPrice: 198.0, avgBuyFx: 1305, currentPrice: 548.6, currentFx: 1345.5, status: "closed", dividendReceived: 0 },
];

function calcStock(s: Stock) {
  if (s.currency === "USD") {
    const buyTotal = s.quantity * s.avgBuyPrice * s.avgBuyFx;
    const currentTotal = s.quantity * s.currentPrice * s.currentFx;
    const unrealizedPnL = currentTotal - buyTotal;
    const pureStockPnL = s.quantity * (s.currentPrice - s.avgBuyPrice) * s.avgBuyFx;
    const fxPnL = unrealizedPnL - pureStockPnL;
    return { buyTotal, currentTotal, unrealizedPnL, pureStockPnL, fxPnL, returnPct: (unrealizedPnL / buyTotal) * 100 };
  } else {
    const buyTotal = s.quantity * s.avgBuyPrice;
    const currentTotal = s.quantity * s.currentPrice;
    const unrealizedPnL = currentTotal - buyTotal;
    return { buyTotal, currentTotal, unrealizedPnL, pureStockPnL: unrealizedPnL, fxPnL: 0, returnPct: (unrealizedPnL / buyTotal) * 100 };
  }
}

export function getStockMetrics(s: Stock) {
  return calcStock(s);
}

export const totalMetrics = (() => {
  let totalBuy = 0, totalCurrent = 0, totalUnrealized = 0, totalFx = 0, totalDividend = 0;
  for (const s of stocks) {
    const m = calcStock(s);
    totalBuy += m.buyTotal;
    totalCurrent += m.currentTotal;
    totalUnrealized += m.unrealizedPnL;
    totalFx += m.fxPnL;
    totalDividend += s.dividendReceived;
  }
  // Realized P&L from closed stocks (simulated)
  const realizedPnL = 4_820_000;
  const totalPnL = totalUnrealized + realizedPnL + totalDividend;
  return {
    totalBuy,
    totalCurrent,
    cash: 3_450_000,
    totalAsset: totalCurrent + 3_450_000,
    unrealizedPnL: totalUnrealized,
    realizedPnL,
    dividendPnL: totalDividend,
    fxPnL: totalFx,
    pureStockPnL: totalUnrealized - totalFx,
    totalPnL,
    returnPct: (totalPnL / totalBuy) * 100,
  };
})();

export const performanceData = [
  { month: "Jan", portfolio: 100, sp500: 100, twr: 100 },
  { month: "Feb", portfolio: 104.2, sp500: 102.8, twr: 103.1 },
  { month: "Mar", portfolio: 99.5, sp500: 100.4, twr: 98.8 },
  { month: "Apr", portfolio: 107.8, sp500: 103.9, twr: 106.2 },
  { month: "May", portfolio: 113.4, sp500: 106.7, twr: 111.5 },
  { month: "Jun", portfolio: 119.1, sp500: 109.2, twr: 116.8 },
  { month: "Jul", portfolio: 115.6, sp500: 108.1, twr: 113.4 },
  { month: "Aug", portfolio: 124.3, sp500: 112.5, twr: 121.7 },
  { month: "Sep", portfolio: 130.8, sp500: 115.3, twr: 127.4 },
  { month: "Oct", portfolio: 127.2, sp500: 113.8, twr: 124.1 },
  { month: "Nov", portfolio: 136.4, sp500: 118.6, twr: 132.9 },
  { month: "Dec", portfolio: 142.7, sp500: 122.1, twr: 138.5 },
];

export const monthlyAlpha = [
  { month: "Jan", alpha: 1.4 }, { month: "Feb", alpha: -0.3 }, { month: "Mar", alpha: 0.9 },
  { month: "Apr", alpha: 2.1 }, { month: "May", alpha: 1.8 }, { month: "Jun", alpha: 2.4 },
  { month: "Jul", alpha: -0.8 }, { month: "Aug", alpha: 3.1 }, { month: "Sep", alpha: 2.7 },
  { month: "Oct", alpha: -0.5 }, { month: "Nov", alpha: 2.9 }, { month: "Dec", alpha: 1.6 },
];

export const rollingBeta = [
  { month: "Jan", beta: 1.18 }, { month: "Feb", beta: 1.22 }, { month: "Mar", beta: 1.15 },
  { month: "Apr", beta: 1.09 }, { month: "May", beta: 1.03 }, { month: "Jun", beta: 0.98 },
  { month: "Jul", beta: 1.05 }, { month: "Aug", beta: 0.97 }, { month: "Sep", beta: 0.94 },
  { month: "Oct", beta: 1.01 }, { month: "Nov", beta: 0.96 }, { month: "Dec", beta: 0.93 },
];

export const fxData = [
  { month: "Jan", fx: 1308, avgBuy: 1312 }, { month: "Feb", fx: 1315, avgBuy: 1312 },
  { month: "Mar", fx: 1298, avgBuy: 1312 }, { month: "Apr", fx: 1321, avgBuy: 1315 },
  { month: "May", fx: 1334, avgBuy: 1315 }, { month: "Jun", fx: 1342, avgBuy: 1318 },
  { month: "Jul", fx: 1328, avgBuy: 1318 }, { month: "Aug", fx: 1339, avgBuy: 1318 },
  { month: "Sep", fx: 1352, avgBuy: 1320 }, { month: "Oct", fx: 1347, avgBuy: 1320 },
  { month: "Nov", fx: 1341, avgBuy: 1320 }, { month: "Dec", fx: 1345, avgBuy: 1322 },
];

export const transactions: Transaction[] = [
  { id: "t1", date: "2024-12-15", ticker: "AAPL", name: "애플", type: "buy", quantity: 10, price: 193.4, currency: "USD", fx: 1342, amount: 2594228, source: "api" },
  { id: "t2", date: "2024-12-10", ticker: "NVDA", name: "엔비디아", type: "buy", quantity: 5, price: 862.1, currency: "USD", fx: 1340, amount: 5775470, source: "api" },
  { id: "t3", date: "2024-12-05", ticker: "005930", name: "삼성전자", type: "sell", quantity: 50, price: 75400, currency: "KRW", fx: 1, amount: 3770000, source: "csv" },
  { id: "t4", date: "2024-11-28", ticker: "MSFT", name: "마이크로소프트", type: "dividend", quantity: 0, price: 0, currency: "USD", fx: 1338, amount: 98000, source: "csv" },
  { id: "t5", date: "2024-11-20", ticker: "GOOGL", name: "알파벳", type: "buy", quantity: 5, price: 168.9, currency: "USD", fx: 1331, amount: 1124048, source: "manual" },
  { id: "t6", date: "2024-11-15", ticker: "TSLA", name: "테슬라", type: "sell", quantity: 10, price: 198.2, currency: "USD", fx: 1328, amount: 2631256, source: "api" },
  { id: "t7", date: "2024-11-01", ticker: "035420", name: "네이버", type: "buy", quantity: 10, price: 185000, currency: "KRW", fx: 1, amount: 1850000, source: "csv" },
  { id: "t8", date: "2024-10-22", ticker: "AMZN", name: "아마존", type: "buy", quantity: 5, price: 191.3, currency: "USD", fx: 1325, amount: 1266363, source: "api" },
  { id: "t9", date: "2024-10-15", ticker: "AAPL", name: "애플", type: "dividend", quantity: 0, price: 0, currency: "USD", fx: 1322, amount: 74000, source: "api" },
  { id: "t10", date: "2024-09-30", ticker: "META", name: "메타", type: "sell", quantity: 20, price: 542.8, currency: "USD", fx: 1318, amount: 14309408, source: "csv" },
];

export const dividends: DividendRecord[] = [
  { id: "d1", date: "2024-12-15", ticker: "AAPL", name: "애플", amount: 0.25, currency: "USD", fx: 1342, amountKRW: 1342 * 0.25 * 50, verified: true },
  { id: "d2", date: "2024-11-28", ticker: "MSFT", name: "마이크로소프트", amount: 0.75, currency: "USD", fx: 1338, amountKRW: 1338 * 0.75 * 30, verified: true },
  { id: "d3", date: "2024-11-01", ticker: "005930", name: "삼성전자", amount: 361, currency: "KRW", fx: 1, amountKRW: 361 * 200, verified: false },
  { id: "d4", date: "2024-10-15", ticker: "AAPL", name: "애플", amount: 0.25, currency: "USD", fx: 1322, amountKRW: 1322 * 0.25 * 50, verified: true },
  { id: "d5", date: "2024-09-20", ticker: "MSFT", name: "마이크로소프트", amount: 0.75, currency: "USD", fx: 1315, amountKRW: 1315 * 0.75 * 30, verified: true },
];

export const stockBenchmarkData: Array<{ ticker: string; name: string; alpha: number; beta: number; alphaContrib: number; betaContrib: number; returnPct: number }> = [
  { ticker: "AAPL", name: "애플", alpha: 8.4, beta: 1.12, alphaContrib: 0.71, betaContrib: 0.94, returnPct: 15.9 },
  { ticker: "MSFT", name: "마이크로소프트", alpha: 6.2, beta: 0.98, alphaContrib: 0.45, betaContrib: 0.71, returnPct: 21.4 },
  { ticker: "NVDA", name: "엔비디아", alpha: 42.1, beta: 1.87, alphaContrib: 2.48, betaContrib: 1.10, returnPct: 112.5 },
  { ticker: "005930", name: "삼성전자", alpha: -5.8, beta: 0.71, alphaContrib: -0.53, betaContrib: 0.65, returnPct: 3.8 },
  { ticker: "GOOGL", name: "알파벳", alpha: 12.3, beta: 1.04, alphaContrib: 0.31, betaContrib: 0.26, returnPct: 24.8 },
  { ticker: "035420", name: "네이버", alpha: -14.2, beta: 0.82, alphaContrib: -0.43, betaContrib: 0.25, returnPct: -6.7 },
  { ticker: "AMZN", name: "아마존", alpha: 9.4, beta: 1.15, alphaContrib: 0.19, betaContrib: 0.23, returnPct: 14.8 },
  { ticker: "TSLA", name: "테슬라", alpha: -18.7, beta: 1.74, alphaContrib: -0.28, betaContrib: 0.26, returnPct: -22.8 },
];

export const allocationData = [
  { name: "미국 기술주", value: 52.4, color: "#00d4a1" },
  { name: "국내 주식", value: 22.8, color: "#4f8cff" },
  { name: "현금", value: 12.1, color: "#6b7494" },
  { name: "미국 기타", value: 12.7, color: "#a78bfa" },
];
