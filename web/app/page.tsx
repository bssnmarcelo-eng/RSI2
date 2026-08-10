import Link from "next/link";
import { ArrowRight, Database, FileCheck2, FlaskConical, Play } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EquityChart } from "@/components/product/equity-chart";
import { MetricCard } from "@/components/product/metric-card";
import { PageHeader } from "@/components/product/page-header";
import { recentRuns } from "@/lib/demo-data";

export default function OverviewPage() {
  return <>
    <PageHeader eyebrow="Visão geral" title="Decisões quantitativas, sem ruído." description="Configure, valide e compare estratégias de reversão à média com rastreabilidade do dado ao resultado." actions={<><Button variant="outline" asChild><Link href="/screening">Abrir screening</Link></Button><Button asChild><Link href="/backtests"><Play className="size-4" />Novo backtest</Link></Button></>} />
    <section aria-label="Indicadores principais" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard label="Retorno da melhor carteira" value="+36,2%" delta="+17,2 p.p. vs. IBOV" tone="positive" helper="Últimos 12 meses simulados" /><MetricCard label="Sharpe" value="1,41" delta="Risco ajustado" tone="positive" helper="Taxa livre de risco: 10,5% a.a." /><MetricCard label="Drawdown máximo" value="−12,7%" delta="Recuperado em 34 dias" tone="negative" helper="Pico ao vale da curva" /><MetricCard label="Execuções este mês" value="28" delta="6 novas" helper="24 backtests · 4 otimizações" /></section>
    <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(300px,.8fr)]">
      <Card className="shadow-none"><CardHeader className="flex-row items-start justify-between"><div><CardTitle>Patrimônio comparado</CardTitle><CardDescription>Carteira RSI2 × Ibovespa · base 100</CardDescription></div><Badge variant="secondary">12 meses</Badge></CardHeader><CardContent><EquityChart compact /></CardContent></Card>
      <Card className="shadow-none"><CardHeader><CardTitle>Comece uma pesquisa</CardTitle><CardDescription>Fluxos guiados com parâmetros revisáveis.</CardDescription></CardHeader><CardContent className="space-y-3">
        {[{href:"/backtests",icon:Play,title:"Testar uma carteira",text:"Universo, regras, custos e sizing."},{href:"/optimizer",icon:FlaskConical,title:"Validar parâmetros",text:"IS/OOS e walk-forward sem vazamento."},{href:"/screening",icon:Database,title:"Encontrar setups",text:"Sinais atuais com liquidez e contexto."}].map(x=><Link key={x.href} href={x.href} className="group flex min-h-16 items-center gap-3 rounded-xl border p-3 transition-colors hover:bg-muted"><span className="grid size-10 place-items-center rounded-lg bg-primary/10 text-primary"><x.icon className="size-4.5" /></span><span className="min-w-0 flex-1"><strong className="block text-sm">{x.title}</strong><span className="block truncate text-xs text-muted-foreground">{x.text}</span></span><ArrowRight className="size-4 text-muted-foreground group-hover:text-foreground" /></Link>)}
      </CardContent></Card>
    </div>
    <Card className="mt-6 shadow-none"><CardHeader className="flex-row items-center justify-between"><div><CardTitle>Execuções recentes</CardTitle><CardDescription>Resultados versionados e reproduzíveis.</CardDescription></div><Button variant="ghost" asChild><Link href="/history">Ver histórico <ArrowRight className="size-4" /></Link></Button></CardHeader><CardContent className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Execução</TableHead><TableHead>Modo</TableHead><TableHead>Quando</TableHead><TableHead className="text-right">Retorno</TableHead><TableHead className="text-right">Sharpe</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{recentRuns.map(run=><TableRow key={run.id}><TableCell><strong className="block text-sm">{run.name}</strong><span className="font-mono text-[11px] text-muted-foreground">{run.id}</span></TableCell><TableCell>{run.mode}</TableCell><TableCell className="text-muted-foreground">{run.date}</TableCell><TableCell className="metric-number text-right text-success">{run.return}</TableCell><TableCell className="metric-number text-right">{run.sharpe}</TableCell><TableCell><Badge variant="outline" className="gap-1"><FileCheck2 className="size-3" />{run.status}</Badge></TableCell></TableRow>)}</TableBody></Table></CardContent></Card>
  </>;
}
