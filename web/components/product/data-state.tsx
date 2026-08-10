import { AlertTriangle, Database, LoaderCircle, SearchX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export function DataState({ type, title, description, action }: { type: "empty" | "error" | "loading" | "partial"; title: string; description: string; action?: string }) {
  const Icon = type === "empty" ? SearchX : type === "error" ? AlertTriangle : type === "loading" ? LoaderCircle : Database;
  return <Card className="border-dashed shadow-none"><CardContent className="grid min-h-52 place-items-center p-8 text-center"><div><Icon className={`mx-auto mb-4 size-7 text-muted-foreground ${type === "loading" ? "animate-spin" : ""}`} /><h3 className="font-medium">{title}</h3><p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">{description}</p>{action ? <Button variant="outline" className="mt-5">{action}</Button> : null}</div></CardContent></Card>;
}
