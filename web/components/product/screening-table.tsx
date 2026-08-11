"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BarChart3, Database, FlaskConical, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getNorgateCatalog, getNorgateSymbols, runNorgateScreening, type ScreeningResponse } from "@/lib/api";

const preferred = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "JPM", "LLY", "COST"];
function parseSymbols(value: string) { return [...new Set(value.split(/[\s,;]+/).map((symbol) => symbol.toUpperCase()).filter(Boolean))]; }

export function ScreeningTable() {
  const [collections, setCollections] = useState<string[]>([]);
  const [collectionName, setCollectionName] = useState("");
  const [symbolsText, setSymbolsText] = useState("");
  const [availableCount, setAvailableCount] = useState(0);
  const [useEntireCollection, setUseEntireCollection] = useState(false);
  const [rsiMax, setRsiMax] = useState(20);
  const [minPrice, setMinPrice] = useState(0);
  const [frequency, setFrequency] = useState("Diário");
  const [query, setQuery] = useState("");
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<ScreeningResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

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
    getNorgateSymbols("watchlist", collectionName).then(({ count, symbols }) => {
      if (!active) return;
      setAvailableCount(count);
      const suggested = preferred.filter((symbol) => symbols.includes(symbol));
      setSymbolsText((suggested.length ? suggested : symbols.slice(0, 10)).join(", "));
    }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Falha ao carregar símbolos."); });
    return () => { active = false; };
  }, [collectionName]);

  async function screen() {
    setRunning(true);
    setError(null);
    try {
      setResponse(await runNorgateScreening({
        collection_type: "watchlist", collection_name: collectionName,
        symbols: useEntireCollection ? [] : parseSymbols(symbolsText), use_entire_collection: useEntireCollection,
        start_date: "2024-01-01", end_date: "2026-08-10", frequency,
        adjustment: "Total Return (splits + dividendos)", rsi_period: 2, rsi_max: rsiMax,
        min_price: minPrice, min_average_turnover: 0,
      }));
    } catch (reason: unknown) { setResponse(null); setError(reason instanceof Error ? reason.message : "Screening não concluído."); }
    finally { setRunning(false); }
  }

  const rows = useMemo(() => (response?.results ?? []).filter((row) => row.ticker.includes(query.toUpperCase())), [query, response]);
  return <>
    <Card className="mb-6 shadow-none"><CardContent className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-[1.2fr_1fr_120px_120px_auto] xl:items-end"><div><Label>Watchlist Norgate</Label><Select value={collectionName} onValueChange={setCollectionName}><SelectTrigger className="mt-2"><SelectValue placeholder="Selecione" /></SelectTrigger><SelectContent>{collections.map((name) => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select></div><div><Label>Ativos ({availableCount.toLocaleString("pt-BR")} disponíveis)</Label><Input className="mt-2" value={symbolsText} onChange={(event) => setSymbolsText(event.target.value)} disabled={useEntireCollection} /></div><div><Label>RSI máx.</Label><Input className="mt-2" type="number" value={rsiMax} onChange={(event) => setRsiMax(Number(event.target.value))} /></div><div><Label>Preço mín.</Label><Input className="mt-2" type="number" value={minPrice} onChange={(event) => setMinPrice(Number(event.target.value))} /></div><Button onClick={() => void screen()} disabled={running || !collectionName}><Database className="size-4" />{running ? "Buscando…" : "Buscar sinais"}</Button><div><Label>Frequência</Label><Select value={frequency} onValueChange={setFrequency}><SelectTrigger className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="Diário">Diário</SelectItem><SelectItem value="Semanal">Semanal</SelectItem><SelectItem value="Mensal">Mensal</SelectItem></SelectContent></Select></div><label className="flex items-center gap-3 rounded-lg border p-3 text-sm"><Switch checked={useEntireCollection} onCheckedChange={setUseEntireCollection} />Coleção inteira</label></CardContent></Card>
    {error ? <div className="mb-6 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm" role="alert">{error}</div> : null}
    {response ? <><Card className="mb-4 shadow-none"><CardContent className="flex flex-col justify-between gap-3 p-4 sm:flex-row sm:items-center"><div><strong className="text-sm">{response.count} ativo(s) com RSI ≤ {rsiMax}</strong><p className="text-xs text-muted-foreground">{response.assets_loaded} séries Norgate carregadas · referência {response.as_of}</p></div><div className="relative sm:w-64"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filtrar resultado" className="pl-9" /></div></CardContent></Card>{rows.length ? <Card className="shadow-none"><CardContent className="p-0"><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Ativo</TableHead><TableHead>Data</TableHead><TableHead className="text-right">Preço</TableHead><TableHead className="text-right">RSI(2)</TableHead><TableHead>Sinal completo</TableHead><TableHead className="text-right">Giro médio</TableHead><TableHead className="text-right">Dist. MM200</TableHead><TableHead><span className="sr-only">Ações</span></TableHead></TableRow></TableHeader><TableBody>{rows.map((row) => <TableRow key={row.ticker}><TableCell className="font-medium">{row.ticker}</TableCell><TableCell>{row.date}</TableCell><TableCell className="text-right">{row.close.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}</TableCell><TableCell className="text-right font-mono">{row.rsi.toFixed(2)}</TableCell><TableCell><Badge variant={row.entry_signal ? "default" : "outline"}>{row.entry_signal ? row.pattern || "Entrada" : "RSI apenas"}</Badge></TableCell><TableCell className="text-right">{new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(row.average_turnover)}</TableCell><TableCell className="text-right">{row.distance_sma_200 === null ? "—" : new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 }).format(row.distance_sma_200)}</TableCell><TableCell><div className="flex justify-end gap-1"><Button size="icon" variant="ghost" aria-label={`Ver fundamentos de ${row.ticker}`} asChild><Link href={`/fundamentals?ticker=${row.ticker}`}><BarChart3 className="size-4" /></Link></Button><Button size="icon" variant="ghost" aria-label={`Testar ${row.ticker}`} asChild><Link href="/backtests"><FlaskConical className="size-4" /></Link></Button></div></TableCell></TableRow>)}</TableBody></Table></div></CardContent></Card> : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">Nenhum ativo atende aos filtros atuais.</div>}</> : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">Configure o universo e consulte os sinais atuais no Norgate local.</div>}
  </>;
}
