"use client";

import { useState } from "react";
import { CheckCircle2, CircleAlert, Database, Save } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/product/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { getApiBase, getNorgateStatus, saveApiBase, type NorgateStatus } from "@/lib/api";

export default function SettingsPage() {
  const [apiUrl, setApiUrl] = useState(() => getApiBase());
  const [testing, setTesting] = useState(false);
  const [connection, setConnection] = useState<NorgateStatus | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  async function testConnection() {
    setTesting(true);
    setConnectionError(null);
    saveApiBase(apiUrl);
    try {
      const next = await getNorgateStatus();
      setConnection(next);
      window.dispatchEvent(new Event("rsi2-api-change"));
      if (next.available) toast.success("API e Norgate Data conectados.");
      else toast.warning(next.message);
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : "A API local não respondeu.";
      setConnection(null);
      setConnectionError(message);
      toast.error(message);
    } finally {
      setTesting(false);
    }
  }

  function savePreferences() {
    const normalized = saveApiBase(apiUrl);
    setApiUrl(normalized);
    window.dispatchEvent(new Event("rsi2-api-change"));
    toast.success("Preferências locais salvas.");
  }

  return <><PageHeader eyebrow="Preferências" title="Dados e configurações" description="Aponte o frontend para a API Python que acessa o Norgate neste computador." /><div className="grid gap-6 xl:grid-cols-2">
    <Card className="shadow-none"><CardHeader><CardTitle>Conexão local</CardTitle><CardDescription>O endereço fica salvo somente neste navegador. Nenhuma credencial Norgate é enviada ao frontend.</CardDescription></CardHeader><CardContent className="space-y-5"><div><Label htmlFor="api-url">API RSI2</Label><Input id="api-url" className="mt-2" value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} placeholder="http://127.0.0.1:8000" /><p className="mt-2 text-xs text-muted-foreground">Padrão recomendado: http://127.0.0.1:8000</p></div><div><Label>Provedor de mercado</Label><Select defaultValue="norgate" disabled><SelectTrigger className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="norgate">Norgate Data local</SelectItem></SelectContent></Select></div><Button variant="outline" onClick={testConnection} disabled={testing}><Database className="size-4" />{testing ? "Testando…" : "Salvar e testar conexão"}</Button>
      {connection ? <div className={`flex gap-3 rounded-xl border p-4 text-sm ${connection.available ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5"}`}><CheckCircle2 className={`size-5 shrink-0 ${connection.available ? "text-success" : "text-warning"}`} /><div><strong>{connection.available ? "Norgate conectado" : "API conectada; Norgate indisponível"}</strong><p className="mt-1 text-muted-foreground">{connection.message} · {connection.watchlists} watchlists · {connection.databases} databases</p></div></div> : null}
      {connectionError ? <div className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm" role="alert"><CircleAlert className="size-5 shrink-0 text-destructive" /><div><strong>A API não respondeu</strong><p className="mt-1 text-muted-foreground">{connectionError}</p><p className="mt-2 text-xs text-muted-foreground">Execute o script local na raiz do projeto e tente novamente.</p></div></div> : null}
    </CardContent></Card>
    <Card className="shadow-none"><CardHeader><CardTitle>Experiência e retenção</CardTitle><CardDescription>Preferências visuais locais para suas pesquisas.</CardDescription></CardHeader><CardContent className="space-y-5"><div className="grid gap-4 sm:grid-cols-2"><div><Label>Moeda de exibição</Label><Select defaultValue="USD"><SelectTrigger className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="USD">USD · Dólar</SelectItem><SelectItem value="BRL">BRL · Real</SelectItem></SelectContent></Select></div><div><Label>Fuso horário</Label><Select defaultValue="sp"><SelectTrigger className="mt-2"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="sp">America/São_Paulo</SelectItem><SelectItem value="ny">America/New_York</SelectItem><SelectItem value="utc">UTC</SelectItem></SelectContent></Select></div></div><label className="flex items-center justify-between rounded-xl border p-4"><span><strong className="block text-sm">Avisos metodológicos</strong><span className="text-xs text-muted-foreground">Exibir alertas de viés e overfitting.</span></span><Switch defaultChecked /></label><Button onClick={savePreferences}><Save className="size-4" />Salvar preferências</Button></CardContent></Card>
  </div></>;
}
