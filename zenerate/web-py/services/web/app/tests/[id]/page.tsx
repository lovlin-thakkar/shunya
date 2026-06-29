"use client";

import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { Loader2, ChevronLeft, CheckCircle2, XCircle, ExternalLink, Mic, MessageSquare } from "lucide-react";
import Link from "next/link";
import { StatusBadge } from "@/components/status-badge";
import { ScoreBar } from "@/components/score-bar";
import { Transcript } from "@/components/transcript";
import type { TestRun } from "@/lib/types";
import { fmtDate } from "@/lib/time";

interface Props { params: { id: string } }

export default function TestRunPage({ params }: Props) {
  const { data: run, isLoading } = useSWR<TestRun>(
    `/api/v1/test-runs/${params.id}/`,
    swrFetcher,
    {
      refreshInterval: (run) => {
        if (!run) return 3000;
        if (run.status === "queued" || run.status === "running") return 2000;
        const judging = run.status === "completed" && run.result && (run.result.scores?.length ?? 0) === 0;
        return judging ? 4000 : 0;
      },
    }
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
      </div>
    );
  }

  if (!run) {
    return <div className="p-8 text-sm" style={{ color: "var(--ink-2)" }}>Test run not found.</div>;
  }

  const result = run.result;
  const scores = result?.scores ?? [];
  const judging = run.status === "completed" && result && scores.length === 0;
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

  return (
    <div className="p-8 max-w-5xl">
      {/* Back */}
      <Link
        href="/tests"
        className="inline-flex items-center gap-1 text-sm mb-6"
        style={{ color: "var(--ink-3)" }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.color = "var(--blue)")}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.color = "var(--ink-3)")}
      >
        <ChevronLeft size={14} />
        Test Runs
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <StatusBadge status={run.status} />

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

            {result && (
              <span
                className="inline-flex items-center gap-1 text-xs font-semibold"
                style={{ color: result.passed ? "var(--green)" : "var(--red)" }}
              >
                {result.passed ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                {result.passed ? "Passed" : "Failed"}
              </span>
            )}
          </div>

          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>{run.scenario_name}</h1>
          <p className="font-mono text-xs mt-1" style={{ color: "var(--ink-3)" }}>{run.id}</p>
        </div>

        {run.observer_url && (
          <a
            href={run.observer_url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium"
            style={{
              border: "1px solid var(--blue-bd)",
              color: "var(--blue)",
              background: "var(--blue-bg)",
            }}
          >
            <ExternalLink size={13} />
            Listen Live
          </a>
        )}
      </div>

      {/* Meta bar */}
      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 rounded-xl p-4"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 2px rgba(0,0,0,0.03)" }}
      >
        {[
          { label: "Agent", value: run.agent_name ?? run.agent.slice(0, 8) + "…" },
          { label: "Scenario", value: run.scenario_name },
          { label: "Started", value: fmtDate(run.started_at) },
          { label: "Completed", value: fmtDate(run.completed_at) },
        ].map(({ label, value }) => (
          <div key={label}>
            <p className="text-xs font-medium mb-0.5" style={{ color: "var(--ink-3)" }}>{label}</p>
            <p className="text-sm truncate" style={{ color: "var(--ink-2)" }}>{value || "—"}</p>
          </div>
        ))}
      </div>

      {/* Two-column */}
      <div className="grid gap-4 lg:grid-cols-5">
        {/* Transcript */}
        <div
          className="lg:col-span-3 rounded-xl p-5"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
        >
          <h2 className="font-semibold text-base mb-4" style={{ color: "var(--ink)" }}>Transcript</h2>
          {run.status === "queued" || run.status === "running" ? (
            <div className="py-10 text-center">
              <Loader2 size={18} className="spin mx-auto mb-2" style={{ color: "var(--ink-3)" }} />
              <p className="text-sm" style={{ color: "var(--ink-3)" }}>
                {run.status === "queued" ? "Waiting to start…" : "Call in progress…"}
              </p>
            </div>
          ) : (
            <Transcript
              turns={result?.transcript ?? []}
              audioRunId={run.mode === "audio" ? run.id : undefined}
              apiUrl={apiUrl}
            />
          )}
        </div>

        {/* Scores */}
        <div
          className="lg:col-span-2 rounded-xl p-5"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
        >
          <h2 className="font-semibold text-base mb-4" style={{ color: "var(--ink)" }}>Judge Scores</h2>

          {run.status === "queued" || run.status === "running" ? (
            <p className="text-sm" style={{ color: "var(--ink-3)" }}>Available after completion.</p>
          ) : judging ? (
            <div className="flex items-center gap-2 text-sm" style={{ color: "var(--amber)" }}>
              <Loader2 size={13} className="spin" />
              Scoring with Claude Sonnet…
            </div>
          ) : scores.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--ink-3)" }}>No judge scores available.</p>
          ) : (
            <div>
              <div className="space-y-5">
                {scores.map((s) => (
                  <ScoreBar key={s.id} field={s.field} score={s.score} passed={s.passed} reasoning={s.reasoning} />
                ))}
              </div>
              <div
                className="mt-4 pt-4 flex items-center justify-between"
                style={{ borderTop: "1px solid var(--border)" }}
              >
                <span className="text-xs font-medium" style={{ color: "var(--ink-3)" }}>Overall</span>
                <span
                  className="text-sm font-semibold"
                  style={{ color: result?.passed ? "var(--green)" : "var(--red)" }}
                >
                  {scores.filter((s) => s.passed).length}/{scores.length} passed
                </span>
              </div>
            </div>
          )}

          {result?.assertion_results && Object.keys(result.assertion_results).length > 0 && (
            <div className="mt-5 pt-5" style={{ borderTop: "1px solid var(--border)" }}>
              <h3 className="text-xs font-medium mb-3" style={{ color: "var(--ink-3)" }}>Assertions</h3>
              <div className="space-y-2">
                {Object.entries(result.assertion_results).map(([name, passed]) => (
                  <div key={name} className="flex items-center gap-2">
                    {passed
                      ? <CheckCircle2 size={13} style={{ color: "var(--green)", flexShrink: 0 }} />
                      : <XCircle size={13} style={{ color: "var(--red)", flexShrink: 0 }} />
                    }
                    <span className="text-sm font-mono" style={{ color: "var(--ink-2)", fontSize: "12px" }}>{name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
