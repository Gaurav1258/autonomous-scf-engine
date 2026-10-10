"use client";

import React, { useEffect, useRef, useState } from "react";
import { scfApi } from "@/lib/api-client";
import { SSEAgentStepPayload, WorkflowStatus } from "@/types";

interface AgentTelemetryProps {
  invoiceId: string | null;
  onWorkflowComplete?: () => void;
}

interface AgentNodeState {
  id: string;
  name: string;
  role: string;
  status: "idle" | "running" | "completed" | "halted";
  summary?: string;
}

const INITIAL_NODES: AgentNodeState[] = [
  { id: "cash_forecaster", name: "1. Cash Forecaster", role: "60-Day Liquidity & Floor", status: "idle" },
  { id: "risk_sentinel", name: "2. Risk Sentinel", role: "RapidFuzz & OFAC Sanctions", status: "idle" },
  { id: "capital_structurer", name: "3. Deal Structurer", role: "XGBoost Elasticity & Math", status: "idle" },
  { id: "guardrail_validator", name: "4. Guardrail Validator", role: "Credit Limits & Concentration", status: "idle" },
  { id: "treasury_dispatcher", name: "5. Treasury Dispatcher", role: "1-Click Dual Term Sheet", status: "idle" },
];

export function AgentTelemetry({ invoiceId, onWorkflowComplete }: AgentTelemetryProps) {
  const [nodes, setNodes] = useState<AgentNodeState[]>(INITIAL_NODES);
  const [logs, setLogs] = useState<string[]>([]);
  const [streamStatus, setStreamStatus] = useState<"idle" | "streaming" | "completed" | "error">("idle");
  const eventSourceRef = useRef<EventSource | null>(null);
  const logsEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    if (!invoiceId) {
      setNodes(INITIAL_NODES);
      setLogs(["Telemetry standby. Select or simulate an invoice to start."]);
      setStreamStatus("idle");
      return;
    }

    // Reset nodes for new stream
    setNodes(INITIAL_NODES);
    setLogs([`Connecting to SSE telemetry stream for ${invoiceId}...`]);
    setStreamStatus("streaming");

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const streamUrl = scfApi.getStreamUrl(invoiceId);
    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    es.addEventListener("workflow_init", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setLogs((prev) => [...prev, `[INIT] ${data.message}`]);
        // Set first node to running
        setNodes((prev) =>
          prev.map((n, idx) => (idx === 0 ? { ...n, status: "running" } : n))
        );
      } catch (err) {
        console.error(err);
      }
    });

    es.addEventListener("agent_step", (e: MessageEvent) => {
      try {
        const data: SSEAgentStepPayload = JSON.parse(e.data);
        setLogs((prev) => [...prev, `[${data.node.toUpperCase()}] ${data.summary}`]);

        setNodes((prev) => {
          const currentIndex = prev.findIndex((n) => n.id === data.node);
          return prev.map((n, idx) => {
            if (idx === currentIndex) {
              return {
                ...n,
                status: data.status.startsWith("REJECTED") ? "halted" : "completed",
                summary: data.summary,
              };
            }
            if (idx === currentIndex + 1 && !data.status.startsWith("REJECTED")) {
              return { ...n, status: "running" };
            }
            return n;
          });
        });
      } catch (err) {
        console.error(err);
      }
    });

    es.addEventListener("workflow_complete", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setLogs((prev) => [
          ...prev,
          `>>> [DISPATCHED] Autonomous orchestration complete for ${data.invoice_id}. Offer ready.`,
        ]);
        setStreamStatus("completed");
        setNodes((prev) =>
          prev.map((n) => (n.status === "running" ? { ...n, status: "completed" } : n))
        );
        es.close();
        if (onWorkflowComplete) onWorkflowComplete();
      } catch (err) {
        console.error(err);
      }
    });

    es.addEventListener("workflow_halted", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        setLogs((prev) => [
          ...prev,
          `⛔ [HALTED] Execution halted on compliance/credit gate: ${data.final_status}`,
        ]);
        setStreamStatus("completed");
        es.close();
        if (onWorkflowComplete) onWorkflowComplete();
      } catch (err) {
        console.error(err);
      }
    });

    es.onerror = () => {
      setLogs((prev) => [...prev, "Connection to telemetry stream closed."]);
      setStreamStatus("completed");
      es.close();
    };

    return () => {
      es.close();
    };
  }, [invoiceId]);

  return (
    <div className="flex flex-col rounded-xl border border-slate-800/80 bg-[#0d1322] shadow-lg">
      {/* Header */}
      <div className="border-b border-slate-800/80 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-sky-400"></span>
            <h2 className="text-sm font-bold text-white">
              Multi-Agent Reasoning Telemetry
            </h2>
            {invoiceId && (
              <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
                {invoiceId}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-slate-400 font-mono">
              Mode: Server-Sent Events (SSE)
            </span>
          </div>
        </div>
      </div>

      {/* Visual Pipeline Nodes */}
      <div className="border-b border-slate-800/80 bg-[#090e1a] p-4">
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-5">
          {nodes.map((node) => {
            let statusBadge = (
              <span className="text-[10px] text-slate-500 font-mono">IDLE</span>
            );
            let borderStyle = "border-slate-800/80 bg-[#0e1424]";

            if (node.status === "running") {
              statusBadge = (
                <span className="flex items-center gap-1 font-mono text-[10px] text-sky-400">
                  <span className="h-1.5 w-1.5 animate-ping rounded-full bg-sky-400"></span>
                  ACTIVE
                </span>
              );
              borderStyle = "border-sky-500/50 bg-sky-950/20 ring-1 ring-sky-500/30";
            } else if (node.status === "completed") {
              statusBadge = (
                <span className="font-mono text-[10px] text-emerald-400">✓ PASS</span>
              );
              borderStyle = "border-emerald-500/30 bg-emerald-950/10";
            } else if (node.status === "halted") {
              statusBadge = (
                <span className="font-mono text-[10px] text-rose-400">✕ HALT</span>
              );
              borderStyle = "border-rose-500/50 bg-rose-950/20 ring-1 ring-rose-500/40";
            }

            return (
              <div
                key={node.id}
                className={`flex flex-col justify-between rounded-lg border p-3 transition-all ${borderStyle}`}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold text-white">{node.name}</span>
                    {statusBadge}
                  </div>
                  <p className="mt-1 text-[10px] text-slate-400 leading-tight">
                    {node.role}
                  </p>
                </div>
                {node.summary && (
                  <p className="mt-2 text-[10px] text-slate-300 font-mono line-clamp-2">
                    {node.summary}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Live Scrolling Terminal Logs */}
      <div className="p-4">
        <div className="flex items-center justify-between pb-2">
          <span className="text-xs font-semibold text-slate-400">Execution Audit Log</span>
          <span className="font-mono text-[10px] text-slate-500">Live Telemetry Feed</span>
        </div>
        <div className="h-40 overflow-y-auto rounded-lg border border-slate-800 bg-[#060a12] p-3 font-mono text-[11px] text-slate-300 shadow-inner">
          {logs.map((log, idx) => (
            <div key={idx} className="py-0.5 leading-relaxed">
              <span className="text-slate-600 mr-2">[{new Date().toISOString().substring(11, 19)}]</span>
              <span
                className={
                  log.includes("HALTED") || log.includes("CRITICAL")
                    ? "text-rose-400 font-semibold"
                    : log.includes("DISPATCHED") || log.includes("PASS")
                    ? "text-emerald-400 font-semibold"
                    : log.includes("INIT")
                    ? "text-sky-400"
                    : "text-slate-300"
                }
              >
                {log}
              </span>
            </div>
          ))}
          <div ref={logsEndRef} />
        </div>
      </div>
    </div>
  );
}

