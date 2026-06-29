"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher, apiFetch } from "@/lib/api";
import { Play, PlayCircle, Trash2, Loader2, ChevronDown } from "lucide-react";
import { RunsTable } from "@/components/runs-table";
import { NewRunModal } from "@/components/new-run-modal";
import type { Agent, Scenario, TestRun, PaginatedResponse } from "@/lib/types";

// ── Run All modal ──────────────────────────────────────────────────────────────

function RunAllModal({
  agents,
  onClose,
}: {
  agents: Agent[];
  onClose: () => void;
}) {
  const [agentId, setAgentId] = useState(agents[0]?.id ?? "");
  const [mode, setMode] = useState<"text" | "audio">("text");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!agentId) { setError("Select an agent"); return; }
    setLoading(true);
    setError("");
    try {
      await apiFetch(`/api/v1/agents/${agentId}/run-evals/`, {
        method: "POST",
        body: JSON.stringify({ mode }),
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start runs");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.35)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-sm rounded-2xl overflow-hidden fade-in"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
        }}
      >
        <div className="px-5 pt-5 pb-4" style={{ borderBottom: "1px solid var(--border)" }}>
          <h2 className="font-semibold text-[15px]" style={{ color: "var(--ink)" }}>Run All Scenarios</h2>
          <p className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
            Dispatches every scenario against the selected agent in parallel
          </p>
        </div>

        <form onSubmit={submit} className="p-5 space-y-4">
          {/* Agent */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-3)" }}>Agent</label>
            <div className="relative">
              <select
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg text-sm appearance-none outline-none pr-8"
                style={{ background: "var(--bg)", border: "1px solid var(--border-strong)", color: "var(--ink)" }}
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: "var(--ink-3)" }} />
            </div>
          </div>

          {/* Mode */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-3)" }}>Mode</label>
            <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-strong)" }}>
              {(["text", "audio"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className="flex-1 py-2 text-sm font-medium capitalize"
                  style={{
                    background: mode === m ? "var(--blue)" : "var(--bg)",
                    color: mode === m ? "white" : "var(--ink-2)",
                  }}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p className="text-xs px-2.5 py-1.5 rounded-lg" style={{ background: "var(--red-bg)", color: "var(--red)" }}>{error}</p>
          )}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2.5 rounded-lg text-sm font-medium"
              style={{ background: "var(--bg)", color: "var(--ink-2)", border: "1px solid var(--border-strong)" }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !agentId}
              className="flex-1 py-2.5 rounded-lg text-sm font-semibold text-white flex items-center justify-center gap-2"
              style={{ background: "var(--blue)", opacity: loading ? 0.7 : 1 }}
            >
              {loading ? <Loader2 size={13} className="spin" /> : <PlayCircle size={13} />}
              {loading ? "Starting…" : "Run All"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function TestsPage() {
  const { data: runsData, isLoading, mutate } = useSWR<PaginatedResponse<TestRun> | TestRun[]>(
    "/api/v1/test-runs/",
    swrFetcher,
    {
      refreshInterval: (data) => {
        const runs = Array.isArray(data) ? data : (data?.results ?? []);
        return runs.some((r) => r.status === "queued" || r.status === "running") ? 3000 : 10000;
      },
    }
  );
  const { data: agentsData } = useSWR<PaginatedResponse<Agent> | Agent[]>("/api/v1/agents/", swrFetcher);
  const { data: scenData } = useSWR<PaginatedResponse<Scenario> | Scenario[]>("/api/v1/scenarios/", swrFetcher);

  const [showRunModal, setShowRunModal] = useState(false);
  const [showRunAll, setShowRunAll] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const runs: TestRun[] = Array.isArray(runsData) ? runsData : (runsData?.results ?? []);
  const agents: Agent[] = Array.isArray(agentsData) ? agentsData : (agentsData?.results ?? []);
  const scenarios: Scenario[] = Array.isArray(scenData) ? scenData : (scenData?.results ?? []);

  const active = runs.filter((r) => r.status === "queued" || r.status === "running").length;

  async function handleClear() {
    if (!confirmClear) { setConfirmClear(true); return; }
    setClearing(true);
    try {
      await apiFetch("/api/v1/test-runs/clear/", { method: "DELETE" });
      await mutate();
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  }

  return (
    <div className="p-8 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>Test Runs</h1>
          <div className="flex items-center gap-3 mt-0.5">
            <p className="text-sm" style={{ color: "var(--ink-3)" }}>
              {runs.length} run{runs.length !== 1 ? "s" : ""} total
            </p>
            {active > 0 && (
              <span className="inline-flex items-center gap-1.5 text-xs" style={{ color: "var(--blue)" }}>
                <Loader2 size={11} className="spin" />
                {active} running
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {runs.length > 0 && (
            <button
              onClick={handleClear}
              disabled={clearing}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium"
              style={{
                border: `1px solid ${confirmClear ? "var(--red)" : "var(--border-strong)"}`,
                color: confirmClear ? "var(--red)" : "var(--ink-3)",
                background: confirmClear ? "var(--red-bg)" : "transparent",
              }}
              onMouseLeave={() => setConfirmClear(false)}
            >
              {clearing ? <Loader2 size={12} className="spin" /> : <Trash2 size={12} />}
              {confirmClear ? "Confirm clear?" : "Clear All"}
            </button>
          )}

          <button
            onClick={() => setShowRunAll(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium"
            style={{ border: "1px solid var(--border-strong)", color: "var(--ink-2)" }}
          >
            <PlayCircle size={13} />
            Run All
          </button>

          <button
            onClick={() => setShowRunModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ background: "var(--blue)" }}
          >
            <Play size={13} />
            Run Test
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
        </div>
      ) : (
        <div
          className="rounded-xl p-5"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
        >
          <RunsTable runs={runs} showAgent />
        </div>
      )}

      {showRunModal && (
        <NewRunModal
          agents={agents}
          scenarios={scenarios}
          onClose={() => { setShowRunModal(false); mutate(); }}
        />
      )}

      {showRunAll && (
        <RunAllModal
          agents={agents}
          onClose={() => { setShowRunAll(false); mutate(); }}
        />
      )}
    </div>
  );
}
