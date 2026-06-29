"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher } from "@/lib/api";
import { ListChecks, Loader2, ChevronDown, ChevronUp, Plus } from "lucide-react";
import type { Scenario, PaginatedResponse } from "@/lib/types";
import { NewScenarioModal } from "@/components/new-scenario-modal";

function ScenarioRow({ scenario, last }: { scenario: Scenario; last: boolean }) {
  const [open, setOpen] = useState(false);
  const stepCount = Array.isArray(scenario.steps) ? scenario.steps.length : 0;
  const rubricKeys = Object.keys(scenario.rubric ?? {});

  return (
    <div style={{ borderBottom: last ? "none" : "1px solid var(--border)" }}>
      <button
        className="w-full text-left px-5 py-4 flex items-center gap-4"
        onClick={() => setOpen(!open)}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "var(--bg)")}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
        style={{ transition: "background 0.1s" }}
      >
        <div className="min-w-0 flex-1">
          <p className="font-medium text-sm" style={{ color: "var(--ink)" }}>{scenario.name}</p>
          {scenario.persona && (
            <p className="text-xs mt-0.5 truncate" style={{ color: "var(--ink-3)", maxWidth: "500px" }}>
              {scenario.persona}
            </p>
          )}
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            {stepCount > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--bg)", color: "var(--ink-3)", border: "1px solid var(--border)" }}>
                {stepCount} steps
              </span>
            )}
            {scenario.assertions?.length > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--bg)", color: "var(--ink-3)", border: "1px solid var(--border)" }}>
                {scenario.assertions.length} assertions
              </span>
            )}
            {rubricKeys.map((k) => (
              <span key={k} className="text-xs px-1.5 py-0.5 rounded" style={{ background: "var(--blue-bg)", color: "var(--blue)" }}>
                {k}
              </span>
            ))}
          </div>
        </div>
        <span style={{ color: "var(--ink-3)", flexShrink: 0 }}>
          {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>

      {open && (
        <div
          className="px-5 pb-5 space-y-4"
          style={{ borderTop: "1px solid var(--border)", background: "var(--bg)" }}
        >
          {scenario.persona && (
            <div className="pt-4">
              <p className="text-xs font-medium mb-1.5" style={{ color: "var(--ink-3)" }}>Persona</p>
              <p className="text-sm leading-relaxed" style={{ color: "var(--ink-2)" }}>{scenario.persona}</p>
            </div>
          )}

          {stepCount > 0 && (
            <div>
              <p className="text-xs font-medium mb-2" style={{ color: "var(--ink-3)" }}>Steps</p>
              <ol className="space-y-2">
                {scenario.steps.map((step, i) => (
                  <li key={i} className="flex gap-3 text-sm">
                    <span className="flex-shrink-0 font-mono w-5 text-right pt-px" style={{ color: "var(--ink-3)", fontSize: "11px" }}>
                      {i + 1}
                    </span>
                    <span style={{ color: "var(--ink-2)", lineHeight: "1.6" }}>
                      {step.quirks?.map((q, qi) => (
                        <span
                          key={qi}
                          className="inline-block font-mono mr-1 rounded px-1"
                          style={{
                            background: "var(--amber-bg)",
                            color: "var(--amber)",
                            fontSize: "10px",
                            border: "1px solid rgba(217,119,6,0.15)",
                          }}
                        >
                          [{q.value ? `${q.tag}:${q.value}` : q.tag}]
                        </span>
                      ))}
                      {step.text || step.raw}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {scenario.assertions?.length > 0 && (
            <div>
              <p className="text-xs font-medium mb-2" style={{ color: "var(--ink-3)" }}>Assertions</p>
              <div className="flex flex-wrap gap-1.5">
                {scenario.assertions.map((a, i) => (
                  <span
                    key={i}
                    className="font-mono text-xs px-2 py-1 rounded"
                    style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink-2)" }}
                  >
                    {a}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ScenariosPage() {
  const { data, isLoading, mutate } = useSWR<PaginatedResponse<Scenario> | Scenario[]>("/api/v1/scenarios/", swrFetcher);
  const [showModal, setShowModal] = useState(false);
  const scenarios: Scenario[] = Array.isArray(data) ? data : (data?.results ?? []);

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>Scenarios</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
            {scenarios.length} scenario{scenarios.length !== 1 ? "s" : ""} — click to expand
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
          style={{ background: "var(--blue)" }}
        >
          <Plus size={14} />
          New Scenario
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
        </div>
      ) : scenarios.length === 0 ? (
        <div className="text-center py-20">
          <ListChecks size={32} className="mx-auto mb-3" style={{ color: "var(--ink-3)" }} />
          <p className="text-sm mb-1" style={{ color: "var(--ink-2)" }}>No scenarios loaded.</p>
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>
            Run{" "}
            <code className="px-1 rounded font-mono" style={{ background: "var(--bg)", color: "var(--ink-2)", fontSize: "11px", border: "1px solid var(--border)" }}>
              python manage.py load_scenarios
            </code>
          </p>
        </div>
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "0 1px 3px rgba(0,0,0,0.04)" }}
        >
          {scenarios.map((s, i) => (
            <ScenarioRow key={s.id} scenario={s} last={i === scenarios.length - 1} />
          ))}
        </div>
      )}

      {showModal && (
        <NewScenarioModal onClose={() => { setShowModal(false); mutate(); }} />
      )}
    </div>
  );
}
