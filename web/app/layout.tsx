import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Suspense } from "react";

import { AppShell } from "@/components/product/app-shell";
import { Providers } from "@/components/product/providers";
import { Skeleton } from "@/components/ui/skeleton";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "RSI2 Research Lab", template: "%s · RSI2" },
  description: "Pesquisa quantitativa, backtests, otimização e screening em uma única plataforma.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8fa" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0d12" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        <Providers>
          <Suspense fallback={<Skeleton className="h-dvh w-full" />}>
            <AppShell>{children}</AppShell>
          </Suspense>
        </Providers>
      </body>
    </html>
  );
}
