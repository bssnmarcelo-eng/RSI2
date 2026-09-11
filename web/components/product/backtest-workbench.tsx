"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Database,
  Download,
  Play,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { EquityChart } from "@/components/product/equity-chart";
import { MetricCard } from "@/components/product/metric-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  createNorgateBacktest,
  getNorgateCatalog,
  getNorgateStatus,
  getNorgateSymbols,
  waitForRun,
  type NorgateBacktestPayload,
  type NorgateCatalog,
  type NorgateStatus,
  type RunSummary,
} from "@/lib/api";

const steps = ["Universo", "Estratégia", "Custos e sizing", "Revisão"];
const preferredSymbols = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "JPM", "LLY", "COST"];

type CollectionType = "watchlist" | "database";
type BacktestMode = "portfolio" | "per_asset";
type InstrumentType = "stock" | "synthetic_atm_call";
type OptionSettings = NonNullable<NorgateBacktestPayload["strategy"]["options"]>;
type PositionManagement = {
  use_rsi_exit: boolean;
  use_max_bars: boolean;
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
};
type HammerSettings = {
  use_hammer: boolean;
  hammer_percentile: number;
  hammer_require_bullish_close: boolean;
  hammer_use_atr_filter: boolean;
  hammer_atr_period: number;
  hammer_atr_multiple: number;
};
type BreadthSettings = {
  enabled: boolean;
  smaPeriod: number;
  thresholdPct: number;
};
type Sma200Filters = {
  price: "any" | "above" | "below";
  slope: "any" | "rising" | "falling";
};

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <div className="space-y-2"><Label>{label}</Label>{children}{hint ? <p className="text-xs leading-5 text-muted-foreground">{hint}</p> : null}</div>;
}

function inferIndexName(name: string) {
  return name.replace(/ Current (&|and) Past$/i, "").trim();
}

function parseSymbols(value: string) {
  return [...new Set(value.split(/[\s,;]+/).map((symbol) => symbol.trim().toUpperCase()).filter(Boolean))];
}

