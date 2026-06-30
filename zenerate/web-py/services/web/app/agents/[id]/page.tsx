"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher, apiFetch } from "@/lib/api";
import { Loader2, ChevronLeft, Play, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { RunsTable } from "@/components/runs-table";
import { NewRunModal } from "@/components/new-run-modal";
import type { Agent, TestRun, Scenario, PaginatedResponse } from "@/lib/types";
import { fmtDate } from "@/lib/time";

interface Props { params: { id: string } }

export default function AgentDetailPage({ params }: Props) {
  const { data: agent, isLoading, mutate: mutateAgent } = useSWR<Agent>(`/api/v1/agents/${params.id}/`, swrFetcher);
  const { data: runsData, mutate: mutateRuns } = useSWR<PaginatedResponse<TestRun> | TestRun[]>(
    `/api/v1/agents/${params.id}/test-runs/`, swrFetcher, { refreshInterval: 5000 }
  );
  const { data: scenData } = useSWR<PaginatedResponse<Scenario> | Scenario[]>("/api/v1/scenarios/", swrFetcher);
  const [showModal, setShowModal] = useState(false);
  const [dynVars, setDynVars] = useState<{ k: string; v: string }[] | null>(null);
  const [savingVars, setSavingVars] = useState(false);

  const runs: TestRun[] = Array.isArray(runsData) ? runsData : (runsData?.results ?? []);
  const scenarios: Scenario[] = Array.isArray(scenData) ? scenData : (scenData?.results ?? []);

  const editedVars = dynVars ?? Object.entries(agent?.dynamic_variables ?? {}).map(([k, v]) => ({ k, v: String(v) }));

  async function saveDynVars() {
    if (!agent) return;
    setSavingVars(true);
    try {
      const obj = Object.fromEntries(editedVars.filter(({ k }) => k.trim()).map(({ k, v }) => [k.trim(), v]));
      await apiFetch(`/api/v1/agents/${agent.id}/`, { method: "PATCH", body: JSON.stringify({ dynamic_variables: obj }) });
      setDynVars(null);
      mutateAgent();
    } finally {
      setSavingVars(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
      </div>
    );
  }

  if (!agent) {
    return <div className="p-8 text-sm" style={{ color: "var(--ink-2)" }}>Agent not found.</div>;
  }

  return (
    <div className="p-8 max-w-5xl">
      {/* Back */}
      <Link
        href="/agents"
        className="inline-flex items-center gap-1 text-sm mb-6"
        style={{ color: "var(--ink-3)" }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.color = "var(--blue)")}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.color = "var(--ink-3)")}
      >
        <ChevronLeft size={14} />
        Agents
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>{agent.name}</h1>
          <p className="text-xs font-mono mt-1" style={{ color: "var(--ink-3)" }}>{agent.id}</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
          style={{ background: "var(--blue)" }}
        >
          <Play size={13} />
          Run Test
        </button>
      </div>

      {/* Details card */}
      <div
        className="rounded-xl p-5 mb-5 space-y-4"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
      >
        {agent.system_prompt && (
          <div>
            <p className="text-xs font-medium mb-1.5" style={{ color: "var(--ink-3)" }}>System Prompt</p>
            <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--ink-2)", lineHeight: "1.7" }}>
              {agent.system_prompt}
            </p>
          </div>
        )}
        <div
          className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4"
          style={{ borderTop: agent.system_prompt ? "1px solid var(--border)" : "none" }}
        >
          {agent.greeting && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: "var(--ink-3)" }}>Greeting</p>
              <p className="text-sm" style={{ color: "var(--ink-2)" }}>{agent.greeting}</p>
            </div>
          )}
          {agent.voice_id && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: "var(--ink-3)" }}>Voice ID</p>
              <p className="text-sm font-mono" style={{ color: "var(--ink-2)" }}>{agent.voice_id}</p>
            </div>
          )}
          {agent.el_agent_id && (
            <div>
              <p className="text-xs font-medium mb-1" style={{ color: "var(--ink-3)" }}>ElevenLabs Agent</p>
              <p className="text-sm font-mono truncate" style={{ color: "var(--ink-2)" }}>{agent.el_agent_id}</p>
            </div>
          )}
          <div>
            <p className="text-xs font-medium mb-1" style={{ color: "var(--ink-3)" }}>Created</p>
            <p className="text-sm" style={{ color: "var(--ink-2)" }}>{fmtDate(agent.created_at)}</p>
          </div>
          <div>
            <p className="text-xs font-medium mb-1" style={{ color: "var(--ink-3)" }}>Updated</p>
            <p className="text-sm" style={{ color: "var(--ink-2)" }}>{fmtDate(agent.updated_at)}</p>
          </div>
        </div>
      </div>

      {/* Dynamic variables */}
      <div
        className="rounded-xl p-5 mb-5"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
      >
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="font-semibold text-base" style={{ color: "var(--ink)" }}>Dynamic Variables</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
              Variables injected into the ElevenLabs conversation (e.g. <code>company_name</code>).
            </p>
          </div>
        </div>

        <div className="space-y-2">
          {editedVars.map((row, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                className="flex-1 rounded-lg px-3 py-1.5 text-sm font-mono"
                style={{ border: "1px solid var(--border-strong)", background: "var(--bg)", color: "var(--ink)" }}
                placeholder="key"
                value={row.k}
                onChange={(e) => {
                  const next = [...editedVars]; next[i] = { ...row, k: e.target.value }; setDynVars(next);
                }}
              />
              <input
                className="flex-1 rounded-lg px-3 py-1.5 text-sm"
                style={{ border: "1px solid var(--border-strong)", background: "var(--bg)", color: "var(--ink)" }}
                placeholder="value"
                value={row.v}
                onChange={(e) => {
                  const next = [...editedVars]; next[i] = { ...row, v: e.target.value }; setDynVars(next);
                }}
              />
              <button
                onClick={() => setDynVars(editedVars.filter((_, j) => j !== i))}
                style={{ color: "var(--ink-3)" }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-2 mt-3">
          <button
            onClick={() => setDynVars([...editedVars, { k: "", v: "" }])}
            className="flex items-center gap-1 text-xs"
            style={{ color: "var(--blue)" }}
          >
            <Plus size={12} /> Add variable
          </button>
          {dynVars !== null && (
            <button
              onClick={saveDynVars}
              disabled={savingVars}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold text-white"
              style={{ background: "var(--blue)", opacity: savingVars ? 0.6 : 1, marginLeft: "auto" }}
            >
              {savingVars ? <Loader2 size={11} className="spin" /> : null}
              Save
            </button>
          )}
        </div>
      </div>

      {/* Runs */}
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
      >
        <h2 className="font-semibold text-base mb-4" style={{ color: "var(--ink)" }}>Test Runs</h2>
        <RunsTable runs={runs} />
      </div>

      {showModal && (
        <NewRunModal
          agents={[agent]}
          scenarios={scenarios}
          defaultAgentId={agent.id}
          onClose={() => { setShowModal(false); mutateRuns(); }}
        />
      )}
    </div>
  );
}
