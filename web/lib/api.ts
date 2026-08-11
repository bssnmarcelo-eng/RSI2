export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type NorgateStatus = {
  available: boolean;
  package_installed: boolean;
  updater_running: boolean;
  watchlists: number;
  databases: number;
  message: string;
};

export type NorgateCatalog = {
  watchlists: string[];
  databases: string[];
  adjustments: string[];
  frequencies: string[];
};

export type RunTrade = Record<string, string | number | boolean | null>;

export type RunSummary = {
  id: string;
  name: string;
  mode: string;
  status: RunStatus;
  progress: number;
  source: "inline" | "norgate";
  created_at: string;
  metrics: Record<string, number>;
  warnings: string[];
  trade_count: number;
  equity: Array<{ date: string; value: number }>;
  trades: RunTrade[];
  data_summary: Record<string, string | number | boolean | string[]>;
  scenario_metrics: Record<string, Record<string, number>>;
  scenario_equity: Record<string, Array<{ date: string; value: number }>>;
  error?: string | null;
};

export type NorgateBacktestPayload = {
  name: string;
  mode: "portfolio" | "per_asset";
  collection_type: "watchlist" | "database";
  collection_name: string;
  symbols: string[];
  use_entire_collection: boolean;
  start_date: string;
  end_date: string;
  frequency: string;
  adjustment: string;
  restrict_to_index: boolean;
  index_name?: string;
  strategy: {
    instrument?: "stock" | "synthetic_atm_call";
    options?: {
      pricing_model: "black_scholes" | "binomial";
      strike_mode: "exact_atm" | "rounded" | "otm_pct";
      strike_interval: number;
      otm_pct: number;
      target_dte: number;
      roll_dte: number;
      volatility_window: number;
      iv_multiplier: number;
      iv_floor: number;
      iv_cap: number;
      iv_scenario: number;
      risk_free_mode: "norgate" | "fixed";
      risk_free_symbol: string;
      risk_free_rate: number;
      dividend_yield: number;
      spread_pct: number;
      minimum_half_spread: number;
      commission_per_contract: number;
      sizing_mode: "premium_risk" | "delta_equivalent";
      premium_risk_pct: number;
      binomial_steps: number;
    };
    rsi_period: number;
    rsi_entry: number;
    use_hammer: boolean;
    hammer_percentile: number;
    hammer_require_bullish_close: boolean;
    hammer_use_atr_filter: boolean;
    hammer_atr_period: number;
    hammer_atr_multiple: number;
    use_rsi_exit: boolean;
    rsi_exit: number;
    use_max_bars: boolean;
    max_bars: number;
    use_profit_target: boolean;
    profit_target_pct: number;
    use_stop_loss: boolean;
    stop_loss_pct: number;
    use_sma_exit: boolean;
    sma_period: number;
    use_signal_low_stop: boolean;
    use_rsi_cum_exit: boolean;
    rsi_cum_periods: number;
    rsi_cum_threshold: number;
    initial_capital: number;
    commission_fixed: number;
    commission_pct: number;
    slippage_bps: number;
  };
  max_positions: number;
  pct_per_trade: number;
};

export type FundamentalMetric = { token: string; label: string; unit: string; value: number | string | null; formatted: string; reference_date: string | null };
export type FundamentalResponse = {
  ticker: string;
  source: "norgate";
  overview: Record<string, string | null>;
  price: number | null;
  fields_with_data: number;
  fields_total: number;
  categories: Array<{ title: string; help: string; metrics: FundamentalMetric[] }>;
};

export type ScreeningResponse = {
  source: "norgate";
  as_of: string;
  count: number;
  assets_loaded: number;
  skipped: string[];
  warnings: string[];
  results: Array<{ ticker: string; date: string; close: number; rsi: number; entry_signal: boolean; pattern: string; average_turnover: number; distance_sma_200: number | null }>;
};

export type OptimizationResponse = {
  source: "norgate"; validation: "split" | "walk_forward"; objective: string; split_date: string | null; assets_loaded: number; symbols: string[]; skipped: string[]; warnings: string[]; results: Array<Record<string, string | number | boolean | null>>;
};

export const API_STORAGE_KEY = "rsi2.api-url.v1";
export const DEFAULT_API_URL = process.env.NEXT_PUBLIC_RSI2_API_URL || "http://127.0.0.1:8000";

export function getApiBase(): string {
  if (typeof window === "undefined") return DEFAULT_API_URL;
  return window.localStorage.getItem(API_STORAGE_KEY) || DEFAULT_API_URL;
}

export function saveApiBase(value: string): string {
  const normalized = value.trim().replace(/\/$/, "") || DEFAULT_API_URL;
  window.localStorage.setItem(API_STORAGE_KEY, normalized);
  return normalized;
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `API RSI2 respondeu ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getNorgateStatus(): Promise<NorgateStatus> {
  return apiRequest("/v1/data-sources/norgate/status");
}

export function getNorgateCatalog(): Promise<NorgateCatalog> {
  return apiRequest("/v1/data-sources/norgate/catalog");
}

export function getNorgateSymbols(collectionType: "watchlist" | "database", collectionName: string): Promise<{ count: number; symbols: string[] }> {
  const query = new URLSearchParams({ collection_type: collectionType, collection_name: collectionName });
  return apiRequest(`/v1/data-sources/norgate/symbols?${query}`);
}

export function createNorgateBacktest(payload: NorgateBacktestPayload): Promise<RunSummary> {
  return apiRequest("/v1/backtests/norgate", { method: "POST", body: JSON.stringify(payload) });
}

export function getRun(runId: string): Promise<RunSummary> {
  return apiRequest(`/v1/runs/${encodeURIComponent(runId)}`);
}

export function getRuns(): Promise<RunSummary[]> {
  return apiRequest("/v1/runs");
}

export function getFundamentals(ticker: string): Promise<FundamentalResponse> {
  return apiRequest(`/v1/fundamentals/${encodeURIComponent(ticker.trim().toUpperCase())}`);
}

export function runNorgateScreening(payload: {
  collection_type: "watchlist" | "database"; collection_name: string; symbols: string[]; use_entire_collection: boolean; start_date: string; end_date: string; frequency: string; adjustment: string; rsi_period: number; rsi_max: number; min_price: number; min_average_turnover: number;
}): Promise<ScreeningResponse> {
  return apiRequest("/v1/screenings/norgate", { method: "POST", body: JSON.stringify(payload) });
}

export function runNorgateOptimization(payload: NorgateBacktestPayload & { parameter_ranges: Record<string, number[]>; validation: "split" | "walk_forward"; objective: string; splits: number; min_trades: number }): Promise<OptimizationResponse> {
  return apiRequest("/v1/optimizations/norgate", { method: "POST", body: JSON.stringify(payload) });
}

export async function deleteRun(runId: string): Promise<void> {
  const response = await fetch(`${getApiBase()}/v1/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
  if (!response.ok) throw new Error(`Não foi possível excluir a execução (${response.status}).`);
}

export async function waitForRun(runId: string, onProgress: (run: RunSummary) => void, timeoutMs = 15 * 60_000): Promise<RunSummary> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const run = await getRun(runId);
    onProgress(run);
    if (run.status === "completed") return run;
    if (run.status === "failed" || run.status === "cancelled") throw new Error(run.error || "A execução não foi concluída.");
    await new Promise((resolve) => window.setTimeout(resolve, 700));
  }
  throw new Error("A execução excedeu o tempo limite de 15 minutos.");
}
