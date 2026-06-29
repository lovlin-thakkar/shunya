"use client";

import { useState } from "react";
import useSWR from "swr";
import { swrFetcher, apiFetch } from "@/lib/api";
import { Plus, Bot, Loader2, ArrowRight } from "lucide-react";
import Link from "next/link";
import type { Agent, PaginatedResponse } from "@/lib/types";
import { formatDistanceToNow } from "@/lib/time";

function NewAgentForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [greeting, setGreeting] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const inputStyle: React.CSSProperties = {
    background: "var(--bg)",
    border: "1px solid var(--border-strong)",
    borderRadius: "8px",
    padding: "8px 12px",
    color: "var(--ink)",
    fontSize: "14px",
    width: "100%",
    outline: "none",
    fontFamily: "inherit",
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) { setError("Name and system prompt are required"); return; }
    setLoading(true);
    setError("");
    try {
      await apiFetch("/api/v1/agents/", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), system_prompt: prompt.trim(), greeting: greeting.trim() }),
      });
      onCreated();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create agent");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-xl p-5 space-y-3 mb-5"
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
      }}
    >
      <h3 className="font-semibold text-sm" style={{ color: "var(--ink)" }}>New Agent</h3>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Agent name" style={inputStyle} />
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="System prompt"
        rows={4}
        style={{ ...inputStyle, resize: "none", lineHeight: "1.6" }}
      />
      <input value={greeting} onChange={(e) => setGreeting(e.target.value)} placeholder="Opening greeting (optional)" style={inputStyle} />
      {error && <p className="text-xs" style={{ color: "var(--red)" }}>{error}</p>}
      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={loading}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
          style={{ background: "var(--blue)", opacity: loading ? 0.7 : 1 }}
        >
          {loading ? <Loader2 size={12} className="spin" /> : <Plus size={12} />}
          Create
        </button>
        <button
          type="button"
          onClick={onCreated}
          className="px-3.5 py-2 rounded-lg text-sm"
          style={{ border: "1px solid var(--border-strong)", color: "var(--ink-2)" }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function AgentsPage() {
  const { data, mutate, isLoading } = useSWR<PaginatedResponse<Agent> | Agent[]>("/api/v1/agents/", swrFetcher);
  const [creating, setCreating] = useState(false);
  const agents: Agent[] = Array.isArray(data) ? data : (data?.results ?? []);

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>Agents</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
            {agents.length} agent{agents.length !== 1 ? "s" : ""} configured
          </p>
        </div>
        {!creating && (
          <button
            onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ background: "var(--blue)" }}
          >
            <Plus size={14} />
            New Agent
          </button>
        )}
      </div>

      {creating && <NewAgentForm onCreated={() => { setCreating(false); mutate(); }} />}

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
        </div>
      ) : agents.length === 0 ? (
        <div className="text-center py-20">
          <Bot size={32} className="mx-auto mb-3" style={{ color: "var(--ink-3)" }} />
          <p className="text-sm mb-2" style={{ color: "var(--ink-2)" }}>No agents yet.</p>
          <button
            onClick={() => setCreating(true)}
            className="text-sm underline underline-offset-2"
            style={{ color: "var(--blue)" }}
          >
            Create your first agent
          </button>
        </div>
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
          }}
        >
          {agents.map((agent, idx) => (
            <Link
              key={agent.id}
              href={`/agents/${agent.id}`}
              className="group flex items-center gap-4 px-5 py-4"
              style={{
                borderTop: idx === 0 ? "none" : "1px solid var(--border)",
                display: "flex",
              }}
              onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = "var(--bg)")}
              onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = "transparent")}
            >
              <div
                className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                style={{ background: "var(--blue-bg)" }}
              >
                <Bot size={14} style={{ color: "var(--blue)" }} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-medium text-sm" style={{ color: "var(--ink)" }}>{agent.name}</p>
                <p className="text-xs mt-0.5 truncate" style={{ color: "var(--ink-3)", maxWidth: "420px" }}>
                  {agent.system_prompt || "No system prompt"}
                </p>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <span className="text-xs" style={{ color: "var(--ink-3)" }}>
                  {formatDistanceToNow(agent.created_at)}
                </span>
                <ArrowRight
                  size={14}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                  style={{ color: "var(--blue)" }}
                />
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
