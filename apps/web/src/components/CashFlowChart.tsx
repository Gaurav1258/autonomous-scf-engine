"use client";

import React, { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatCompactCurrency, formatCurrency } from "@/lib/formatters";
import { scfApi } from "@/lib/api-client";
import { CashCurvePoint, CashCurveResponse } from "@/types";

interface CashFlowChartProps {
  buyerId?: string;
  simulateAdvanceAmount?: number;
}

export function CashFlowChart({
  buyerId = "CORP-INFOSYS",
  simulateAdvanceAmount = 0,
}: CashFlowChartProps) {
  const [data, setData] = useState<CashCurveResponse | null>(null);
  const [selectedBuyer, setSelectedBuyer] = useState(buyerId);
  const [simulateAmount, setSimulateAmount] = useState(simulateAdvanceAmount);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;
    setIsLoading(true);

    scfApi
      .getCashCurve(selectedBuyer, 60, simulateAmount)
      .then((res) => {
        if (isMounted) setData(res);
      })
      .catch((err) => console.error("Failed to load cash curve:", err))
      .finally(() => {
        if (isMounted) setIsLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedBuyer, simulateAmount]);

  const curvePoints = data?.daily_curve || [];

  return (
    <div className="flex flex-col rounded-xl border border-slate-800/80 bg-[#0d1322] shadow-lg">
      {/* Chart Header & Controls */}
      <div className="border-b border-slate-800/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-indigo-400"></span>
              <h3 className="text-sm font-bold text-white">
                60-Day Cash Trajectory & Credit Headroom
              </h3>
            </div>
            <p className="text-xs text-slate-400">
              Corporate cash reserves projected against the $10M inviolable liquidity floor
            </p>
          </div>

          {/* Buyer Selector & Simulation Controls */}
          <div className="flex items-center gap-2">
            <select
              value={selectedBuyer}
              onChange={(e) => setSelectedBuyer(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800/80 px-2.5 py-1 text-xs text-slate-200 font-mono focus:border-sky-500 focus:outline-none"
            >
              <option value="CORP-INFOSYS">CORP-INFOSYS ($150M Facility)</option>
              <option value="CORP-RELIANCE">CORP-RELIANCE ($250M Facility)</option>
              <option value="CORP-TATA">CORP-TATA ($200M Facility)</option>
              <option value="CORP-MAHINDRA">CORP-MAHINDRA ($100M Facility)</option>
            </select>

            <button
              onClick={() => setSimulateAmount((prev) => (prev > 0 ? 0 : 350_000))}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                simulateAmount > 0
                  ? "border-emerald-500/50 bg-emerald-950/40 text-emerald-300"
                  : "border-slate-700 bg-slate-800/60 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {simulateAmount > 0 ? "✓ Simulating -$350K Advance" : "+ Overlay -$350K Advance"}
            </button>
          </div>
        </div>

        {/* Headroom Telemetry Stats */}
        {data && (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4 font-mono text-xs">
            <div className="rounded border border-slate-800 bg-[#090e1a] p-2">
              <span className="text-[10px] text-slate-400 uppercase">Current Balance</span>
              <div className="font-bold text-white">{formatCompactCurrency(data.current_cash_balance)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#090e1a] p-2">
              <span className="text-[10px] text-slate-400 uppercase">Min Cash Floor</span>
              <div className="font-bold text-rose-400">{formatCompactCurrency(data.min_cash_floor)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#090e1a] p-2">
              <span className="text-[10px] text-slate-400 uppercase">Facility Limit</span>
              <div className="font-bold text-sky-400">{formatCompactCurrency(data.facility_limit)}</div>
            </div>
            <div className="rounded border border-slate-800 bg-[#090e1a] p-2">
              <span className="text-[10px] text-slate-400 uppercase">Undrawn Headroom</span>
              <div className="font-bold text-emerald-400">{formatCompactCurrency(data.undrawn_headroom)}</div>
            </div>
          </div>
        )}
      </div>

      {/* Chart Canvas */}
      <div className="p-4">
        <div className="h-64 w-full">
          {isLoading && curvePoints.length === 0 ? (
            <div className="flex h-full items-center justify-center text-xs text-slate-500">
              Loading cash telemetry curve...
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={curvePoints} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="cashGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0284c7" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#0284c7" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="simulatedGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="day"
                  stroke="#64748b"
                  fontSize={10}
                  tickLine={false}
                  tickFormatter={(d) => `D+${d}`}
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={10}
                  tickLine={false}
                  tickFormatter={(v) => formatCompactCurrency(v)}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const pt = payload[0].payload as CashCurvePoint;
                      return (
                        <div className="rounded-lg border border-slate-700 bg-[#0b101c] p-2.5 font-mono text-[11px] text-white shadow-xl">
                          <div className="font-bold text-slate-300">
                            Day {pt.day} ({pt.date})
                          </div>
                          <div className="text-sky-400">Projected: {formatCurrency(pt.projected_cash)}</div>
                          {simulateAmount > 0 && (
                            <div className="text-emerald-400">Post-Advance: {formatCurrency(pt.simulated_cash)}</div>
                          )}
                          <div className="text-rose-400">Floor: {formatCurrency(pt.min_floor)}</div>
                          <div className="text-slate-400">Headroom: {formatCurrency(pt.facility_headroom)}</div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                {/* 10M Minimum Floor Reference Line */}
                <ReferenceLine
                  y={10_000_000}
                  stroke="#f43f5e"
                  strokeDasharray="4 4"
                  label={{
                    value: "MIN CASH FLOOR ($10M)",
                    fill: "#f43f5e",
                    fontSize: 9,
                    position: "insideTopLeft",
                  }}
                />
                {/* Baseline Projected Cash Area */}
                <Area
                  type="monotone"
                  dataKey="projected_cash"
                  stroke="#0284c7"
                  strokeWidth={2}
                  fillOpacity={1}
                  fill="url(#cashGradient)"
                  name="Baseline Cash"
                />
                {/* Simulated Cash Post-Advance Area */}
                {simulateAmount > 0 && (
                  <Area
                    type="monotone"
                    dataKey="simulated_cash"
                    stroke="#10b981"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    fillOpacity={1}
                    fill="url(#simulatedGradient)"
                    name="Simulated Post-Advance"
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}

