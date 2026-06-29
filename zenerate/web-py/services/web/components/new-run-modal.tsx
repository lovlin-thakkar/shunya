"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { X, Play, Loader2, Mic, MessageSquare } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Agent, Scenario, TestRun } from "@/lib/types";

interface Props {
  agents: Agent[];
  scenarios: Scenario[];
  defaultAgentId?: string;
  onClose: () => void;
}

export function NewRunModal({ agents, scenarios, defaultAgentId, onClose }: Props) {
  const router = useRouter();
  const [agentId, setAgentId] = useState(defaultAgentId ?? agents[0]?.id ?? "");
  const [mode, setMode] = useState<"text" | "audio">("text");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectedAgent = agents.find((a) => a.id === agentId);

  const compatibleScenarios = useMemo(() => {
    if (!selectedAgent) return scenarios;
    return scenarios.filter((s) => {
      if (!s.compatible_agents || s.compatible_agents.length === 0) return true;
      return s.compatible_agents.includes(selectedAgent.id) || s.compatible_agents.includes(selectedAgent.name);
    });
  }, [scenarios, selectedAgent]);

  const [scenarioName, setScenarioName] = useState(() => compatibleScenarios[0]?.name ?? "");

  function handleAgentChange(newId: string) {
    setAgentId(newId);
    const agent = agents.find((a) => a.id === newId);
    if (!agent) return;
    const filtered = scenarios.filter((s) => {
      if (!s.compatible_agents || s.compatible_agents.length === 0) return true;
      return s.compatible_agents.includes(agent.id) || s.compatible_agents.includes(agent.name);
    });
    setScenarioName(filtered[0]?.name ?? "");
  }

  async function submit() {
    if (!agentId || !scenarioName) { setError("Select an agent and scenario"); return; }
    setLoading(true);
    setError("");
    try {
      const run = await apiFetch<TestRun>("/api/v1/test-runs/", {
        method: "POST",
        body: JSON.stringify({ agent: agentId, scenario: scenarioName, mode }),
      });
      router.push(`/tests/${run.id}`);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start run");
    } finally {
      setLoading(false);
    }
  }

  const selectStyle: React.CSSProperties = {
    background: "var(--bg)",
    border: "1px solid var(--border-strong)",
    color: "var(--ink)",
    borderRadius: "8px",
    padding: "8px 12px",
    width: "100%",
    fontSize: "14px",
    outline: "none",
    cursor: "pointer",
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.35)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-md rounded-2xl overflow-hidden fade-in"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.15), 0 0 0 1px rgba(0,0,0,0.05)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="font-semibold text-[15px]" style={{ color: "var(--ink)" }}>
            New Test Run
          </h2>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center transition-colors"
            style={{ color: "var(--ink-3)" }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = "var(--bg)";
              (e.currentTarget as HTMLElement).style.color = "var(--ink)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.background = "transparent";
              (e.currentTarget as HTMLElement).style.color = "var(--ink-3)";
            }}
          >
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-5 space-y-4">
          {/* Agent */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-2)" }}>
              Agent
            </label>
            <select value={agentId} onChange={(e) => handleAgentChange(e.target.value)} style={selectStyle}>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </div>

          {/* Scenario */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium" style={{ color: "var(--ink-2)" }}>
                Scenario
              </label>
              {compatibleScenarios.length < scenarios.length && (
                <span className="text-xs" style={{ color: "var(--ink-3)" }}>
                  {compatibleScenarios.length} of {scenarios.length} compatible
                </span>
              )}
            </div>
            {compatibleScenarios.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--red)" }}>
                No scenarios are compatible with this agent.
              </p>
            ) : (
              <select value={scenarioName} onChange={(e) => setScenarioName(e.target.value)} style={selectStyle}>
                {compatibleScenarios.map((s) => <option key={s.id} value={s.name}>{s.name}</option>)}
              </select>
            )}
          </div>

          {/* Mode */}
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-2)" }}>
              Mode
            </label>
            <div className="flex gap-2">
              {(["text", "audio"] as const).map((m) => {
                const active = mode === m;
                return (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-sm font-medium"
                    style={{
                      border: `1px solid ${active ? "var(--blue)" : "var(--border-strong)"}`,
                      background: active ? "var(--blue-bg)" : "transparent",
                      color: active ? "var(--blue)" : "var(--ink-2)",
                    }}
                  >
                    {m === "audio" ? <Mic size={13} /> : <MessageSquare size={13} />}
                    {m === "text" ? "Text" : "Audio"}
                  </button>
                );
              })}
            </div>
          </div>

          {error && (
            <p className="text-xs" style={{ color: "var(--red)" }}>{error}</p>
          )}
        </div>

        {/* Footer */}
        <div
          className="px-5 pb-5 pt-1"
        >
          <button
            onClick={submit}
            disabled={loading || compatibleScenarios.length === 0}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold text-white"
            style={{
              background: "var(--blue)",
              opacity: loading || compatibleScenarios.length === 0 ? 0.5 : 1,
            }}
          >
            {loading ? <Loader2 size={14} className="spin" /> : <Play size={13} />}
            {loading ? "Starting…" : "Run Test"}
          </button>
        </div>
      </div>
    </div>
  );
}
