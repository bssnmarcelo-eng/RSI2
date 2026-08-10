import { BacktestWorkbench } from "@/components/product/backtest-workbench";
import { PageHeader } from "@/components/product/page-header";

export const metadata = { title: "Backtests" };
export default function BacktestsPage() { return <><PageHeader eyebrow="Laboratório" title="Configure um backtest reproduzível." description="Um fluxo guiado para definir universo, regras, custos e risco antes de calcular qualquer resultado."/><BacktestWorkbench/></>; }
