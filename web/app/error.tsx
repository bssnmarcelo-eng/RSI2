"use client";
import { useEffect } from "react";
import { DataState } from "@/components/product/data-state";
export default function ErrorPage({error,reset}:{error:Error&{digest?:string};reset:()=>void}){useEffect(()=>{console.error(error)},[error]);return <div className="py-12" onClick={reset}><DataState type="error" title="Não foi possível carregar esta área" description="Tente novamente. Se o problema persistir, confira a conexão com a API e o identificador da execução." action="Tentar novamente"/></div>}
