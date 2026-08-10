import { OptimizerLab } from "@/components/product/optimizer-lab";
import { PageHeader } from "@/components/product/page-header";
export const metadata={title:"Otimizador"};
export default function OptimizerPage(){return <><PageHeader eyebrow="Pesquisa" title="Encontre regiões robustas, não picos." description="Compare parâmetros com separação real entre treino e teste, walk-forward e leitura explícita de degradação."/><OptimizerLab/></>}
