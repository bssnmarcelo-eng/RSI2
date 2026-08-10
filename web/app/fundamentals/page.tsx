import { FundamentalsView } from "@/components/product/fundamentals-view";
import { PageHeader } from "@/components/product/page-header";
export const metadata={title:"Fundamentos"};
export default function FundamentalsPage(){return <><PageHeader eyebrow="Pesquisa" title="Entenda o ativo além do sinal." description="Valuation, qualidade, balanço e crescimento com referência temporal explícita."/><FundamentalsView/></>}
