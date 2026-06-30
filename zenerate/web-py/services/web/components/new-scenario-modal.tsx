"use client";

import { useState, useRef, useEffect } from "react";
import { X, Plus, Trash2, Loader2, ChevronDown, Check } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { Scenario } from "@/lib/types";

interface Props {
  agents: { id: string; name: string }[];
  onClose: () => void;
  scenario?: import("@/lib/types").Scenario; // when set, modal is in edit mode
}

// Known assertions with human-readable descriptions
const KNOWN_ASSERTIONS: { value: string; label: string; description: string }[] = [
  { value: "resolved_within_5_turns",                       label: "Resolved within 5 turns",                    description: "Agent resolves the issue in 5 turns or fewer" },
  { value: "resolved_within_6_turns",                       label: "Resolved within 6 turns",                    description: "Agent resolves the issue in 6 turns or fewer" },
  { value: "no_hallucinated_policy",                        label: "No hallucinated policy",                     description: "Agent doesn't invent policies or facts" },
  { value: "agent_acknowledges_frustration",                label: "Acknowledges frustration",                   description: "Agent responds with empathy to a frustrated caller" },
  { value: "agent_does_not_promise_impossible_timeline",    label: "No impossible timeline promised",            description: "Agent avoids committing to unrealistic deadlines" },
  { value: "appointment_confirmed",                         label: "Appointment confirmed",                      description: "Agent confirms a booking or appointment clearly" },
  { value: "correct_date_time_captured",                    label: "Date/time captured correctly",               description: "Agent captures the correct date and time" },
  { value: "contact_details_collected",                     label: "Contact details collected",                  description: "Agent collects name, phone, or email" },
  { value: "agent_provides_confirmation_number_or_summary", label: "Confirmation number or summary given",       description: "Agent gives a reference number or call summary" },
  { value: "agent_asks_for_clarification_when_unclear",     label: "Asks for clarification when unclear",        description: "Agent asks follow-up questions instead of guessing" },
  { value: "agent_does_not_fabricate_account_details",      label: "No fabricated account details",             description: "Agent never invents account info" },
  { value: "agent_maintains_patience",                      label: "Maintains patience",                         description: "Agent stays calm and patient throughout" },
  { value: "agent_verifies_identity_before_account_access", label: "Verifies identity before account access",   description: "Agent confirms who the caller is before sharing account info" },
];

// ── Assertion picker ──────────────────────────────────────────────────────────

function AssertionPicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [customInput, setCustomInput] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  const filtered = KNOWN_ASSERTIONS.filter(
    (a) =>
      !selected.includes(a.value) &&
      (a.label.toLowerCase().includes(query.toLowerCase()) ||
        a.value.toLowerCase().includes(query.toLowerCase()))
  );

  function toggle(value: string) {
    onChange(selected.includes(value) ? selected.filter((s) => s !== value) : [...selected, value]);
  }

  function addCustom() {
    const v = customInput.trim().replace(/\s+/g, "_").toLowerCase();
    if (v && !selected.includes(v)) { onChange([...selected, v]); }
    setCustomInput("");
  }

  return (
    <div ref={ref} className="relative">
      {/* Selected tags */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map((s) => {
            const known = KNOWN_ASSERTIONS.find((a) => a.value === s);
            return (
              <span
                key={s}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium"
                style={{ background: "var(--blue-bg)", color: "var(--blue)", border: "1px solid var(--blue-bd)" }}
              >
                {known?.label ?? s}
                <button
                  type="button"
                  onClick={() => toggle(s)}
                  className="ml-0.5 hover:opacity-70"
                >
                  <X size={10} />
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm text-left"
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border-strong)",
          color: selected.length ? "var(--ink)" : "var(--ink-3)",
        }}
      >
        <span>{selected.length === 0 ? "Select checks to add…" : `${selected.length} selected`}</span>
        <ChevronDown size={13} style={{ color: "var(--ink-3)", flexShrink: 0 }} />
      </button>

      {/* Dropdown */}
      {open && (
        <div
          className="absolute left-0 right-0 mt-1 rounded-xl overflow-hidden z-10"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.1)",
            maxHeight: "260px",
            display: "flex",
            flexDirection: "column",
          }}
        >
          {/* Search */}
          <div className="p-2 flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search checks…"
              autoFocus
              className="w-full px-2.5 py-1.5 rounded-lg text-sm outline-none"
              style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--ink)" }}
            />
          </div>

          {/* List */}
          <div className="overflow-y-auto flex-1">
            {filtered.length === 0 && query && (
              <p className="px-3 py-2 text-xs" style={{ color: "var(--ink-3)" }}>No match for "{query}"</p>
            )}
            {filtered.map((a) => (
              <button
                key={a.value}
                type="button"
                onClick={() => { toggle(a.value); setQuery(""); }}
                className="w-full text-left px-3 py-2.5 flex items-start gap-3"
                style={{ borderBottom: "1px solid var(--border)" }}
                onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "var(--bg)")}
                onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
              >
                <div
                  className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{
                    border: `1.5px solid ${selected.includes(a.value) ? "var(--blue)" : "var(--border-strong)"}`,
                    background: selected.includes(a.value) ? "var(--blue)" : "transparent",
                  }}
                >
                  {selected.includes(a.value) && <Check size={9} color="white" />}
                </div>
                <div>
                  <p className="text-sm font-medium" style={{ color: "var(--ink)" }}>{a.label}</p>
                  <p className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>{a.description}</p>
                </div>
              </button>
            ))}

            {/* Custom assertion */}
            <div className="p-2" style={{ borderTop: filtered.length > 0 ? "1px solid var(--border)" : "none" }}>
              <p className="text-xs mb-1.5 px-1" style={{ color: "var(--ink-3)" }}>
                Or add a custom check — Claude will evaluate it semantically
              </p>
              <div className="flex gap-2">
                <input
                  value={customInput}
                  onChange={(e) => setCustomInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addCustom())}
                  placeholder="e.g. agent_offers_free_shipping"
                  className="flex-1 px-2.5 py-1.5 rounded-lg text-xs font-mono outline-none"
                  style={{
                    background: "var(--bg)",
                    border: "1px solid var(--border-strong)",
                    color: "var(--ink)",
                  }}
                />
                <button
                  type="button"
                  onClick={addCustom}
                  disabled={!customInput.trim()}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-semibold text-white flex-shrink-0"
                  style={{ background: "var(--blue)", opacity: customInput.trim() ? 1 : 0.4 }}
                >
                  Add
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Rubric section ────────────────────────────────────────────────────────────

const RUBRIC_FIELDS = ["safety", "empathy", "accuracy", "resolution", "clarity", "compliance"];

