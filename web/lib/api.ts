export type RunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type RunSummary = { id: string; name: string; mode: string; status: RunStatus; metrics: Record<string, number>; warnings: string[]; trade_count: number };

const apiBase = process.env.NEXT_PUBLIC_RSI2_API_URL;

export async function getRuns(): Promise<RunSummary[]> {
  if (!apiBase) return [];
  const response = await fetch(`${apiBase}/v1/runs`, { next: { revalidate: 30 } });
  if (!response.ok) throw new Error(`API RSI2 respondeu ${response.status}`);
  return response.json() as Promise<RunSummary[]>;
}
