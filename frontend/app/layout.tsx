import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Marketing Demand Harness",
  description: "Pedidos ao Marketing transformados em demandas completas e aprovadas.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        <header className="border-b border-slate-200 bg-white">
          <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <Link href="/" className="font-semibold">
              Marketing Demand Harness
            </Link>
            <div className="flex gap-4 text-sm">
              <Link href="/" className="text-indigo-700 hover:underline">
                Nova demanda
              </Link>
              <Link href="/tarefas" className="text-indigo-700 hover:underline">
                Quadro de tarefas
              </Link>
              <Link href="/registro" className="text-indigo-700 hover:underline">
                Registro
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
