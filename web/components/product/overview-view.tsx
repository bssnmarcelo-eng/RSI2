"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Database, FileCheck2, History, Play } from "lucide-react";
import { EquityChart } from "@/components/product/equity-chart";
import { MetricCard } from "@/components/product/metric-card";
import { PageHeader } from "@/components/product/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getNorgateStatus, getRuns, type NorgateStatus, type RunSummary } from "@/lib/api";

function percent(value?: number) {
  if (value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value);
}

function number(value?: number) {
  if (value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export function OverviewView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [status, setStatus] = useState<NorgateStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getRuns(), getNorgateStatus()]).then(([nextRuns, nextStatus]) => {
      if (!active) return;
      setRuns(nextRuns);
      setStatus(nextStatus);
    }).catch(() => {
      if (active) setOffline(true);
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  const completed = useMemo(() => runs.filter((run) => run.status === "completed" && run.source === "norgate"), [runs]);
  const latest = completed[0];

  return <>
    <PageHeader eyebrow="Visão geral" title="Decisões quantitativas, sem ruído." description="Resultados desta tela vêm da API Python e do Norgate instalados neste computador." actions={<><Button variant="outline" asChild><Link href="/history"><History className="size-4" />Ver histórico</Link></Button><Button asChild><Link href="/backtests"><Play className="size-4" />Novo backtest</Link></Button></>} />
    {offline ? <div className="mb-6 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm"><strong>API local offline</strong><p className="mt-1 text-muted-foreground">Inicie o ambiente local para carregar resultados Norgate. Nenhum dado demonstrativo será exibido no lugar deles.</p></div> : null}
    <section aria-label="Indicadores principais" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Retorno da última execução" value={percent(latest?.metrics.total_return)} tone={(latest?.metrics.total_return ?? 0) >= 0 ? "positive" : "negative"} helper={latest?.name ?? "Nenhuma execução Norgate nesta sessão"} /><MetricCard label="Sharpe" value={number(latest?.metrics.sharpe)} tone={(latest?.metrics.sharpe ?? 0) >= 1 ? "positive" : "neutral"} helper="Calculado pela curva real" /><MetricCard label="Drawdown máximo" value={percent(latest?.metrics.max_drawdown)} tone="negative" helper="Pico ao vale da curva" /><MetricCard label="Execuções locais" value={loading ? "…" : String(runs.length)} helper={`${completed.length} backtest(s) Norgate concluído(s)`} /></section>
    <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,.8fr)]">
      <Card className="shadow-none"><CardHeader className="flex-row items-start justify-between"><div><CardTitle>Patrimônio da última execução</CardTitle><CardDescription>{latest ? `${latest.name} · série real` : "Execute um backtest para gerar a primeira curva"}</CardDescription></div>{latest ? <Badge variant="secondary">Norgate local</Badge> : null}</CardHeader><CardContent>{latest?.equity.length ? <EquityChart compact points={latest.equity} /> : <div className="grid h-56 place-items-center rounded-xl border border-dashed text-center"><div><Database className="mx-auto size-7 text-muted-foreground" /><p className="mt-3 text-sm font-medium">Ainda não há uma curva nesta sessão</p><p className="mt-1 text-xs text-muted-foreground">Os resultados não são substituídos por amostras fictícias.</p></div></div>}</CardContent></Card>
      <Card className="shadow-none"><CardHeader><CardTitle>Ambiente local</CardTitle><CardDescription>Estado da fonte usada nos cálculos.</CardDescription></CardHeader><CardContent className="space-y-4"><div className={`rounded-xl border p-4 ${status?.available ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5"}`}><div className="flex items-center gap-2"><span className={`size-2 rounded-full ${status?.available ? "bg-success" : "bg-warning"}`} /><strong className="text-sm">{status?.available ? "Norgate conectado" : loading ? "Verificando…" : "Norgate indisponível"}</strong></div><p className="mt-2 text-xs leading-5 text-muted-foreground">{status ? `${status.watchlists} watchlists · ${status.databases} databases` : "API em http://127.0.0.1:8000"}</p></div><Button className="w-full" asChild><Link href="/backtests">Configurar backtest <ArrowRight className="size-4" /></Link></Button><Button variant="outline" className="w-full" asChild><Link href="/settings">Testar conexão</Link></Button></CardContent></Card>
    </div>
    <Card className="mt-6 shadow-none"><CardHeader className="flex-row items-center justify-between"><div><CardTitle>Execuções recentes</CardTitle><CardDescription>Somente resultados produzidos pela API nesta sessão.</CardDescription></div><Button variant="ghost" asChild><Link href="/history">Ver histórico <ArrowRight className="size-4" /></Link></Button></CardHeader><CardContent className="overflow-x-auto">{runs.length ? <Table><TableHeader><TableRow><TableHead>Execução</TableHead><TableHead>Fonte</TableHead><TableHead>Modo</TableHead><TableHead>Quando</TableHead><TableHead className="text-right">Retorno</TableHead><TableHead className="text-right">Sharpe</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{runs.slice(0, 5).map((run) => <TableRow key={run.id}><TableCell><strong className="block text-sm">{run.name}</strong><span className="font-mono text-[11px] text-muted-foreground">{run.id}</span></TableCell><TableCell><Badge variant="outline"><Database className="mr-1 size-3" />{run.source === "norgate" ? "Norgate" : "API"}</Badge></TableCell><TableCell>{run.mode === "portfolio" ? "Carteira" : "Por ativo"}</TableCell><TableCell className="text-muted-foreground">{new Date(run.created_at).toLocaleString("pt-BR")}</TableCell><TableCell className={`metric-number text-right ${(run.metrics.total_return ?? 0) >= 0 ? "text-success" : "text-destructive"}`}>{run.status === "completed" ? percent(run.metrics.total_return) : "—"}</TableCell><TableCell className="metric-number text-right">{run.status === "completed" ? number(run.metrics.sharpe) : "—"}</TableCell><TableCell><Badge variant="outline" className="gap-1"><FileCheck2 className="size-3" />{run.status}</Badge></TableCell></TableRow>)}</TableBody></Table> : <div className="py-8 text-center text-sm text-muted-foreground">Nenhuma execução local registrada.</div>}</CardContent></Card>
  </>;
}
