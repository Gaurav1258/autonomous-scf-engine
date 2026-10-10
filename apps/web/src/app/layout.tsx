import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Autonomous SCF Engine — Treasury Cockpit",
  description:
    "Institutional-grade autonomous supply chain finance, working capital floating engine, and multi-agent telemetry cockpit.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#070b14] text-slate-100 antialiased selection:bg-sky-500 selection:text-white">
        {/* Institutional Header */}
        <header className="sticky top-0 z-50 border-b border-slate-800/80 bg-[#090e1a]/90 backdrop-blur-md">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-sky-500 to-indigo-600 shadow-md shadow-sky-500/20">
                <span className="font-mono text-base font-black text-white">⚡</span>
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-sm font-bold tracking-tight text-white sm:text-base">
                    Autonomous SCF Engine
                  </h1>
                  <span className="rounded bg-sky-950/80 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-sky-400 border border-sky-800/50">
                    A2A Multi-Agent
                  </span>
                </div>
                <p className="text-[11px] text-slate-400">
                  Institutional Working Capital Floating & Dual-Approval Cockpit
                </p>
              </div>
            </div>

            {/* Cloud Run Live Status Indicator */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-3 py-1 text-xs">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
                </span>
                <span className="font-mono text-[11px] text-emerald-400">
                  Cloud Run: Online
                </span>
              </div>

              <a
                href="https://scf-api-8938740754.us-central1.run.app/docs"
                target="_blank"
                rel="noreferrer"
                className="hidden rounded-lg border border-slate-700/80 bg-slate-800/60 px-2.5 py-1 text-xs font-medium text-slate-300 transition-colors hover:border-slate-600 hover:text-white sm:inline-flex items-center gap-1.5"
              >
                <span>Swagger Docs</span>
                <span className="text-[10px] text-slate-400">↗</span>
              </a>
            </div>
          </div>
        </header>

        {/* Main Viewport */}
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
          {children}
        </main>
      </body>
    </html>
  );
}

