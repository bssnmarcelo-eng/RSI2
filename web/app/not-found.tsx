import Link from "next/link";
import { Button } from "@/components/ui/button";
import { DataState } from "@/components/product/data-state";
export default function NotFound(){return <div className="py-12"><DataState type="empty" title="Página não encontrada" description="O endereço pode ter mudado ou a execução foi removida."/><Button className="mx-auto mt-4 flex w-fit" asChild><Link href="/">Voltar à visão geral</Link></Button></div>}