export function BacktestWorkbench() {
  const [step, setStep] = useState(0);
  const [mode, setMode] = useState<BacktestMode>("portfolio");
  const [status, setStatus] = useState<NorgateStatus | null>(null);
  const [catalog, setCatalog] = useState<NorgateCatalog | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [collectionType, setCollectionType] = useState<CollectionType>("watchlist");
  const [collectionName, setCollectionName] = useState("");
  const [availableSymbols, setAvailableSymbols] = useState<string[]>([]);
  const [symbolsText, setSymbolsText] = useState("");
  const [useEntireCollection, setUseEntireCollection] = useState(true);
  const [startDate, setStartDate] = useState("2021-01-01");
  const [endDate, setEndDate] = useState("2026-08-10");
  const [frequency, setFrequency] = useState("Semanal");
  const [adjustment, setAdjustment] = useState("Total Return (splits + dividendos)");
  const [restrictToIndex, setRestrictToIndex] = useState(true);
  const [indexName, setIndexName] = useState("");
  const [rsiPeriod, setRsiPeriod] = useState(2);
  const [rsiEntry, setRsiEntry] = useState(10);
  const [sma200Filters, setSma200Filters] = useState<Sma200Filters>({ price: "any", slope: "any" });
  const [hammer, setHammer] = useState<HammerSettings>({
    use_hammer: true,
    hammer_percentile: 0.33,
    hammer_require_bullish_close: false,
    hammer_use_atr_filter: true,
    hammer_atr_period: 14,
    hammer_atr_multiple: 1,
  });
  const [breadth, setBreadth] = useState<BreadthSettings>({
    enabled: true,
    smaPeriod: 40,
    thresholdPct: 50,
  });
  const [rsiExit, setRsiExit] = useState(70);
  const [maxBars, setMaxBars] = useState(7);
  const [management, setManagement] = useState<PositionManagement>({
    use_rsi_exit: true,
    use_max_bars: true,
    use_profit_target: false,
    profit_target_pct: 5,
    use_stop_loss: false,
    stop_loss_pct: 3,
    use_sma_exit: false,
    sma_period: 5,
    use_signal_low_stop: false,
    use_rsi_cum_exit: false,
    rsi_cum_periods: 2,
    rsi_cum_threshold: 100,
  });
  const [initialCapital, setInitialCapital] = useState(100000);
  const [maxPositions, setMaxPositions] = useState(10);
  const [pctPerTrade, setPctPerTrade] = useState(10);
  const [commissionFixed, setCommissionFixed] = useState(0);
  const [commissionPct, setCommissionPct] = useState(0.03);
  const [slippagePct, setSlippagePct] = useState(0.10);
  const [instrument, setInstrument] = useState<InstrumentType>("stock");
  const [options, setOptions] = useState<OptionSettings>({
    pricing_model: "black_scholes",
    strike_mode: "exact_atm",
    strike_interval: 1,
    otm_pct: 10,
    target_dte: 45,
    roll_dte: 0,
    volatility_window: 20,
    iv_multiplier: 1.2,
    iv_floor: 0.10,
    iv_cap: 2,
    iv_scenario: 1,
    risk_free_mode: "norgate",
    risk_free_symbol: "%3MTCM",
    risk_free_rate: 0.04,
    dividend_yield: 0,
    spread_pct: 0.08,
    minimum_half_spread: 0.01,
    commission_per_contract: 0.65,
    sizing_mode: "premium_risk",
    premium_risk_pct: 10,
    binomial_steps: 200,
  });
  const [running, setRunning] = useState(false);
  const [runState, setRunState] = useState<RunSummary | null>(null);
  const [result, setResult] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedSymbols = useMemo(() => parseSymbols(symbolsText), [symbolsText]);
  const collections = collectionType === "watchlist" ? catalog?.watchlists ?? [] : catalog?.databases ?? [];

  useEffect(() => {
    let active = true;
    Promise.all([getNorgateStatus(), getNorgateCatalog()])
      .then(([nextStatus, nextCatalog]) => {
        if (!active) return;
        setStatus(nextStatus);
        setCatalog(nextCatalog);
        const preferred = nextCatalog.watchlists.find((name) => name.includes("S&P 500 Current & Past")) ?? nextCatalog.watchlists[0] ?? "";
        setCollectionName(preferred);
        setIndexName(inferIndexName(preferred));
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Não foi possível consultar a API local.");
      })
      .finally(() => { if (active) setLoadingData(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!collectionName) return;
    let active = true;
    getNorgateSymbols(collectionType, collectionName)
      .then(({ symbols }) => {
        if (!active) return;
        setAvailableSymbols(symbols);
        const suggested = preferredSymbols.filter((symbol) => symbols.includes(symbol));
        setSymbolsText((suggested.length ? suggested : symbols.slice(0, 10)).join(", "));
        setIndexName(inferIndexName(collectionName));
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Não foi possível carregar os símbolos.");
      })
      .finally(() => { if (active) setLoadingData(false); });
    return () => { active = false; };
  }, [collectionName, collectionType]);

  function changeCollectionType(value: CollectionType) {
    setCollectionType(value);
    const names = value === "watchlist" ? catalog?.watchlists : catalog?.databases;
    setCollectionName(names?.[0] ?? "");
  }

  function changeMode(value: BacktestMode) {
    setMode(value);
    if (value === "per_asset") {
      setUseEntireCollection(false);
    } else if (breadth.enabled) {
      setUseEntireCollection(true);
      setRestrictToIndex(true);
    }
  }

  function changeBreadth(changes: Partial<BreadthSettings>) {
    setBreadth((current) => ({ ...current, ...changes }));
    if (changes.enabled) {
      setUseEntireCollection(true);
      setRestrictToIndex(true);
    }
  }

  function changeInstrument(value: InstrumentType) {
    setInstrument(value);
  }

  async function run() {
    if (!collectionName || (!useEntireCollection && selectedSymbols.length === 0)) {
      setError("Selecione uma coleção e informe pelo menos um símbolo.");
      return;
    }
    if (mode === "portfolio" && breadth.enabled && (!useEntireCollection || !restrictToIndex)) {
      setError("Para calcular o breadth do índice corretamente, use a coleção inteira e ative os constituintes point-in-time.");
      return;
    }
    setRunning(true);
    setError(null);
    setRunState(null);
    const payload: NorgateBacktestPayload = {
      name: `${mode === "portfolio" ? "Carteira" : "Ativo"} ${collectionName} · RSI2`,
      mode,
      collection_type: collectionType,
      collection_name: collectionName,
      symbols: useEntireCollection ? [] : selectedSymbols,
      use_entire_collection: useEntireCollection,
      start_date: startDate,
      end_date: endDate,
      frequency,
      adjustment,
      restrict_to_index: restrictToIndex,
      index_name: restrictToIndex ? indexName : undefined,
      strategy: {
        instrument,
        options,
        rsi_period: rsiPeriod,
        rsi_entry: rsiEntry,
        sma_200_price_filter: sma200Filters.price,
        sma_200_slope_filter: sma200Filters.slope,
        ...hammer,
        ...management,
        rsi_exit: rsiExit,
        max_bars: maxBars,
        initial_capital: initialCapital,
        commission_fixed: commissionFixed,
        commission_pct: commissionPct / 100,
        slippage_bps: slippagePct * 100,
      },
      max_positions: mode === "portfolio" ? maxPositions : 1,
      pct_per_trade: mode === "portfolio" ? pctPerTrade : 100,
      use_breadth_filter: mode === "portfolio" && breadth.enabled,
      breadth_sma_period: breadth.smaPeriod,
      breadth_threshold_pct: breadth.thresholdPct,
    };
    try {
      const queued = await createNorgateBacktest(payload);
      setRunState(queued);
      const completed = await waitForRun(queued.id, setRunState);
      setResult(completed);
      toast.success("Backtest Norgate concluído.");
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "Falha ao executar o backtest.";
      setError(message);
      toast.error(message);
    } finally {
      setRunning(false);
    }
  }

  if (result) return <BacktestResult run={result} onNew={() => { setResult(null); setRunState(null); setStep(0); }} />;

  return <div>
    <Tabs value={mode} onValueChange={(value) => changeMode(value as BacktestMode)} className="mb-6"><TabsList><TabsTrigger value="portfolio">Carteira</TabsTrigger><TabsTrigger value="per_asset">Por ativo</TabsTrigger></TabsList></Tabs>
    <Card className="shadow-none">
      <CardHeader className="border-b"><div className="grid grid-cols-4 gap-2" aria-label={`Etapa ${step + 1} de 4: ${steps[step]}`}>{steps.map((label, index) => <button type="button" key={label} onClick={() => setStep(index)} className="group min-h-14 text-left" aria-current={index === step ? "step" : undefined}><span className={`mb-2 block h-1 rounded-full ${index <= step ? "bg-primary" : "bg-muted"}`} /><span className={`hidden text-xs md:block ${index === step ? "font-medium" : "text-muted-foreground"}`}>{index < step ? <Check className="mr-1 inline size-3.5" /> : null}{index + 1}. {label}</span><span className="sr-only md:hidden">{label}</span></button>)}</div></CardHeader>
      <CardContent className="p-5 md:p-8">
        {step === 0 ? <UniverseStep status={status} catalog={catalog} loading={loadingData} collectionType={collectionType} collectionName={collectionName} collections={collections} availableCount={availableSymbols.length} symbolsText={symbolsText} useEntireCollection={useEntireCollection} startDate={startDate} endDate={endDate} frequency={frequency} adjustment={adjustment} restrictToIndex={restrictToIndex} indexName={indexName} onCollectionType={changeCollectionType} onCollectionName={setCollectionName} onSymbolsText={setSymbolsText} onEntireCollection={setUseEntireCollection} onStartDate={setStartDate} onEndDate={setEndDate} onFrequency={setFrequency} onAdjustment={setAdjustment} onRestrictToIndex={setRestrictToIndex} onIndexName={setIndexName} /> : null}
        {step === 1 ? <StrategyStep mode={mode} rsiPeriod={rsiPeriod} rsiEntry={rsiEntry} rsiExit={rsiExit} maxBars={maxBars} hammer={hammer} breadth={breadth} sma200Filters={sma200Filters} management={management} onRsiPeriod={setRsiPeriod} onRsiEntry={setRsiEntry} onRsiExit={setRsiExit} onMaxBars={setMaxBars} onHammer={(changes) => setHammer((current) => ({ ...current, ...changes }))} onBreadth={changeBreadth} onSma200Filters={(changes) => setSma200Filters((current) => ({ ...current, ...changes }))} onManagement={(changes) => setManagement((current) => ({ ...current, ...changes }))} /> : null}
        {step === 2 ? <div className="space-y-8"><OptionsPanel instrument={instrument} options={options} onInstrument={changeInstrument} onOptions={(changes) => setOptions((current) => ({ ...current, ...changes }))} /><CostsStep initialCapital={initialCapital} maxPositions={maxPositions} pctPerTrade={pctPerTrade} commissionFixed={commissionFixed} commissionPct={commissionPct} slippagePct={slippagePct} mode={mode} onInitialCapital={setInitialCapital} onMaxPositions={setMaxPositions} onPctPerTrade={setPctPerTrade} onCommissionFixed={setCommissionFixed} onCommissionPct={setCommissionPct} onSlippagePct={setSlippagePct} /></div> : null}
        {step === 3 ? <div className="space-y-6"><ReviewStep mode={mode} collectionName={collectionName} symbolCount={useEntireCollection ? availableSymbols.length : selectedSymbols.length} startDate={startDate} endDate={endDate} frequency={frequency} adjustment={adjustment} rsiPeriod={rsiPeriod} rsiEntry={rsiEntry} rsiExit={rsiExit} maxBars={maxBars} hammer={hammer} breadth={breadth} sma200Filters={sma200Filters} management={management} initialCapital={initialCapital} maxPositions={maxPositions} pctPerTrade={pctPerTrade} restrictToIndex={restrictToIndex} />{instrument === "synthetic_atm_call" ? <OptionReview options={options} /> : null}</div> : null}
        {error ? <div className="mt-6 flex gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert"><CircleAlert className="size-5 shrink-0" /><div><strong>Não foi possível continuar</strong><p className="mt-1 text-foreground/75">{error}</p></div></div> : null}
        {running ? <div className="mt-8 rounded-xl border bg-muted/40 p-5" role="status"><div className="mb-3 flex justify-between gap-4 text-sm"><span>{runState?.status === "queued" ? "Na fila de execução…" : "Carregando dados e calculando o backtest…"}</span><span className="metric-number">{Math.round((runState?.progress ?? 0) * 100)}%</span></div><Progress value={(runState?.progress ?? 0) * 100} /><p className="mt-2 text-xs text-muted-foreground">{runState?.id ? `Execução ${runState.id} · dados processados localmente` : "Enviando configuração para a API local"}</p></div> : null}
        <div className="mt-8 flex flex-col-reverse gap-3 border-t pt-5 sm:flex-row sm:justify-between"><Button variant="outline" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0 || running}><ChevronLeft className="size-4" />Voltar</Button>{step < 3 ? <Button onClick={() => setStep(step + 1)} disabled={running || (step === 0 && !status?.available)}>Continuar<ChevronRight className="size-4" /></Button> : <Button onClick={run} disabled={running || !status?.available}><Play className="size-4" />{running ? "Executando…" : "Executar com Norgate"}</Button>}</div>
      </CardContent>
    </Card>
  </div>;
}

type UniverseProps = {
  status: NorgateStatus | null; catalog: NorgateCatalog | null; loading: boolean; collectionType: CollectionType; collectionName: string; collections: string[]; availableCount: number; symbolsText: string; useEntireCollection: boolean; startDate: string; endDate: string; frequency: string; adjustment: string; restrictToIndex: boolean; indexName: string;
  onCollectionType: (value: CollectionType) => void; onCollectionName: (value: string) => void; onSymbolsText: (value: string) => void; onEntireCollection: (value: boolean) => void; onStartDate: (value: string) => void; onEndDate: (value: string) => void; onFrequency: (value: string) => void; onAdjustment: (value: string) => void; onRestrictToIndex: (value: boolean) => void; onIndexName: (value: string) => void;
};

function UniverseStep(props: UniverseProps) {
  return <div><h2 className="text-xl font-medium">Defina os dados Norgate</h2><p className="mt-2 text-sm text-muted-foreground">O frontend consulta diretamente a API Python local, que usa a mesma instalação do Norgate Data do aplicativo Streamlit.</p>
    <div className="mt-6 grid gap-5 md:grid-cols-2">
      <Field label="Tipo de coleção"><Select value={props.collectionType} onValueChange={(value) => props.onCollectionType(value as CollectionType)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="watchlist">Watchlist Norgate</SelectItem><SelectItem value="database">Database Norgate</SelectItem></SelectContent></Select></Field>
      <Field label="Coleção"><Select value={props.collectionName} onValueChange={props.onCollectionName} disabled={!props.catalog}><SelectTrigger><SelectValue placeholder="Selecione uma coleção" /></SelectTrigger><SelectContent>{props.collections.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select></Field>
      <Field label="Ativos" hint={`${props.availableCount.toLocaleString("pt-BR")} símbolos disponíveis na coleção. Separe tickers por vírgula.`}><Input value={props.symbolsText} onChange={(event) => props.onSymbolsText(event.target.value)} disabled={props.useEntireCollection || props.loading} placeholder="AAPL, MSFT, NVDA" /></Field>
      <Field label="Frequência"><Select value={props.frequency} onValueChange={props.onFrequency}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(props.catalog?.frequencies ?? ["Semanal", "Diário", "Mensal"]).map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></Field>
      <Field label="Data inicial"><Input type="date" value={props.startDate} onChange={(event) => props.onStartDate(event.target.value)} /></Field>
      <Field label="Data final"><Input type="date" value={props.endDate} onChange={(event) => props.onEndDate(event.target.value)} /></Field>
      <div className="md:col-span-2"><Field label="Ajuste de preços"><Select value={props.adjustment} onValueChange={props.onAdjustment}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{(props.catalog?.adjustments ?? ["Total Return (splits + dividendos)"]).map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent></Select></Field></div>
    </div>
    <div className="mt-6 space-y-3">
      <label className="flex items-center justify-between gap-4 rounded-xl border p-4"><span><strong className="block text-sm">Usar a coleção inteira</strong><span className="text-xs text-muted-foreground">Pode levar vários minutos em universos grandes.</span></span><Switch checked={props.useEntireCollection} onCheckedChange={props.onEntireCollection} /></label>
      <label className="flex items-center justify-between gap-4 rounded-xl border p-4"><span><strong className="block text-sm">Constituintes point-in-time</strong><span className="text-xs text-muted-foreground">Aplica a série histórica de pertencimento ao índice e reduz viés de sobrevivência.</span></span><Switch checked={props.restrictToIndex} onCheckedChange={props.onRestrictToIndex} /></label>
      {props.restrictToIndex ? <Field label="Nome do índice no Norgate"><Input value={props.indexName} onChange={(event) => props.onIndexName(event.target.value)} /></Field> : null}
    </div>
    <div className={`mt-6 flex items-start gap-3 rounded-xl border p-4 text-sm ${props.status?.available ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5"}`}><Database className={`mt-0.5 size-5 shrink-0 ${props.status?.available ? "text-success" : "text-warning"}`} /><div><strong>{props.loading ? "Consultando a API local…" : props.status?.available ? "Norgate conectado" : "Norgate indisponível"}</strong><p className="mt-1 text-muted-foreground">{props.status?.message ?? "Aguardando resposta de http://127.0.0.1:8000"}</p></div></div>
  </div>;
}

type StrategyStepProps = {
  mode: BacktestMode; rsiPeriod: number; rsiEntry: number; rsiExit: number; maxBars: number; hammer: HammerSettings; breadth: BreadthSettings; sma200Filters: Sma200Filters; management: PositionManagement;
  onRsiPeriod: (value: number) => void; onRsiEntry: (value: number) => void; onRsiExit: (value: number) => void; onMaxBars: (value: number) => void; onHammer: (changes: Partial<HammerSettings>) => void; onBreadth: (changes: Partial<BreadthSettings>) => void; onSma200Filters: (changes: Partial<Sma200Filters>) => void; onManagement: (changes: Partial<PositionManagement>) => void;
};

function ExitRule({ title, description, enabled, onEnabled, children }: { title: string; description: string; enabled: boolean; onEnabled: (value: boolean) => void; children?: React.ReactNode }) {
  return <div className={`rounded-xl border p-4 transition-colors ${enabled ? "border-primary/30 bg-primary/5" : "bg-muted/20"}`}><div className="flex items-start justify-between gap-4"><div><strong className="block text-sm">{title}</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">{description}</p></div><Switch checked={enabled} onCheckedChange={onEnabled} aria-label={`Ativar ${title}`} /></div>{children ? <div className={`mt-4 ${enabled ? "" : "opacity-50"}`}>{children}</div> : null}</div>;
}

function StrategyStep(props: StrategyStepProps) {
  const hammer = props.hammer;
  const management = props.management;
  return <div><h2 className="text-xl font-medium">Configure entrada e manejo da posição</h2><p className="mt-2 text-sm text-muted-foreground">Defina RSI, formato do Hammer e regras de saída. Quando várias saídas estão ativas, prevalece a primeira acionada.</p>
    <div className="mt-6 grid gap-5 md:grid-cols-2"><Field label="Período do RSI"><Input aria-label="Período do RSI" type="number" value={props.rsiPeriod} min="2" max="100" onChange={(event) => props.onRsiPeriod(Number(event.target.value))} /></Field><Field label="Entrada: RSI abaixo de"><Input aria-label="RSI máximo para entrada" type="number" value={props.rsiEntry} min="0" max="100" onChange={(event) => props.onRsiEntry(Number(event.target.value))} /></Field></div>
    <h3 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Filtro de tendência — MM200</h3>
    <div className="mt-3 grid gap-5 rounded-xl border p-4 md:grid-cols-2">
      <Field label="Preço em relação à MM200" hint="A comparação usa o fechamento do candle de sinal."><Select value={props.sma200Filters.price} onValueChange={(value) => props.onSma200Filters({ price: value as Sma200Filters["price"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="any">Qualquer posição</SelectItem><SelectItem value="above">Preço acima da MM200</SelectItem><SelectItem value="below">Preço abaixo da MM200</SelectItem></SelectContent></Select></Field>
      <Field label="Inclinação da MM200" hint="Compara a MM200 atual com a da barra anterior, sem olhar dados futuros."><Select value={props.sma200Filters.slope} onValueChange={(value) => props.onSma200Filters({ slope: value as Sma200Filters["slope"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="any">Qualquer inclinação</SelectItem><SelectItem value="rising">MM200 ascendente</SelectItem><SelectItem value="falling">MM200 descendente</SelectItem></SelectContent></Select></Field>
    </div>
    <h3 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Padrão Hammer</h3>
    <div className={`mt-3 rounded-xl border p-4 transition-colors ${hammer.use_hammer ? "border-primary/30 bg-primary/5" : "bg-muted/20"}`}>
      <div className="flex items-start justify-between gap-4"><div><strong className="block text-sm">Exigir candle Hammer</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">O open e o close devem estar na faixa superior definida pelo percentil do candle.</p></div><Switch checked={hammer.use_hammer} onCheckedChange={(value) => props.onHammer({ use_hammer: value })} aria-label="Exigir candle Hammer" /></div>
      <div className={`mt-4 grid gap-4 md:grid-cols-2 ${hammer.use_hammer ? "" : "opacity-50"}`}>
        <Field label="Percentil superior do corpo" hint="0,33 = open e close no terço superior. Menor é mais rigoroso; maior é mais permissivo."><Input aria-label="Percentil superior do Hammer" type="number" value={hammer.hammer_percentile} min="0.01" max="1" step="0.01" disabled={!hammer.use_hammer} onChange={(event) => props.onHammer({ hammer_percentile: Number(event.target.value) })} /></Field>
        <div className="flex items-center justify-between gap-4 rounded-lg border bg-background/60 p-4"><div><strong className="block text-sm">Exigir fechamento altista</strong><p className="mt-1 text-xs text-muted-foreground">Close deve ser maior ou igual ao open.</p></div><Switch checked={hammer.hammer_require_bullish_close} disabled={!hammer.use_hammer} onCheckedChange={(value) => props.onHammer({ hammer_require_bullish_close: value })} aria-label="Exigir fechamento altista no Hammer" /></div>
      </div>
      <div className={`mt-4 rounded-lg border bg-background/60 p-4 ${hammer.use_hammer ? "" : "opacity-50"}`}><div className="flex items-start justify-between gap-4"><div><strong className="block text-sm">Filtro de amplitude por ATR</strong><p className="mt-1 text-xs text-muted-foreground">Exige que a amplitude do Hammer seja maior que N × ATR.</p></div><Switch checked={hammer.hammer_use_atr_filter} disabled={!hammer.use_hammer} onCheckedChange={(value) => props.onHammer({ hammer_use_atr_filter: value })} aria-label="Ativar filtro ATR do Hammer" /></div><div className={`mt-4 grid gap-4 sm:grid-cols-2 ${hammer.hammer_use_atr_filter ? "" : "opacity-50"}`}><Field label="Período do ATR"><Input aria-label="Período do ATR do Hammer" type="number" value={hammer.hammer_atr_period} min="1" max="500" disabled={!hammer.use_hammer || !hammer.hammer_use_atr_filter} onChange={(event) => props.onHammer({ hammer_atr_period: Number(event.target.value) })} /></Field><Field label="Múltiplo mínimo do ATR"><Input aria-label="Múltiplo mínimo do ATR do Hammer" type="number" value={hammer.hammer_atr_multiple} min="0" max="100" step="0.05" disabled={!hammer.use_hammer || !hammer.hammer_use_atr_filter} onChange={(event) => props.onHammer({ hammer_atr_multiple: Number(event.target.value) })} /></Field></div></div>
      {!hammer.use_hammer ? <p className="mt-4 text-xs font-medium text-warning">Sem outro padrão habilitado, desligar o Hammer impede novas entradas.</p> : null}
    </div>
    {props.mode === "portfolio" ? <><h3 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Regime de mercado</h3>
    <div className={`mt-3 rounded-xl border p-4 transition-colors ${props.breadth.enabled ? "border-primary/30 bg-primary/5" : "bg-muted/20"}`}>
      <div className="flex items-start justify-between gap-4"><div><strong className="block text-sm">Filtro de breadth</strong><p className="mt-1 text-xs leading-5 text-muted-foreground">Só abre novas posições quando a parcela de constituintes acima da própria média alcança o limite.</p></div><Switch checked={props.breadth.enabled} onCheckedChange={(value) => props.onBreadth({ enabled: value })} aria-label="Ativar filtro de breadth" /></div>
      <div className={`mt-4 grid gap-4 sm:grid-cols-2 ${props.breadth.enabled ? "" : "opacity-50"}`}><Field label="Período da média (barras)"><Input aria-label="Período da média do breadth" type="number" value={props.breadth.smaPeriod} min="2" max="500" disabled={!props.breadth.enabled} onChange={(event) => props.onBreadth({ smaPeriod: Number(event.target.value) })} /></Field><Field label="Breadth mínimo (%)" hint="Configuração inicial: 50% acima da MM40."><Input aria-label="Breadth mínimo percentual" type="number" value={props.breadth.thresholdPct} min="0" max="100" step="1" disabled={!props.breadth.enabled} onChange={(event) => props.onBreadth({ thresholdPct: Number(event.target.value) })} /></Field></div>
    </div></> : null}
    <h3 className="mt-8 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Regras de saída</h3>
    <div className="mt-3 grid gap-4 md:grid-cols-2">
      <ExitRule title="Recuperação do RSI" description="Sai quando o RSI fecha acima do limite configurado." enabled={management.use_rsi_exit} onEnabled={(value) => props.onManagement({ use_rsi_exit: value })}><Field label="RSI de saída"><Input aria-label="RSI de saída" type="number" value={props.rsiExit} min="0" max="100" disabled={!management.use_rsi_exit} onChange={(event) => props.onRsiExit(Number(event.target.value))} /></Field></ExitRule>
      <ExitRule title="Tempo máximo" description="Encerra a posição depois de N barras, mesmo sem recuperação." enabled={management.use_max_bars} onEnabled={(value) => props.onManagement({ use_max_bars: value })}><Field label="Máximo de barras"><Input aria-label="Máximo de barras na posição" type="number" value={props.maxBars} min="1" max="500" disabled={!management.use_max_bars} onChange={(event) => props.onMaxBars(Number(event.target.value))} /></Field></ExitRule>
      <ExitRule title="Alvo de lucro" description="Realiza o ganho quando o fechamento alcança o percentual sobre o preço de entrada." enabled={management.use_profit_target} onEnabled={(value) => props.onManagement({ use_profit_target: value })}><Field label="Alvo (%)"><Input aria-label="Alvo de lucro percentual" type="number" value={management.profit_target_pct} min="0.01" max="1000" step="0.25" disabled={!management.use_profit_target} onChange={(event) => props.onManagement({ profit_target_pct: Number(event.target.value) })} /></Field></ExitRule>
      <ExitRule title="Stop loss percentual" description="Protege a posição quando o fechamento cai o percentual definido desde a entrada." enabled={management.use_stop_loss} onEnabled={(value) => props.onManagement({ use_stop_loss: value })}><Field label="Stop (%)"><Input aria-label="Stop loss percentual" type="number" value={management.stop_loss_pct} min="0.01" max="100" step="0.25" disabled={!management.use_stop_loss} onChange={(event) => props.onManagement({ stop_loss_pct: Number(event.target.value) })} /></Field></ExitRule>
      <ExitRule title="Stop na mínima do sinal" description="Stop intrabar na mínima do candle Hammer; gaps saem na abertura da barra." enabled={management.use_signal_low_stop} onEnabled={(value) => props.onManagement({ use_signal_low_stop: value })} />
      <ExitRule title="Fechamento acima da SMA" description="Sai quando o fechamento supera uma média curta de recuperação." enabled={management.use_sma_exit} onEnabled={(value) => props.onManagement({ use_sma_exit: value })}><Field label="Período da SMA"><Input aria-label="Período da SMA de saída" type="number" value={management.sma_period} min="1" max="500" disabled={!management.use_sma_exit} onChange={(event) => props.onManagement({ sma_period: Number(event.target.value) })} /></Field></ExitRule>
      <div className="md:col-span-2"><ExitRule title="RSI acumulado" description="Sai quando a soma do RSI dos últimos N períodos supera o limite." enabled={management.use_rsi_cum_exit} onEnabled={(value) => props.onManagement({ use_rsi_cum_exit: value })}><div className="grid gap-4 sm:grid-cols-2"><Field label="Períodos"><Input aria-label="Períodos do RSI acumulado" type="number" value={management.rsi_cum_periods} min="1" max="50" disabled={!management.use_rsi_cum_exit} onChange={(event) => props.onManagement({ rsi_cum_periods: Number(event.target.value) })} /></Field><Field label="Limite acumulado"><Input aria-label="Limite do RSI acumulado" type="number" value={management.rsi_cum_threshold} min="0" max="1000" step="5" disabled={!management.use_rsi_cum_exit} onChange={(event) => props.onManagement({ rsi_cum_threshold: Number(event.target.value) })} /></Field></div></ExitRule></div>
    </div>
    <div className="mt-6 flex items-start gap-3 rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm"><ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" /><p>O stop na mínima do sinal é intrabar. As demais regras são confirmadas no fechamento e executadas na próxima abertura, preservando a simulação sem look-ahead.</p></div>
  </div>;
}

type OptionsPanelProps = {
  instrument: InstrumentType;
  options: OptionSettings;
  onInstrument: (value: InstrumentType) => void;
  onOptions: (changes: Partial<OptionSettings>) => void;
};

function OptionsPanel(props: OptionsPanelProps) {
  const synthetic = props.instrument === "synthetic_atm_call";
  return <div>
    <h2 className="text-xl font-medium">Escolha o instrumento</h2>
    <p className="mt-2 text-sm text-muted-foreground">O backtest permanece integralmente na ação e na frequência escolhida. A call é calculada em paralelo para cada trade.</p>
    <div className="mt-5 max-w-md"><Field label="Instrumento"><Select value={props.instrument} onValueChange={(value) => props.onInstrument(value as InstrumentType)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="stock">Somente ação</SelectItem><SelectItem value="synthetic_atm_call">Ação + Call sintética (ATM/OTM)</SelectItem></SelectContent></Select></Field></div>
    {synthetic ? <div className="mt-6 rounded-xl border border-primary/30 bg-primary/5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-medium">Contrato ATM e mark-to-model</h3><p className="mt-1 text-xs text-muted-foreground">Sinais e saídas usam a frequência selecionada; dados diários Capital entram apenas na precificação da call.</p></div><Badge>Comparação paralela</Badge></div>
      <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        <Field label="Modelo"><Select value={props.options.pricing_model} onValueChange={(value) => props.onOptions({ pricing_model: value as OptionSettings["pricing_model"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="black_scholes">Black-Scholes-Merton</SelectItem><SelectItem value="binomial">Árvore binomial CRR</SelectItem></SelectContent></Select></Field>
        <Field label="Strike"><Select value={props.options.strike_mode} onValueChange={(value) => props.onOptions({ strike_mode: value as OptionSettings["strike_mode"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="exact_atm">ATM exato (K = S)</SelectItem><SelectItem value="rounded">ATM na grade sintética</SelectItem><SelectItem value="otm_pct">Call OTM por percentual</SelectItem></SelectContent></Select></Field>
        <Field label="Intervalo da grade"><Input type="number" min="0.01" step="0.5" value={props.options.strike_interval} disabled={props.options.strike_mode === "exact_atm"} onChange={(event) => props.onOptions({ strike_interval: Number(event.target.value) })} /></Field>
        <Field label="Distância OTM (%)"><Input type="number" min="0.1" max="1000" step="0.5" value={props.options.otm_pct} disabled={props.options.strike_mode !== "otm_pct"} onChange={(event) => props.onOptions({ otm_pct: Number(event.target.value) })} /></Field>
        <Field label="DTE-alvo"><Input type="number" min="7" max="730" value={props.options.target_dte} onChange={(event) => props.onOptions({ target_dte: Number(event.target.value) })} /></Field>
        <Field label="Janela da volatilidade"><Input type="number" min="2" max="252" value={props.options.volatility_window} onChange={(event) => props.onOptions({ volatility_window: Number(event.target.value) })} /></Field>
        <Field label="Multiplicador RV → IV"><Input type="number" min="0.01" max="10" step="0.05" value={props.options.iv_multiplier} onChange={(event) => props.onOptions({ iv_multiplier: Number(event.target.value) })} /></Field>
        <Field label="Piso de IV"><Input type="number" min="0.01" max="10" step="0.01" value={props.options.iv_floor} onChange={(event) => props.onOptions({ iv_floor: Number(event.target.value) })} /></Field>
        <Field label="Teto de IV"><Input type="number" min="0.01" max="10" step="0.1" value={props.options.iv_cap} onChange={(event) => props.onOptions({ iv_cap: Number(event.target.value) })} /></Field>
        <Field label="Fonte da taxa"><Select value={props.options.risk_free_mode} onValueChange={(value) => props.onOptions({ risk_free_mode: value as OptionSettings["risk_free_mode"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="norgate">Norgate histórica</SelectItem><SelectItem value="fixed">Taxa fixa</SelectItem></SelectContent></Select></Field>
        <Field label="Símbolo da taxa Norgate"><Input value={props.options.risk_free_symbol} disabled={props.options.risk_free_mode !== "norgate"} onChange={(event) => props.onOptions({ risk_free_symbol: event.target.value })} /></Field>
        <Field label="Taxa livre de risco (%)"><Input type="number" min="-10" max="100" step="0.25" value={props.options.risk_free_rate * 100} onChange={(event) => props.onOptions({ risk_free_rate: Number(event.target.value) / 100 })} /></Field>
        <Field label="Spread bid/ask total (%)"><Input type="number" min="0" max="200" step="0.5" value={props.options.spread_pct * 100} onChange={(event) => props.onOptions({ spread_pct: Number(event.target.value) / 100 })} /></Field>
        <Field label="Comissão por contrato/ponta"><Input type="number" min="0" step="0.05" value={props.options.commission_per_contract} onChange={(event) => props.onOptions({ commission_per_contract: Number(event.target.value) })} /></Field>
        <Field label="Dimensionamento"><Select value={props.options.sizing_mode} onValueChange={(value) => props.onOptions({ sizing_mode: value as OptionSettings["sizing_mode"] })}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="premium_risk">Orçamento em prêmio</SelectItem><SelectItem value="delta_equivalent">Delta equivalente</SelectItem></SelectContent></Select></Field>
        <Field label="Orçamento por operação (%)"><Input type="number" min="0.1" max="100" step="0.5" value={props.options.premium_risk_pct} onChange={(event) => props.onOptions({ premium_risk_pct: Number(event.target.value) })} /></Field>
      </div>
    </div> : null}
  </div>;
}

function OptionReview({ options }: { options: OptionSettings }) {
  return <div className="rounded-xl border border-primary/30 bg-primary/5 p-5 text-sm">
    <div className="flex items-center gap-2"><Badge>Ação + Call sintética</Badge><strong>{options.pricing_model === "black_scholes" ? "Black-Scholes-Merton" : "Árvore binomial CRR"}</strong></div>
    <p className="mt-3 text-muted-foreground">{options.strike_mode === "otm_pct" ? `Strike aproximadamente ${number(options.otm_pct)}% OTM` : options.strike_mode === "rounded" ? "Strike ATM na grade sintética" : "Strike ATM exato"} · {options.target_dte} DTE · sem rolagem, encerra no vencimento · IV = {options.iv_multiplier}× RV{options.volatility_window} · orçamento {options.premium_risk_pct}% · spread {number(options.spread_pct * 100)}%.</p>
    <p className="mt-2 text-xs text-warning">Resultado mark-to-model: não representa uma cadeia histórica executável.</p>
  </div>;
}

type CostsProps = { initialCapital: number; maxPositions: number; pctPerTrade: number; commissionFixed: number; commissionPct: number; slippagePct: number; mode: BacktestMode; onInitialCapital: (value: number) => void; onMaxPositions: (value: number) => void; onPctPerTrade: (value: number) => void; onCommissionFixed: (value: number) => void; onCommissionPct: (value: number) => void; onSlippagePct: (value: number) => void };
function CostsStep(props: CostsProps) {
  return <div><h2 className="text-xl font-medium">Modele capital, custos e risco</h2><p className="mt-2 text-sm text-muted-foreground">Percentuais da tela são convertidos para as unidades exatas esperadas pelo motor Python.</p><div className="mt-6 grid gap-5 md:grid-cols-2"><Field label="Capital inicial"><Input type="number" value={props.initialCapital} min="1" onChange={(event) => props.onInitialCapital(Number(event.target.value))} /></Field>{props.mode === "portfolio" ? <><Field label="Máximo de posições (0 = sem limite)"><Input type="number" value={props.maxPositions} min="0" onChange={(event) => props.onMaxPositions(Number(event.target.value))} /></Field><Field label="Alocação por posição (%)"><Input type="number" value={props.pctPerTrade} min="0.01" max="100" step="0.1" onChange={(event) => props.onPctPerTrade(Number(event.target.value))} /></Field></> : null}<Field label="Corretagem fixa por ordem"><Input type="number" value={props.commissionFixed} min="0" step="0.01" onChange={(event) => props.onCommissionFixed(Number(event.target.value))} /></Field><Field label="Custo variável por ordem (%)"><Input type="number" value={props.commissionPct} min="0" max="100" step="0.01" onChange={(event) => props.onCommissionPct(Number(event.target.value))} /></Field><Field label="Slippage por ordem (%)"><Input type="number" value={props.slippagePct} min="0" max="100" step="0.01" onChange={(event) => props.onSlippagePct(Number(event.target.value))} /></Field></div></div>;
}

type ReviewProps = { mode: BacktestMode; collectionName: string; symbolCount: number; startDate: string; endDate: string; frequency: string; adjustment: string; rsiPeriod: number; rsiEntry: number; rsiExit: number; maxBars: number; hammer: HammerSettings; breadth: BreadthSettings; sma200Filters: Sma200Filters; management: PositionManagement; initialCapital: number; maxPositions: number; pctPerTrade: number; restrictToIndex: boolean };
function ReviewStep(props: ReviewProps) {
  const exits = [
    props.management.use_rsi_cum_exit ? `RSI(${props.management.rsi_cum_periods}) acumulado > ${props.management.rsi_cum_threshold}` : null,
    props.management.use_rsi_exit ? `RSI > ${props.rsiExit}` : null,
    props.management.use_max_bars ? `${props.maxBars} barras` : null,
    props.management.use_profit_target ? `alvo +${props.management.profit_target_pct}%` : null,
    props.management.use_stop_loss ? `stop −${props.management.stop_loss_pct}%` : null,
    props.management.use_signal_low_stop ? "stop na mínima do sinal" : null,
    props.management.use_sma_exit ? `fechamento > SMA(${props.management.sma_period})` : null,
  ].filter(Boolean).join(" · ") || "Somente fechamento obrigatório na última barra";
  const hammer = props.hammer.use_hammer
    ? `Percentil ${props.hammer.hammer_percentile} · ${props.hammer.hammer_require_bullish_close ? "fechamento altista" : "qualquer cor"} · ${props.hammer.hammer_use_atr_filter ? `amplitude > ${props.hammer.hammer_atr_multiple}× ATR(${props.hammer.hammer_atr_period})` : "sem filtro ATR"}`
    : "Desativado — nenhuma entrada será gerada";
  const sma200 = [
    props.sma200Filters.price === "above" ? "preço acima" : props.sma200Filters.price === "below" ? "preço abaixo" : null,
    props.sma200Filters.slope === "rising" ? "média ascendente" : props.sma200Filters.slope === "falling" ? "média descendente" : null,
  ].filter(Boolean).join(" · ") || "Desativado";
  const rows = [
    ["Fonte", `Norgate local · ${props.collectionName}`],
    ["Universo", `${props.symbolCount.toLocaleString("pt-BR")} ativo(s) · ${props.frequency}`],
    ["Período", `${props.startDate} a ${props.endDate}`],
    ["Ajuste", props.adjustment],
    ["Entrada", `RSI(${props.rsiPeriod}) < ${props.rsiEntry}`],
    ["MM200", sma200],
    ["Hammer", hammer],
    ["Filtro de mercado", props.mode === "portfolio" && props.breadth.enabled ? `Breadth ≥ ${props.breadth.thresholdPct}% acima da MM${props.breadth.smaPeriod}` : "Desativado"],
    ["Manejo e saídas", exits],
    ["Capital", `${props.initialCapital.toLocaleString("pt-BR")} · ${props.mode === "portfolio" ? `${props.pctPerTrade}% por posição · máx. ${props.maxPositions || "∞"}` : "100% por ativo"}`],
    ["Constituintes históricos", props.restrictToIndex ? "Ativado" : "Desativado"],
  ];
  return <div><div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><h2 className="text-xl font-medium">Revise antes de executar</h2><p className="mt-2 text-sm text-muted-foreground">A execução ocorrerá neste computador e os preços não serão enviados ao site publicado.</p></div><Badge variant="secondary">{props.mode === "portfolio" ? "Carteira" : "Por ativo"}</Badge></div><div className="mt-6 grid gap-4 md:grid-cols-2">{rows.map(([label, value]) => <div key={label} className="rounded-xl border bg-muted/25 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-sm font-medium">{value}</p></div>)}</div><div className="mt-5 flex gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm"><CircleAlert className="size-5 shrink-0 text-warning" /><p><strong>Risco de pesquisa:</strong> resultados históricos não garantem desempenho futuro. Valide liquidez, custos e robustez fora da amostra.</p></div></div>;
}

function percent(value = 0) { return new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value); }
function number(value = 0, digits = 2) { return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value); }
function dateLabel(value: unknown) { const parsed = new Date(String(value)); return Number.isNaN(parsed.getTime()) ? String(value ?? "—") : parsed.toLocaleDateString("pt-BR"); }

function downloadTrades(run: RunSummary) {
  if (!run.trades.length) return;
  const headers = Object.keys(run.trades[0]);
  const escape = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [headers.map(escape).join(","), ...run.trades.map((row) => headers.map((key) => escape(row[key])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = `${run.id}-trades.csv`; anchor.click(); URL.revokeObjectURL(url);
}

function ScenarioSummary({ run }: { run: RunSummary }) {
  const scenarios = [
    ["low", "IV baixa (0,85×)"],
    ["base", "IV base"],
    ["high", "IV alta (1,15×)"],
  ] as const;
  return <Card className="mb-6 shadow-none"><CardHeader><h3 className="font-medium">Resultado paralelo das calls sintéticas</h3><p className="text-xs text-muted-foreground">A curva principal e as métricas abaixo continuam sendo das ações. Estes cenários reaplicam exatamente os mesmos trades às calls.</p></CardHeader><CardContent><div className="mb-5 grid gap-3 sm:grid-cols-3">{scenarios.map(([key, label]) => <div key={key} className="rounded-lg border bg-muted/20 p-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-lg font-medium">{percent(run.scenario_metrics[key]?.total_return ?? 0)}</p><p className="text-xs text-muted-foreground">Capital equivalente {number(run.scenario_metrics[key]?.final_equity ?? 0)}</p></div>)}</div><Tabs defaultValue="base"><TabsList>{scenarios.map(([key, label]) => <TabsTrigger key={key} value={key}>{label}</TabsTrigger>)}</TabsList>{scenarios.map(([key]) => <TabsContent key={key} value={key} className="mt-5"><EquityChart points={run.scenario_equity[key] ?? run.equity} /></TabsContent>)}</Tabs></CardContent></Card>;
}

function OptionResults({ run }: { run: RunSummary }) {
  return <Card className="mb-6 border-primary/30 bg-primary/5 shadow-none"><CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><h3 className="font-medium">Equivalência por trade em Call sintética</h3><p className="mt-1 text-xs text-muted-foreground">Uma call por trade, sem rolagem. Ela sai com a ação ou encerra no vencimento pelo intrínseco.</p></div><Badge>Mark-to-model</Badge></div></CardHeader><CardContent className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Ativo</TableHead><TableHead>Entrada/saída da call</TableHead><TableHead>Motivo da saída</TableHead><TableHead>Strike</TableHead><TableHead>DTE</TableHead><TableHead>Contratos</TableHead><TableHead>IV entrada/saída</TableHead><TableHead>Delta</TableHead><TableHead>Prêmio entrada/saída</TableHead><TableHead className="text-right">Retorno call</TableHead><TableHead className="text-right">P&amp;L call</TableHead></TableRow></TableHeader><TableBody>{run.trades.slice(0, 20).map((trade, index) => <TableRow key={`option-${trade.ticker}-${trade.entry_date}-${index}`}><TableCell className="font-medium">{String(trade.ticker ?? "—")}</TableCell><TableCell>{dateLabel(trade.option_entry_date)} → {dateLabel(trade.option_exit_date)}</TableCell><TableCell>{String(trade.option_exit_reason ?? "—")}</TableCell><TableCell>{number(Number(trade.option_strike ?? 0))}</TableCell><TableCell>{String(trade.option_dte_entry ?? "—")} → {String(trade.option_dte_exit ?? "—")}</TableCell><TableCell>{String(trade.option_contracts ?? "—")}</TableCell><TableCell>{percent(Number(trade.option_iv_entry ?? 0))} / {percent(Number(trade.option_iv_exit ?? 0))}</TableCell><TableCell>{number(Number(trade.option_delta_entry ?? 0), 3)}</TableCell><TableCell>{number(Number(trade.option_entry_price ?? 0))} / {number(Number(trade.option_exit_price ?? 0))}</TableCell><TableCell className="text-right">{percent(Number(trade.option_net_return ?? 0))}</TableCell><TableCell className={`text-right ${Number(trade.option_pnl ?? 0) >= 0 ? "text-success" : "text-destructive"}`}>{number(Number(trade.option_pnl ?? 0))}</TableCell></TableRow>)}</TableBody></Table>{run.trades.length > 20 ? <p className="mt-3 text-xs text-muted-foreground">Exibindo 20 de {run.trades.length} operações; exporte o CSV para todos os gregos e campos.</p> : null}</CardContent></Card>;
}

function BacktestResult({ run, onNew }: { run: RunSummary; onNew: () => void }) {
  const metrics = run.metrics;
  const symbols = Array.isArray(run.data_summary.symbols) ? run.data_summary.symbols : [];
  const synthetic = run.data_summary.instrument === "synthetic_atm_call";
  const breadthEnabled = run.data_summary.breadth_filter === true;
  return <div>{synthetic ? <><ScenarioSummary run={run} /><OptionResults run={run} /></> : null}<div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between"><div><div className="flex flex-wrap items-center gap-2"><Badge className="bg-success text-white">Concluído</Badge><Badge variant="outline"><Database className="mr-1 size-3" />Norgate local</Badge>{breadthEnabled ? <Badge variant="outline">Breadth {String(run.data_summary.breadth_threshold_pct)}% · MM{String(run.data_summary.breadth_sma_period)}</Badge> : null}{synthetic ? <Badge variant="outline">Ação + Call sintética</Badge> : null}<span className="font-mono text-xs text-muted-foreground">{run.id}</span></div><h2 className="mt-3 text-2xl font-medium">{run.name}</h2><p className="mt-2 text-sm text-muted-foreground">{run.data_summary.start_date}–{run.data_summary.end_date} · {Number(run.data_summary.assets_loaded ?? 0).toLocaleString("pt-BR")} ativos · {run.trade_count.toLocaleString("pt-BR")} operações</p></div><div className="flex gap-2"><Button variant="outline" disabled={!run.trades.length} onClick={() => downloadTrades(run)}><Download className="size-4" />Exportar trades</Button><Button onClick={onNew}><RefreshCw className="size-4" />Novo backtest</Button></div></div>
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Retorno total" value={percent(metrics.total_return)} tone={metrics.total_return >= 0 ? "positive" : "negative"} /><MetricCard label="CAGR" value={percent(metrics.cagr)} tone={metrics.cagr >= 0 ? "positive" : "negative"} /><MetricCard label="Sharpe" value={number(metrics.sharpe)} tone={metrics.sharpe >= 1 ? "positive" : "neutral"} /><MetricCard label="Drawdown máximo" value={percent(metrics.max_drawdown)} tone="negative" /><MetricCard label="Patrimônio final" value={number(metrics.final_equity)} /><MetricCard label="Taxa de acerto" value={percent(metrics.win_rate)} /><MetricCard label="Profit factor" value={number(metrics.profit_factor)} /><MetricCard label="Exposição" value={percent(metrics.exposure)} /></section>
    {run.warnings.length ? <div className="mt-6 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm"><strong>Avisos da execução ({run.warnings.length})</strong><ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">{run.warnings.slice(0, 8).map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul>{run.warnings.length > 8 ? <p className="mt-2 text-xs text-muted-foreground">Mais {run.warnings.length - 8} avisos não exibidos.</p> : null}</div> : null}
    <Card className="mt-6 shadow-none"><CardContent className="p-5 md:p-6"><Tabs defaultValue="summary"><TabsList className="w-full justify-start overflow-x-auto"><TabsTrigger value="summary">Curva de patrimônio</TabsTrigger><TabsTrigger value="trades">Operações</TabsTrigger><TabsTrigger value="data">Dados usados</TabsTrigger><TabsTrigger value="method">Metodologia</TabsTrigger></TabsList><TabsContent value="summary" className="mt-6"><EquityChart points={run.equity} /></TabsContent><TabsContent value="trades" className="mt-6 overflow-x-auto">{run.trades.length ? <Table><TableHeader><TableRow><TableHead>Ativo</TableHead><TableHead>Entrada</TableHead><TableHead>Saída</TableHead><TableHead>Barras</TableHead><TableHead className="text-right">P&amp;L ação</TableHead><TableHead className="text-right">Retorno ação</TableHead>{synthetic ? <><TableHead className="text-right">Prêmio call E/S</TableHead><TableHead className="text-right">Retorno call</TableHead><TableHead className="text-right">P&amp;L call</TableHead></> : null}<TableHead>Motivo</TableHead></TableRow></TableHeader><TableBody>{run.trades.map((trade, index) => { const pnl = Number(trade.pnl ?? 0); const optionPnl = Number(trade.option_pnl ?? 0); return <TableRow key={`${trade.ticker}-${trade.entry_date}-${index}`}><TableCell className="font-medium">{String(trade.ticker ?? "—")}</TableCell><TableCell>{dateLabel(trade.entry_date)}</TableCell><TableCell>{dateLabel(trade.exit_date)}</TableCell><TableCell>{String(trade.bars_held ?? "—")}</TableCell><TableCell className={`text-right ${pnl >= 0 ? "text-success" : "text-destructive"}`}>{number(pnl)}</TableCell><TableCell className="text-right">{percent(Number(trade.net_return ?? 0))}</TableCell>{synthetic ? <><TableCell className="text-right">{number(Number(trade.option_entry_price ?? 0))} / {number(Number(trade.option_exit_price ?? 0))}</TableCell><TableCell className="text-right">{percent(Number(trade.option_net_return ?? 0))}</TableCell><TableCell className={`text-right ${optionPnl >= 0 ? "text-success" : "text-destructive"}`}>{number(optionPnl)}</TableCell></> : null}<TableCell>{String(trade.exit_reason ?? "—")}</TableCell></TableRow>; })}</TableBody></Table> : <p className="rounded-xl border p-5 text-sm text-muted-foreground">Nenhuma operação foi gerada por essa configuração.</p>}</TabsContent><TabsContent value="data" className="mt-6 space-y-4 text-sm"><div className="grid gap-4 md:grid-cols-2"><div className="rounded-xl border p-4"><p className="text-xs text-muted-foreground">Coleção</p><p className="mt-1 font-medium">{String(run.data_summary.collection_name ?? "—")}</p></div><div className="rounded-xl border p-4"><p className="text-xs text-muted-foreground">Frequência e ajuste dos sinais</p><p className="mt-1 font-medium">{String(run.data_summary.frequency ?? "—")} · {String(run.data_summary.adjustment ?? "—")}</p>{synthetic ? <p className="mt-2 text-xs text-muted-foreground">Calls: Diário · Capital (apenas splits), somente para precificação.</p> : null}</div></div><div><p className="mb-2 text-xs text-muted-foreground">Símbolos carregados</p><div className="flex flex-wrap gap-2">{symbols.map((symbol) => <Badge key={symbol} variant="secondary">{symbol}</Badge>)}</div></div></TabsContent><TabsContent value="method" className="mt-6 space-y-3 text-sm leading-6 text-muted-foreground"><p>Preços e constituintes são lidos pela biblioteca Norgate instalada neste computador. A API apenas adapta os dados para o mesmo motor Python usado pelo projeto.</p><p>Entradas são confirmadas no fechamento e executadas na abertura seguinte. Custos e slippage configurados são debitados em cada ordem.</p>{breadthEnabled ? <p>O breadth é calculado no fechamento com a composição histórica do índice. Novas entradas exigem pelo menos {String(run.data_summary.breadth_threshold_pct)}% dos membros elegíveis acima da própria MM{String(run.data_summary.breadth_sma_period)}; posições abertas não são encerradas pelo filtro.</p> : null}{synthetic ? <p>A frequência escolhida gera os trades da ação; uma série diária auxiliar precifica a call ATM sem criar ou remover sinais.</p> : null}</TabsContent></Tabs></CardContent></Card>
  </div>;
}
