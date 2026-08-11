"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Database, FlaskConical, Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getNorgateCatalog, getNorgateSymbols, runNorgateOptimization, type OptimizationResponse } from "@/lib/api";

function range(min: number, max: number, step: number) {
  if (step <= 0 || max < min) return [min];
  return Array.from({ length: Math.floor((max - min) / step) + 1 }, (_, index) => Number((min + index * step).toFixed(6)));
}
function parseSymbols(value: string) { return [...new Set(value.split(/[\s,;]+/).map((symbol) => symbol.toUpperCase()).filter(Boolean))]; }
function metric(row: Record<string, string | number | boolean | null>, key: string) { return Number(row[key] ?? 0); }

export function OptimizerLab() {
  const [collections, setCollections] = useState<string[]>([]);
  const [collectionName, setCollectionName] = useState("");
  const [symbolsText, setSymbolsText] = useState("");
  const [validation, setValidation] = useState<"split" | "walk_forward">("walk_forward");
  const [entryMin, setEntryMin] = useState(5); const [entryMax, setEntryMax] = useState(15); const [entryStep, setEntryStep] = useState(5);
  const [exitMin, setExitMin] = useState(65); const [exitMax, setExitMax] = useState(75); const [exitStep, setExitStep] = useState(5);
  const [barsMin, setBarsMin] = useState(5); const [barsMax, setBarsMax] = useState(9); const [barsStep, setBarsStep] = useState(2);
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<OptimizationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const combinations = range(entryMin, entryMax, entryStep).length * range(exitMin, exitMax, exitStep).length * range(barsMin, barsMax, barsStep).length;

  useEffect(() => {
    let active = true;
    getNorgateCatalog().then((catalog) => {
      if (!active) return;
      setCollections(catalog.watchlists);
      setCollectionName(catalog.watchlists.find((name) => name.includes("S&P 500 Current & Past")) ?? catalog.watchlists[0] ?? "");
    }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "API local indisponível."); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!collectionName) return;
    let active = true;
    getNorgateSymbols("watchlist", collectionName).then(({ symbols }) => {
      if (!active) return;
      const preferred = ["AAPL", "MSFT", "NVDA"].filter((symbol) => symbols.includes(symbol));
      setSymbolsText((preferred.length ? preferred : symbols.slice(0, 3)).join(", "));
    }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Falha ao carregar símbolos."); });
    return () => { active = false; };
  }, [collectionName]);

  async function run() {
    setRunning(true); setError(null); setResponse(null);
    try {
      setResponse(await runNorgateOptimization({
        name: "Otimização Norgate RSI2", mode: "per_asset", collection_type: "watchlist", collection_name: collectionName,
        symbols: parseSymbols(symbolsText), use_entire_collection: false, start_date: "2015-01-01", end_date: "2026-08-10",
        frequency: "Semanal", adjustment: "Total Return (splits + dividendos)", restrict_to_index: false,
        strategy: { rsi_period: 2, rsi_entry: 10, use_hammer: true, hammer_percentile: 0.33, hammer_require_bullish_close: false, hammer_use_atr_filter: true, hammer_atr_period: 14, hammer_atr_multiple: 1, use_rsi_exit: true, rsi_exit: 70, use_max_bars: true, max_bars: 7, use_profit_target: false, profit_target_pct: 5, use_stop_loss: false, stop_loss_pct: 3, use_sma_exit: false, sma_period: 5, use_signal_low_stop: false, use_rsi_cum_exit: false, rsi_cum_periods: 2, rsi_cum_threshold: 100, initial_capital: 100000, commission_fixed: 0, commission_pct: 0.0003, slippage_bps: 10 },
        max_positions: 1, pct_per_trade: 100,
        parameter_ranges: { rsi_entry_threshold: range(entryMin, entryMax, entryStep), rsi_exit_threshold: range(exitMin, exitMax, exitStep), max_bars: range(barsMin, barsMax, barsStep) },
        validation, objective: "sharpe", splits: 3, min_trades: 3,
      }));
    } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "Otimização não concluída."); }
    finally { setRunning(false); }
  }

  const ranking = useMemo(() => [...(response?.results ?? [])].sort((a, b) => metric(b, "test_sharpe") - metric(a, "test_sharpe")), [response]);
  const best = ranking[0];
  const degradation = best && metric(best, "train_sharpe") ? metric(best, "test_sharpe") / metric(best, "train_sharpe") - 1 : 0;
  const ranges = [
    { name: "Entrada RSI", values: [entryMin, entryMax, entryStep], setters: [setEntryMin, setEntryMax, setEntryStep] },
    { name: "Saída RSI", values: [exitMin, exitMax, exitStep], setters: [setExitMin, setExitMax, setExitStep] },
    { name: "Máximo de barras", values: [barsMin, barsMax, barsStep], setters: [setBarsMin, setBarsMax, setBarsStep] },
  ];
  return <div className="grid gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
    <Card className="h-fit shadow-none"><CardHeader><CardTitle>Espaço de busca Norgate</CardTitle><CardDescription>{combinations} combinações em dados locais.</CardDescription></CardHeader><CardContent className="space-y-6"><div><Label>Watchlist</Label><Select value={collectionName} onValueChange={setCollectionName}><SelectTrigger className="mt-2"><SelectValue placeholder="Selecione" /></SelectTrigger><SelectContent>{collections.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select></div><div><Label>Ativos</Label><Input className="mt-2" value={symbolsText} onChange={(event) => setSymbolsText(event.target.value)} /><p className="mt-1 text-xs text-muted-foreground">Use poucos ativos para iteração rápida; separe por vírgula.</p></div>
      {ranges.map((parameter) => <fieldset key={parameter.name} className="rounded-xl border p-4"><legend className="px-1 text-sm font-medium">{parameter.name}</legend><div className="mt-2 grid grid-cols-3 gap-2">{["Mín.", "Máx.", "Passo"].map((label, index) => <div key={label}><Label className="text-[11px] text-muted-foreground">{label}</Label><Input type="number" value={parameter.values[index]} onChange={(event) => parameter.setters[index](Number(event.target.value))} /></div>)}</div></fieldset>)}
      <div><Label className="mb-3 block">Validação</Label><RadioGroup value={validation} onValueChange={(value) => setValidation(value as "split" | "walk_forward")} className="space-y-2"><label className="flex min-h-14 cursor-pointer gap-3 rounded-xl border p-3"><RadioGroupItem value="walk_forward" className="mt-0.5" /><span><strong className="block text-sm">Walk-forward</strong><span className="text-xs text-muted-foreground">Janela crescente · 3 folds</span></span></label><label className="flex min-h-14 cursor-pointer gap-3 rounded-xl border p-3"><RadioGroupItem value="split" className="mt-0.5" /><span><strong className="block text-sm">IS/OOS fixo</strong><span className="text-xs text-muted-foreground">70% treino · 30% teste</span></span></label></RadioGroup></div>
      <Button className="w-full" onClick={() => void run()} disabled={running || !collectionName || combinations > 1000}><Play className="size-4" />{running ? "Validando com Norgate…" : `Executar ${combinations} combinações`}</Button>{error ? <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm" role="alert">{error}</div> : null}
    </CardContent></Card>
    <div className="space-y-6">{running ? <Card className="shadow-none"><CardContent className="grid min-h-96 place-items-center text-center"><div><FlaskConical className="mx-auto size-8 animate-pulse text-primary" /><p className="mt-4 font-medium">Executando validação sem vazamento…</p><p className="mt-2 text-sm text-muted-foreground">Preços carregados diretamente do Norgate local.</p></div></CardContent></Card> : response ? <><div className="flex items-center justify-between"><div><h2 className="text-xl font-medium">Resultado real da validação</h2><p className="mt-1 text-sm text-muted-foreground">{response.assets_loaded} ativos · {response.validation === "walk_forward" ? "walk-forward" : `corte ${response.split_date}`}</p></div><Badge variant="outline"><Database className="size-3.5" />Norgate local</Badge></div>{best ? <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"><Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">Melhor entrada</p><p className="metric-number mt-2 text-2xl">RSI &lt; {metric(best, "rsi_entry_threshold")}</p></CardContent></Card><Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">Melhor saída</p><p className="metric-number mt-2 text-2xl">RSI &gt; {metric(best, "rsi_exit_threshold")}</p></CardContent></Card><Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">Sharpe OOS</p><p className="metric-number mt-2 text-2xl">{metric(best, "test_sharpe").toFixed(2)}</p></CardContent></Card><Card className="shadow-none"><CardContent className="p-5"><p className="text-xs text-muted-foreground">Degradação</p><p className="metric-number mt-2 text-2xl">{new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 }).format(degradation)}</p></CardContent></Card></section> : null}<Card className="shadow-none"><CardHeader><CardTitle>Ranking fora da amostra</CardTitle><CardDescription>Parâmetros e métricas retornados pelo motor Python.</CardDescription></CardHeader><CardContent className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Fold</TableHead><TableHead>Entrada</TableHead><TableHead>Saída</TableHead><TableHead>Barras</TableHead><TableHead className="text-right">Trades OOS</TableHead><TableHead className="text-right">Sharpe IS</TableHead><TableHead className="text-right">Sharpe OOS</TableHead><TableHead className="text-right">P&amp;L OOS</TableHead></TableRow></TableHeader><TableBody>{ranking.slice(0, 12).map((row, index) => <TableRow key={index}><TableCell>{String(row.fold ?? "—")}</TableCell><TableCell>{metric(row, "rsi_entry_threshold")}</TableCell><TableCell>{metric(row, "rsi_exit_threshold")}</TableCell><TableCell>{metric(row, "max_bars")}</TableCell><TableCell className="text-right">{metric(row, "test_trades")}</TableCell><TableCell className="text-right">{metric(row, "train_sharpe").toFixed(2)}</TableCell><TableCell className="text-right">{metric(row, "test_sharpe").toFixed(2)}</TableCell><TableCell className="text-right">{metric(row, "test_total_pnl").toLocaleString("pt-BR", { maximumFractionDigits: 2 })}</TableCell></TableRow>)}</TableBody></Table></CardContent></Card><div className="flex gap-3 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm"><AlertTriangle className="size-5 shrink-0 text-warning" /><p>Otimizadores amplificam risco de overfitting. Prefira regiões estáveis e confirme os parâmetros em outro universo.</p></div></> : <Card className="shadow-none"><CardContent className="grid min-h-96 place-items-center text-center"><div><Database className="mx-auto size-8 text-muted-foreground" /><p className="mt-4 font-medium">Configure e execute a primeira validação Norgate</p><p className="mt-2 text-sm text-muted-foreground">Nenhum resultado demonstrativo é exibido.</p></div></CardContent></Card>}</div>
  </div>;
}
