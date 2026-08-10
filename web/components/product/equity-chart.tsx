"use client";

import { Area, AreaChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { equityCurve } from "@/lib/demo-data";

export function EquityChart({ compact = false }: { compact?: boolean }) {
  return (
    <div>
      <div className={compact ? "h-56" : "h-80"} role="img" aria-label="Curva de patrimônio: carteira de 100 para 136 e benchmark de 100 para 119">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={equityCurve} margin={{ top: 10, right: 8, left: -18, bottom: 0 }}>
            <defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="var(--primary)" stopOpacity={0.22}/><stop offset="95%" stopColor="var(--primary)" stopOpacity={0}/></linearGradient></defs>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} />
            <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} domain={[95, 140]} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, color: "var(--popover-foreground)", fontSize: 12 }} />
            <Area isAnimationActive={false} type="monotone" dataKey="portfolio" name="Carteira" stroke="var(--primary)" strokeWidth={2.5} fill="url(#equity-fill)" />
            <Line isAnimationActive={false} type="monotone" dataKey="benchmark" name="Ibovespa" stroke="var(--muted-foreground)" strokeWidth={1.5} dot={false} strokeDasharray="5 5" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer min-h-11 py-3">Ver dados do gráfico em texto</summary><p>A carteira terminou em 136, contra 119 do benchmark, partindo de base 100.</p></details>
    </div>
  );
}
