import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function MetricCard({ label, value, delta, tone = "neutral", helper }: { label: string; value: string; delta?: string; tone?: "positive" | "negative" | "neutral"; helper?: string }) {
  const Icon = tone === "positive" ? ArrowUpRight : tone === "negative" ? ArrowDownRight : Minus;
  return (
    <Card className="shadow-none">
      <CardContent className="p-5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <div className="mt-2 flex items-end justify-between gap-3"><strong className="metric-number text-2xl font-medium">{value}</strong>{delta ? <span className={cn("flex items-center text-xs font-medium", tone === "positive" && "text-success", tone === "negative" && "text-destructive", tone === "neutral" && "text-muted-foreground")}><Icon className="mr-1 size-3.5" />{delta}</span> : null}</div>
        {helper ? <p className="mt-2 text-[11px] text-muted-foreground">{helper}</p> : null}
      </CardContent>
    </Card>
  );
}
