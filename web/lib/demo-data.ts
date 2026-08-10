export type EquityPoint = { date: string; portfolio: number; benchmark: number; drawdown: number };

export const equityCurve: EquityPoint[] = [
  { date: "Jan", portfolio: 100, benchmark: 100, drawdown: 0 },
  { date: "Fev", portfolio: 104, benchmark: 102, drawdown: -1.2 },
  { date: "Mar", portfolio: 102, benchmark: 101, drawdown: -3.4 },
  { date: "Abr", portfolio: 109, benchmark: 105, drawdown: -0.8 },
  { date: "Mai", portfolio: 113, benchmark: 106, drawdown: -1.7 },
  { date: "Jun", portfolio: 111, benchmark: 108, drawdown: -3.1 },
  { date: "Jul", portfolio: 118, benchmark: 110, drawdown: -0.6 },
  { date: "Ago", portfolio: 122, benchmark: 112, drawdown: -1.1 },
  { date: "Set", portfolio: 120, benchmark: 111, drawdown: -2.4 },
  { date: "Out", portfolio: 127, benchmark: 114, drawdown: -0.4 },
  { date: "Nov", portfolio: 131, benchmark: 116, drawdown: -0.9 },
  { date: "Dez", portfolio: 136, benchmark: 119, drawdown: -0.2 },
];

export const recentRuns = [
  { id: "RUN-2481", name: "Carteira Ibovespa · RSI2", mode: "Carteira", date: "Hoje, 10:42", return: "+36,2%", sharpe: "1,41", status: "Concluído" },
  { id: "RUN-2478", name: "Walk-forward · 50 ativos", mode: "Otimizador", date: "Ontem, 18:17", return: "+24,8%", sharpe: "1,18", status: "Concluído" },
  { id: "RUN-2472", name: "PETR4 · custos conservadores", mode: "Por ativo", date: "08 ago, 14:09", return: "+18,4%", sharpe: "0,96", status: "Concluído" },
];

export const trades = [
  { ticker: "WEGE3", entry: "14/05/2026", exit: "19/05/2026", bars: 4, pnl: "+R$ 1.842", return: "+4,7%", reason: "RSI acumulado" },
  { ticker: "PETR4", entry: "03/06/2026", exit: "06/06/2026", bars: 3, pnl: "+R$ 1.124", return: "+3,1%", reason: "RSI acumulado" },
  { ticker: "ITUB4", entry: "17/06/2026", exit: "23/06/2026", bars: 5, pnl: "−R$ 418", return: "−1,2%", reason: "Tempo máximo" },
  { ticker: "VALE3", entry: "09/07/2026", exit: "14/07/2026", bars: 4, pnl: "+R$ 2.016", return: "+5,4%", reason: "RSI acumulado" },
];

export const screeningRows = [
  { ticker: "ABEV3", price: "R$ 14,82", rsi: 7.8, setup: "Entrada", liquidity: "R$ 186 mi", distance: "−8,4%", quality: 94 },
  { ticker: "ITUB4", price: "R$ 33,16", rsi: 9.1, setup: "Entrada", liquidity: "R$ 412 mi", distance: "−6,7%", quality: 91 },
  { ticker: "WEGE3", price: "R$ 47,38", rsi: 11.5, setup: "Atenção", liquidity: "R$ 228 mi", distance: "−5,9%", quality: 87 },
  { ticker: "RADL3", price: "R$ 24,04", rsi: 13.2, setup: "Atenção", liquidity: "R$ 98 mi", distance: "−7,1%", quality: 84 },
  { ticker: "RENT3", price: "R$ 38,72", rsi: 15.9, setup: "Monitorar", liquidity: "R$ 121 mi", distance: "−9,2%", quality: 78 },
];

export const optimizerRows = [
  { rsi: 5, exit: 65, return: 21.4, sharpe: 0.92, maxdd: -15.8 },
  { rsi: 5, exit: 70, return: 26.7, sharpe: 1.17, maxdd: -14.2 },
  { rsi: 5, exit: 75, return: 23.1, sharpe: 1.02, maxdd: -16.4 },
  { rsi: 10, exit: 65, return: 28.9, sharpe: 1.26, maxdd: -13.1 },
  { rsi: 10, exit: 70, return: 32.4, sharpe: 1.41, maxdd: -12.7 },
  { rsi: 10, exit: 75, return: 29.2, sharpe: 1.22, maxdd: -14.9 },
  { rsi: 15, exit: 65, return: 24.8, sharpe: 1.08, maxdd: -14.3 },
  { rsi: 15, exit: 70, return: 27.1, sharpe: 1.16, maxdd: -13.8 },
  { rsi: 15, exit: 75, return: 22.6, sharpe: 0.97, maxdd: -17.2 },
];

export const fundamentals = {
  ticker: "WEGE3",
  company: "WEG S.A.",
  sector: "Bens industriais · Máquinas e equipamentos",
  updatedAt: "30/06/2026",
  price: "R$ 47,38",
  marketCap: "R$ 198,8 bi",
  valuation: [
    ["P/L", "31,4×", "Mediana 5a: 34,8×"], ["EV/EBITDA", "22,6×", "Mediana 5a: 25,1×"], ["P/VP", "9,7×", "Setor: 3,2×"], ["Dividend yield", "1,4%", "12 meses"],
  ],
  profitability: [
    ["ROIC", "28,6%", "+3,2 p.p. em 3a"], ["ROE", "31,1%", "+2,4 p.p. em 3a"], ["Margem EBITDA", "22,8%", "+1,8 p.p. a/a"], ["Margem líquida", "17,2%", "+1,1 p.p. a/a"],
  ],
};
