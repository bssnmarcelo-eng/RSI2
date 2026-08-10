import { ScreeningTable } from "@/components/product/screening-table";
import { PageHeader } from "@/components/product/page-header";
export const metadata={title:"Screening"};
export default function ScreeningPage(){return <><PageHeader eyebrow="Pesquisa" title="Encontre setups com contexto." description="Filtre sinais de reversão, valide liquidez e siga para fundamentos ou backtest em um clique."/><ScreeningTable/></>}
