"use client";

import { useMemo } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type EquityPoint = { date: string; value: number };
type ChartPoint = { date: string; portfolio: number; equity?: number };

export function EquityChart({ compact = false, points }: { compact?: boolean; points?: EquityPoint[] }) {
  const hasRealData = Boolean(points?.length);
  const chartData = useMemo<ChartPoint[]>(() => {
    if (!points?.length) return [];
    const first = points[0].value || 1;
    const stride = Math.max(1, Math.ceil(points.length / 320));
    return points.filter((_, index) => index % stride === 0 || index === points.length - 1).map((point) => ({
      date: new Date(point.date).toLocaleDateString("pt-BR", { month: "short", year: "2-digit" }),
      portfolio: (point.value / first) * 100,
      equity: point.value,
    }));
  }, [points]);
  const last = points?.at(-1)?.value;

  return (
    <div>
      <div className={compact ? "h-56" : "h-80"} role="img" aria-label={hasRealData ? `Curva de patrimônio real com ${points?.length} observações e valor final ${last}` : "Curva de patrimônio sem dados"}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
            <defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="var(--primary)" stopOpacity={0.22} /><stop offset="95%" stopColor="var(--primary)" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} minTickGap={34} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} domain={["auto", "auto"]} />
            <Tooltip formatter={(value, name, item) => hasRealData && name === "Carteira" ? [new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(Number(item.payload.equity)), "Patrimônio"] : [Number(value).toFixed(2), String(name)]} contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }} />
            <Area isAnimationActive={false} type="monotone" dataKey="portfolio" name="Carteira" stroke="var(--primary)" strokeWidth={2.5} fill="url(#equity-fill)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer min-h-11 py-3">Ver dados do gráfico em texto</summary><p>{hasRealData ? `A série contém ${points?.length.toLocaleString("pt-BR")} observações. O patrimônio final foi ${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 2 }).format(last ?? 0)}.` : "Nenhuma série foi fornecida para o gráfico."}</p></details>
    </div>
  );
}
