"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Building2, CalendarDays, Database, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getFundamentals, type FundamentalMetric, type FundamentalResponse } from "@/lib/api";

function MetricGrid({ metrics }: { metrics: FundamentalMetric[] }) {
  const available = metrics.filter((metric) => metric.value !== null);
  if (!available.length) return <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">Nenhum campo disponível nesta categoria para o ticker.</p>;
  return <div className="grid gap-3 sm:grid-cols-2">{available.map((metric) => <div key={metric.token} className="rounded-xl border p-4"><p className="text-xs text-muted-foreground">{metric.label}</p><p className="metric-number mt-2 text-xl font-medium">{metric.formatted}</p><p className="mt-1 text-xs text-muted-foreground">{metric.reference_date ? `Referência: ${metric.reference_date}` : "Snapshot atual"}</p></div>)}</div>;
}

export function FundamentalsView() {
  const [query, setQuery] = useState("AAPL");
  const [data, setData] = useState<FundamentalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try { setData(await getFundamentals(query)); }
    catch (reason: unknown) { setData(null); setError(reason instanceof Error ? reason.message : "Não foi possível consultar os fundamentos."); }
    finally { setLoading(false); }
  }

  const overview = data?.overview;
  return <>
    <Card className="mb-6 shadow-none"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row"><div className="relative flex-1"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input value={query} onChange={(event) => setQuery(event.target.value.toUpperCase())} onKeyDown={(event) => { if (event.key === "Enter") void load(); }} placeholder="Digite um ticker Norgate, ex.: AAPL" className="pl-9" /></div><Button onClick={() => void load()} disabled={loading}>{loading ? "Consultando…" : "Consultar Norgate"}</Button></CardContent></Card>
    {error ? <div className="mb-6 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm" role="alert"><strong>Consulta não concluída</strong><p className="mt-1 text-muted-foreground">{error}</p></div> : null}
    {!data ? <Card className="shadow-none"><CardContent className="grid min-h-80 place-items-center text-center"><div><Database className="mx-auto size-8 text-muted-foreground" /><h2 className="mt-4 font-medium">Consulte os fundamentos locais</h2><p className="mt-2 max-w-md text-sm text-muted-foreground">Os dados serão lidos do Norgate Data / LSEG neste computador; nenhuma amostra fictícia é exibida.</p></div></CardContent></Card> : <div className="grid gap-6 xl:grid-cols-[300px_minmax(0,1fr)]">
      <Card className="h-fit shadow-none"><CardContent className="p-6"><span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary"><Building2 className="size-5" /></span><p className="mt-5 font-mono text-sm text-primary">{data.ticker}</p><h2 className="mt-1 text-xl font-medium">{overview?.name ?? data.ticker}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{[overview?.exchange, overview?.currency, overview?.gics_sector, overview?.gics_industry].filter(Boolean).join(" · ")}</p><div className="mt-6 border-t pt-5"><p className="text-xs text-muted-foreground">Último preço</p><p className="metric-number mt-1 text-2xl">{data.price === null ? "—" : new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(data.price)}</p><p className="mt-4 text-xs text-muted-foreground">Cobertura</p><p className="metric-number mt-1">{data.fields_with_data} de {data.fields_total} campos</p></div><div className="mt-6 flex items-center gap-2 text-xs text-muted-foreground"><CalendarDays className="size-4" />Última cotação: {overview?.last_quoted ?? "—"}</div><Button variant="outline" className="mt-6 w-full" asChild><Link href="/backtests">Testar este ativo <ArrowRight className="size-4" /></Link></Button></CardContent></Card>
      <Card className="shadow-none"><CardHeader><CardTitle>Fundamentos atuais</CardTitle><CardDescription>Snapshot Norgate/LSEG; cada valor preserva sua data de referência.</CardDescription></CardHeader><CardContent><Tabs defaultValue="category-0"><TabsList className="h-auto w-full justify-start overflow-x-auto">{data.categories.map((category, index) => <TabsTrigger key={category.title} value={`category-${index}`}>{category.title}</TabsTrigger>)}</TabsList>{data.categories.map((category, index) => <TabsContent key={category.title} value={`category-${index}`} className="mt-6"><p className="mb-4 text-sm text-muted-foreground">{category.help}</p><MetricGrid metrics={category.metrics} /></TabsContent>)}</Tabs><p className="mt-6 rounded-xl bg-muted p-4 text-xs leading-5 text-muted-foreground">Fundamentos são snapshots atuais, não séries point-in-time para backtests. Confira as datas de referência antes de tomar decisões.</p></CardContent></Card>
    </div>}
  </>;
}
