"use client";

import { useEffect, useState } from "react";
import { Database, Unplug } from "lucide-react";
import { getNorgateStatus } from "@/lib/api";

export function ApiIndicator() {
  const [available, setAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      setAvailable(null);
      getNorgateStatus().then((status) => {
        if (active) setAvailable(status.available);
      }).catch(() => {
        if (active) setAvailable(false);
      });
    };
    refresh();
    window.addEventListener("rsi2-api-change", refresh);
    return () => { active = false; window.removeEventListener("rsi2-api-change", refresh); };
  }, []);

  const Icon = available === false ? Unplug : Database;
  const label = available === null ? "Verificando dados" : available ? "Norgate conectado" : "API local offline";
  return <span className="flex items-center gap-2"><Icon className={`size-3.5 ${available ? "text-success" : available === false ? "text-warning" : "text-muted-foreground"}`} />{label}</span>;
}
