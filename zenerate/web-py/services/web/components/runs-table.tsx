"use client";

import Link from "next/link";
import { StatusBadge } from "./status-badge";
import { CheckCircle2, XCircle, Loader2, ArrowRight, Mic, MessageSquare } from "lucide-react";
import type { TestRun } from "@/lib/types";
import { formatDistanceToNow } from "@/lib/time";

function parseError(raw: string): string {
  const body = raw.replace(/^\d{3}:\s*/, "");
  try {
    const parsed = JSON.parse(body);
    return parsed.error ?? parsed.detail ?? parsed.message ?? body;
  } catch {
    return body;
  }
}

interface Props {
  runs: TestRun[];
  showAgent?: boolean;
}

export function RunsTable({ runs, showAgent }: Props) {
  if (runs.length === 0) {
    return (
      <div className="py-16 text-center text-sm" style={{ color: "var(--ink-3)" }}>
        No runs yet.{" "}
        <span style={{ color: "var(--blue)" }}>Click Run Test to get started.</span>
      </div>
    );
  }

  const thStyle: React.CSSProperties = {
    color: "var(--ink-3)",
    fontSize: "11px",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    paddingBottom: "10px",
    paddingRight: "20px",
    textAlign: "left",
    whiteSpace: "nowrap",
    borderBottom: "1px solid var(--border)",
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr>
            {["Run", showAgent && "Agent", "Scenario", "Mode", "Status", "Result", "Scores", ""].filter(Boolean).map((h) => (
              <th key={String(h)} style={thStyle}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run, idx) => {
            const result = run.result;
            const scores = result?.scores ?? [];
            const nPass = scores.filter((s) => s.passed).length;
            const judging = run.status === "completed" && result && scores.length === 0;
            const last = idx === runs.length - 1;

            return (
              <tr
                key={run.id}
                className="group"
                style={{ borderBottom: last ? "none" : "1px solid var(--border)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <td className="py-3 pr-5">
                  <span className="font-mono text-xs" style={{ color: "var(--ink-3)" }}>
                    {run.id.slice(0, 8)}
                  </span>
                </td>

                {showAgent && (
                  <td className="py-3 pr-5">
                    <span className="text-sm" style={{ color: "var(--ink-2)" }}>
                      {run.agent_name ?? run.agent.slice(0, 8)}
                    </span>
                  </td>
                )}

                <td className="py-3 pr-5">
                  <span className="font-medium text-sm" style={{ color: "var(--ink)" }}>
                    {run.scenario_name}
                  </span>
                </td>

                <td className="py-3 pr-5">
                  <span
                    className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded"
                    style={{
                      color: run.mode === "audio" ? "#7c3aed" : "#0369a1",
                      background: run.mode === "audio" ? "#f5f3ff" : "#f0f9ff",
                    }}
                  >
                    {run.mode === "audio" ? <Mic size={10} /> : <MessageSquare size={10} />}
                    {run.mode}
                  </span>
                </td>

                <td className="py-3 pr-5">
                  <StatusBadge status={run.status} />
                  {run.status === "failed" && run.error_message && (
                    <p
                      className="text-xs mt-1 max-w-[200px] truncate"
                      style={{ color: "var(--red)", opacity: 0.8 }}
                      title={parseError(run.error_message)}
                    >
                      {parseError(run.error_message)}
                    </p>
                  )}
                </td>

                <td className="py-3 pr-5">
                  {result ? (
                    result.passed
                      ? <CheckCircle2 size={15} style={{ color: "var(--green)" }} />
                      : <XCircle size={15} style={{ color: "var(--red)" }} />
                  ) : (
                    <span style={{ color: "var(--ink-3)" }}>—</span>
                  )}
                </td>

                <td className="py-3 pr-5">
                  {judging ? (
                    <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: "var(--amber)" }}>
                      <Loader2 size={10} className="spin" />
                      Judging
                    </span>
                  ) : scores.length > 0 ? (
                    <span className="font-mono text-xs">
                      <span style={{ color: "var(--green)", fontWeight: 600 }}>{nPass}</span>
                      <span style={{ color: "var(--ink-3)" }}>/{scores.length}</span>
                    </span>
                  ) : (
                    <span style={{ color: "var(--ink-3)" }}>—</span>
                  )}
                </td>

                <td className="py-3">
                  <Link
                    href={`/tests/${run.id}`}
                    className="inline-flex items-center gap-1 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ color: "var(--blue)" }}
                  >
                    View <ArrowRight size={12} />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
