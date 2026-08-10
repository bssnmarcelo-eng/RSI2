import { Skeleton } from "@/components/ui/skeleton";
export default function Loading(){return <div aria-label="Carregando conteúdo" role="status"><Skeleton className="h-8 w-36"/><Skeleton className="mt-4 h-12 max-w-2xl"/><div className="mt-8 grid gap-4 md:grid-cols-4">{Array.from({length:4}).map((_,i)=><Skeleton key={i} className="h-32"/>)}</div><Skeleton className="mt-6 h-96"/></div>}
