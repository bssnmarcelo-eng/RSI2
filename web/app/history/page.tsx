import { HistoryView } from "@/components/product/history-view";
import { PageHeader } from "@/components/product/page-header";
export const metadata={title:"Histórico"};
export default function HistoryPage(){return <><PageHeader eyebrow="Rastreabilidade" title="Cada resultado tem uma origem." description="Encontre, compare, duplique e exporte execuções com parâmetros e dados versionados."/><HistoryView/></>}
