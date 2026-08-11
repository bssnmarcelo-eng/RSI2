"use client";

import { useEffect, useMemo, useState } from "react";
import { Database, MoreHorizontal, RefreshCw, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { deleteRun, getRuns, type RunSummary } from "@/lib/api";

function percent(value = 0) { return new Intl.NumberFormat("pt-BR", { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 2 }).format(value); }

export function HistoryView() {
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const rows = useMemo(() => runs.filter((run) => `${run.name} ${run.id} ${run.mode}`.toLowerCase().includes(query.toLowerCase())), [query, runs]);

  async function refresh() {
    setLoading(true);
    setError(null);
    try { setRuns(await getRuns()); }
    catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar o histórico local."); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    let active = true;
    getRuns().then((nextRuns) => {
      if (active) setRuns(nextRuns);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o histórico local.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, []);

  async function remove(runId: string) {
    try {
      await deleteRun(runId);
      setRuns((current) => current.filter((run) => run.id !== runId));
      toast.success("Execução excluída.");
    } catch (reason: unknown) {
      toast.error(reason instanceof Error ? reason.message : "Falha ao excluir a execução.");
    }
  }

  return <>
    <Card className="mb-5 shadow-none"><CardContent className="flex flex-col gap-3 p-4 md:flex-row"><div className="relative flex-1"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar nome, modo ou ID" className="pl-9" /></div><Button variant="outline" onClick={() => void refresh()} disabled={loading}><RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />Atualizar</Button></CardContent></Card>
    {error ? <div className="mb-5 rounded-xl border border-warning/30 bg-warning/5 p-4 text-sm"><strong>Histórico local indisponível</strong><p className="mt-1 text-muted-foreground">{error}</p></div> : null}
    <Card className="shadow-none"><CardContent className="p-0"><div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>Execução</TableHead><TableHead>Fonte</TableHead><TableHead>Modo</TableHead><TableHead>Data</TableHead><TableHead className="text-right">Retorno</TableHead><TableHead className="text-right">Sharpe</TableHead><TableHead>Status</TableHead><TableHead><span className="sr-only">Ações</span></TableHead></TableRow></TableHeader><TableBody>{rows.map((run) => <TableRow key={run.id}><TableCell><strong className="block text-sm">{run.name}</strong><span className="font-mono text-[11px] text-muted-foreground">{run.id}</span></TableCell><TableCell>{run.source === "norgate" ? <Badge variant="outline"><Database className="mr-1 size-3" />Norgate local</Badge> : <Badge variant="secondary">API</Badge>}</TableCell><TableCell>{run.mode === "portfolio" ? "Carteira" : "Por ativo"}</TableCell><TableCell className="text-muted-foreground">{new Date(run.created_at).toLocaleString("pt-BR")}</TableCell><TableCell className={`text-right ${(run.metrics.total_return ?? 0) >= 0 ? "text-success" : "text-destructive"}`}>{run.status === "completed" ? percent(run.metrics.total_return) : "—"}</TableCell><TableCell className="text-right">{run.status === "completed" ? Number(run.metrics.sharpe ?? 0).toFixed(2) : "—"}</TableCell><TableCell><Badge variant="outline">{run.status}</Badge></TableCell><TableCell><DropdownMenu><DropdownMenuTrigger asChild><Button size="icon" variant="ghost" aria-label={`Ações de ${run.id}`}><MoreHorizontal className="size-4" /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><AlertDialog><AlertDialogTrigger asChild><DropdownMenuItem variant="destructive" onSelect={(event) => event.preventDefault()}><Trash2 />Excluir</DropdownMenuItem></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Excluir {run.id}?</AlertDialogTitle><AlertDialogDescription>O resultado será removido do processo local da API.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancelar</AlertDialogCancel><AlertDialogAction onClick={() => void remove(run.id)}>Excluir execução</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></DropdownMenuContent></DropdownMenu></TableCell></TableRow>)}</TableBody></Table></div>{!loading && !rows.length ? <div className="p-8 text-center text-sm text-muted-foreground">Nenhuma execução encontrada. Rode um backtest Norgate para vê-lo aqui.</div> : null}</CardContent></Card>
  </>;
}
