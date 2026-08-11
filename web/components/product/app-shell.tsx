"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  Activity, BarChart3, BookOpen, BriefcaseBusiness, ChevronRight,
  FlaskConical, History, Menu, Moon, Search, Settings2, Sun, Target,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiIndicator } from "@/components/product/api-indicator";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const navigation = [
  { label: "Visão geral", href: "/", icon: Activity },
  { label: "Backtests", href: "/backtests", icon: BriefcaseBusiness },
  { label: "Otimizador", href: "/optimizer", icon: FlaskConical },
  { label: "Screening", href: "/screening", icon: Search },
  { label: "Fundamentos", href: "/fundamentals", icon: BarChart3 },
  { label: "Histórico", href: "/history", icon: History },
];

function Brand() {
  return (
    <Link href="/" className="flex min-h-11 items-center gap-3 rounded-lg px-2" aria-label="RSI2 — início">
      <span className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <Target className="size-5" aria-hidden="true" />
      </span>
      <span><strong className="block text-sm font-semibold tracking-tight">RSI2</strong><span className="block text-[11px] text-muted-foreground">Research Lab</span></span>
    </Link>
  );
}

function Navigation({ mobile = false }: { mobile?: boolean }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Navegação principal" className="space-y-1">
      {navigation.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link key={item.href} href={item.href} className={cn(
            "group flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors",
            active ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            mobile && "text-base",
          )} aria-current={active ? "page" : undefined}>
            <item.icon className="size-4.5" aria-hidden="true" />
            <span className="flex-1">{item.label}</span>
            {active ? <ChevronRight className="size-4" aria-hidden="true" /> : null}
          </Link>
        );
      })}
    </nav>
  );
}

function ThemeButton() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  return (
    <Button variant="ghost" size="icon" onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "Usar tema claro" : "Usar tema escuro"}>
      {dark ? <Sun className="size-4.5" /> : <Moon className="size-4.5" />}
    </Button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[244px_minmax(0,1fr)]">
      <aside className="fixed inset-y-0 z-30 hidden w-[244px] border-r bg-sidebar lg:flex lg:flex-col">
        <div className="px-4 py-5"><Brand /></div>
        <div className="flex-1 px-3"><Navigation /></div>
        <div className="space-y-2 border-t p-3">
          <Link href="/settings" className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"><Settings2 className="size-4.5" />Configurações</Link>
          <Link href="/methodology" className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"><BookOpen className="size-4.5" />Metodologia e riscos</Link>
          <div className="flex items-center justify-between rounded-lg border bg-card px-3 py-2 text-xs"><ApiIndicator /><ThemeButton /></div>
        </div>
      </aside>
      <div className="min-w-0 lg:col-start-2">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b bg-background/92 px-4 backdrop-blur md:px-8 lg:px-10">
          <div className="flex items-center gap-3 lg:hidden">
            <Sheet>
              <SheetTrigger asChild><Button variant="outline" size="icon" aria-label="Abrir menu"><Menu className="size-5" /></Button></SheetTrigger>
              <SheetContent side="left" className="w-[292px] p-4"><SheetTitle className="sr-only">Menu</SheetTitle><Brand /><div className="mt-6"><Navigation mobile /><div className="mt-5 border-t pt-4"><Link href="/settings" className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted"><Settings2 className="size-4.5"/>Configurações</Link><Link href="/methodology" className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm text-muted-foreground hover:bg-muted"><BookOpen className="size-4.5"/>Metodologia e riscos</Link></div></div></SheetContent>
            </Sheet>
            <Brand />
          </div>
          <div className="hidden items-center gap-2 text-xs text-muted-foreground lg:flex"><span className="size-2 rounded-full bg-success" />Ambiente de pesquisa</div>
          <div className="flex items-center gap-2"><Button variant="outline" className="hidden md:inline-flex" asChild><Link href="/backtests">Novo backtest</Link></Button><ThemeButton /></div>
        </header>
        <main id="conteudo" className="mx-auto w-full max-w-[1480px] p-4 md:p-8 lg:p-10">{children}</main>
      </div>
    </div>
  );
}