function RubricSection({
  fields,
  onChange,
}: {
  fields: { key: string; weight: string }[];
  onChange: (v: { key: string; weight: string }[]) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const usedKeys = fields.map((f) => f.key).filter(Boolean);
  const available = RUBRIC_FIELDS.filter((f) => !usedKeys.includes(f));

  function add() { onChange([...fields, { key: available[0] ?? "", weight: "1.0" }]); }
  function remove(i: number) { onChange(fields.filter((_, idx) => idx !== i)); }
  function update(i: number, k: "key" | "weight", v: string) {
    onChange(fields.map((r, idx) => idx === i ? { ...r, [k]: v } : r));
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 text-xs"
        style={{ color: "var(--ink-3)" }}
      >
        <ChevronDown
          size={12}
          style={{ transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.15s" }}
        />
        {expanded ? "Hide" : "Add"} rubric scoring weights
        <span className="ml-1" style={{ color: "var(--ink-3)", fontWeight: 400 }}>
          — optional, for judge scoring
        </span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          {fields.map((r, i) => (
            <div key={i} className="flex gap-2 items-center">
              <select
                value={r.key}
                onChange={(e) => update(i, "key", e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg text-sm outline-none appearance-none"
                style={{ background: "var(--bg)", border: "1px solid var(--border-strong)", color: r.key ? "var(--ink)" : "var(--ink-3)" }}
              >
                {!r.key && <option value="">Select a field…</option>}
                {RUBRIC_FIELDS.filter((f) => f === r.key || !usedKeys.includes(f)).map((f) => (
                  <option key={f} value={f}>{f.charAt(0).toUpperCase() + f.slice(1)}</option>
                ))}
              </select>
              <div className="flex items-center gap-1 flex-shrink-0">
                <span className="text-xs" style={{ color: "var(--ink-3)" }}>×</span>
                <select
                  value={r.weight}
                  onChange={(e) => update(i, "weight", e.target.value)}
                  className="w-16 px-2 py-2 rounded-lg text-sm text-center outline-none appearance-none"
                  style={{ background: "var(--bg)", border: "1px solid var(--border-strong)", color: "var(--ink)" }}
                >
                  {["0.5", "1.0", "1.5", "2.0", "2.5", "3.0"].map((v) => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                onClick={() => remove(i)}
                className="p-1.5 rounded-lg flex-shrink-0"
                style={{ color: "var(--ink-3)" }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.color = "var(--red)";
                  (e.currentTarget as HTMLElement).style.background = "var(--red-bg)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.color = "var(--ink-3)";
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                }}
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}

          {available.length > 0 && (
            <button
              type="button"
              onClick={add}
              className="flex items-center gap-1 text-xs"
              style={{ color: "var(--blue)" }}
            >
              <Plus size={11} /> Add field
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main modal ────────────────────────────────────────────────────────────────

export function NewScenarioModal({ agents, onClose, scenario }: Props) {
  const isEdit = Boolean(scenario);

  // Pre-populate from existing scenario when editing
  const [name, setName] = useState(scenario?.name ?? "");
  const [persona, setPersona] = useState(scenario?.persona ?? "");
  const [steps, setSteps] = useState<string[]>(
    scenario?.steps?.length
      ? scenario.steps.map((s) => (typeof s === "string" ? s : s.text ?? s.raw ?? ""))
      : ["", ""]
  );
  const [assertions, setAssertions] = useState<string[]>(scenario?.assertions ?? []);
  const [rubricFields, setRubricFields] = useState<{ key: string; weight: string }[]>(
    scenario?.rubric
      ? Object.entries(scenario.rubric).map(([k, v]) => ({ key: k, weight: String(v) }))
      : []
  );
  // Map agent names → IDs for pre-population in edit mode
  const [compatibleAgentIds, setCompatibleAgentIds] = useState<string[]>(() => {
    if (!scenario?.compatible_agents?.length) return [];
    return agents
      .filter((a) => scenario.compatible_agents!.includes(a.name))
      .map((a) => a.id);
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function addStep() { setSteps([...steps, ""]); }
  function removeStep(i: number) { setSteps(steps.filter((_, idx) => idx !== i)); }
  function updateStep(i: number, v: string) { setSteps(steps.map((s, idx) => idx === i ? v : s)); }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setError("Scenario name is required"); return; }

    const filteredSteps = steps.map((s) => s.trim()).filter(Boolean);
    if (filteredSteps.length === 0) { setError("Add at least one caller message"); return; }

    const rubric = Object.fromEntries(
      rubricFields
        .filter((r) => r.key.trim())
        .map((r) => [r.key.trim(), parseFloat(r.weight) || 1])
    );

    setLoading(true);
    setError("");
    try {
      const url = isEdit ? `/api/v1/scenarios/${scenario!.id}/` : "/api/v1/scenarios/";
      await apiFetch<Scenario>(url, {
        method: isEdit ? "PATCH" : "POST",
        body: JSON.stringify({
          name: name.trim(),
          persona: persona.trim(),
          steps: filteredSteps,
          assertions,
          rubric,
          description: "",
          compatible_agent_ids: compatibleAgentIds,
        }),
      });
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : isEdit ? "Failed to update scenario" : "Failed to create scenario");
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
        className="w-full max-w-lg max-h-[90vh] flex flex-col rounded-2xl overflow-hidden fade-in"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.15), 0 0 0 1px rgba(0,0,0,0.05)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 flex-shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div>
            <h2 className="font-semibold text-[15px]" style={{ color: "var(--ink)" }}>
              {isEdit ? "Edit Scenario" : "New Scenario"}
            </h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
              {isEdit ? `Editing "${scenario!.name}"` : "Write a conversation script for a synthetic caller"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center ml-4"
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
        <form onSubmit={submit} className="flex-1 overflow-y-auto">
          <div className="px-5 py-5 space-y-5">

            {/* Name */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-2)" }}>
                Scenario name <span style={{ color: "var(--red)" }}>*</span>
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. angry_customer_refund"
                autoFocus
                className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                style={{
                  background: "var(--bg)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--ink)",
                }}
              />
              <p className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>
                Use underscores. This is the identifier used when running tests.
              </p>
            </div>

            {/* Persona */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--ink-2)" }}>
                Caller persona
              </label>
              <textarea
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                placeholder="e.g. Frustrated customer who wants a refund. Short, impatient replies. Won't accept excuses."
                rows={2}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  background: "var(--bg)",
                  border: "1px solid var(--border-strong)",
                  color: "var(--ink)",
                  resize: "none",
                  lineHeight: "1.6",
                  fontFamily: "inherit",
                }}
              />
              <p className="text-xs mt-1" style={{ color: "var(--ink-3)" }}>
                Describes who the caller is. This shapes how the caller speaks and reacts.
              </p>
            </div>

            {/* Steps — the caller's lines */}
            <div>
              <div className="flex items-start justify-between mb-2">
                <div>
                  <label className="text-xs font-medium" style={{ color: "var(--ink-2)" }}>
                    Caller messages
                  </label>
                  <p className="text-xs mt-0.5" style={{ color: "var(--ink-3)" }}>
                    What the caller says, in order. The agent responds between each one.
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                {steps.map((step, i) => (
                  <div key={i} className="flex gap-2.5 items-start">
                    {/* Caller avatar */}
                    <div
                      className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold mt-1.5"
                      style={{ background: "#f0fdf4", color: "#15803d", border: "1px solid #bbf7d0" }}
                    >
                      {i + 1}
                    </div>
                    <div className="flex-1 relative">
                      <input
                        value={step}
                        onChange={(e) => updateStep(i, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") { e.preventDefault(); addStep(); }
                        }}
                        placeholder={
                          i === 0
                            ? "e.g. Hi, I'd like to cancel my subscription"
                            : i === 1
                            ? "e.g. No wait, I want a refund actually"
                            : "Continue the conversation…"
                        }
                        className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                        style={{
                          background: "var(--bg)",
                          border: "1px solid var(--border-strong)",
                          color: "var(--ink)",
                          fontFamily: "inherit",
                        }}
                      />
                    </div>
                    {steps.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeStep(i)}
                        className="flex-shrink-0 p-1.5 rounded-lg mt-0.5"
                        style={{ color: "var(--ink-3)" }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.color = "var(--red)";
                          (e.currentTarget as HTMLElement).style.background = "var(--red-bg)";
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.color = "var(--ink-3)";
                          (e.currentTarget as HTMLElement).style.background = "transparent";
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ))}
              </div>

              <button
                type="button"
                onClick={addStep}
                className="mt-2 flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg"
                style={{ color: "var(--blue)", background: "var(--blue-bg)" }}
              >
                <Plus size={11} />
                Add message
                <span style={{ color: "var(--blue-bd)", fontSize: "10px" }}>↵ Enter</span>
              </button>

              {/* Voice Quirks reference */}
              <div
                className="mt-3 rounded-lg px-3 py-2.5"
                style={{ background: "var(--amber-bg)", border: "1px solid rgba(217,119,6,0.15)" }}
              >
                <p className="text-xs font-medium mb-1.5" style={{ color: "var(--amber)" }}>
                  Voice Quirks — inline annotations for audio mode
                </p>
                <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                  {[
                    ["[stutter]", "simulates stuttering"],
                    ["[slow_speech]", "slow/hesitant delivery"],
                    ["[pause:3s]", "adds a silence pause"],
                    ["[interrupt]", "mid-sentence interruption"],
                    ["[background_noise]", "noisy environment"],
                    ['[hard_input:"text"]', "hard to understand"],
                    ['[email:"x@y.com"]', "spoken email address"],
                    ['[phone:"415-555-0192"]', "spoken phone number"],
                  ].map(([tag, desc]) => (
                    <div key={tag} className="flex items-baseline gap-1.5">
                      <code className="text-xs flex-shrink-0 font-mono" style={{ color: "var(--amber)", fontSize: "10px" }}>{tag}</code>
                      <span className="text-xs" style={{ color: "var(--ink-3)", fontSize: "10px" }}>{desc}</span>
                    </div>
                  ))}
                </div>
                <p className="text-xs mt-1.5" style={{ color: "var(--ink-3)", fontSize: "10px" }}>
                  Example: <code className="font-mono" style={{ color: "var(--amber)" }}>[stutter] I w-want a refund</code> — stripped in text mode, played as-is in audio mode.
                </p>
              </div>
            </div>

            {/* Compatible agents */}
            {agents.length > 0 && (
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: "var(--ink-2)" }}>
                  Compatible agents
                </label>
                <p className="text-xs mb-2" style={{ color: "var(--ink-3)" }}>
                  Leave empty to allow any agent. Select specific agents to restrict.
                </p>
                <div className="flex flex-wrap gap-2">
                  {agents.map((a) => {
                    const selected = compatibleAgentIds.includes(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() =>
                          setCompatibleAgentIds(
                            selected
                              ? compatibleAgentIds.filter((id) => id !== a.id)
                              : [...compatibleAgentIds, a.id]
                          )
                        }
                        className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium"
                        style={{
                          border: `1px solid ${selected ? "var(--blue)" : "var(--border-strong)"}`,
                          background: selected ? "var(--blue-bg)" : "transparent",
                          color: selected ? "var(--blue)" : "var(--ink-3)",
                        }}
                      >
                        {selected && <Check size={10} />}
                        {a.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Pass/fail checks */}
            <div>
              <label className="block text-xs font-medium mb-1" style={{ color: "var(--ink-2)" }}>
                Pass/fail checks
              </label>
              <p className="text-xs mb-2" style={{ color: "var(--ink-3)" }}>
                Behavioral checks the agent must pass. Known checks run instantly; custom ones are evaluated by Claude.
              </p>
              <AssertionPicker selected={assertions} onChange={setAssertions} />
            </div>

            {/* Rubric — collapsed by default */}
            <RubricSection fields={rubricFields} onChange={setRubricFields} />

            {error && (
              <p className="text-xs px-1 py-1.5 rounded-lg" style={{ color: "var(--red)", background: "var(--red-bg)" }}>
                {error}
              </p>
            )}
          </div>
        </form>

        {/* Footer */}
        <div
          className="flex gap-2 px-5 py-4 flex-shrink-0"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            onClick={submit}
            disabled={loading || !name.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ background: "var(--blue)", opacity: loading || !name.trim() ? 0.5 : 1 }}
          >
            {loading && <Loader2 size={13} className="spin" />}
            {loading ? (isEdit ? "Saving…" : "Creating…") : isEdit ? "Save Changes" : "Create Scenario"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm"
            style={{ border: "1px solid var(--border-strong)", color: "var(--ink-2)" }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
