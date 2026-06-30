"use client";

import { useState } from "react";
import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import { Bot, Loader2, ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { Agent } from "@/lib/types";

// Agents are synced from the tenant's ElevenLabs account, not authored here.
const syncAgents = () => apiFetch<Agent[]>("/api/v1/agents/sync-elevenlabs/", { method: "POST" });

export default function AgentsPage() {
  const { data, error, isLoading, mutate } = useSWR<Agent[]>("elevenlabs-agents", syncAgents, {
    revalidateOnFocus: false,
  });
  const [syncing, setSyncing] = useState(false);
  const agents: Agent[] = data ?? [];

  async function resync() {
    setSyncing(true);
    try {
      await mutate(syncAgents(), { revalidate: false });
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-semibold text-xl" style={{ color: "var(--ink)" }}>Agents</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-3)" }}>
            {agents.length} ElevenLabs agent{agents.length !== 1 ? "s" : ""} synced
          </p>
        </div>
        <button
          onClick={resync}
          disabled={syncing || isLoading}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-semibold"
          style={{ border: "1px solid var(--border-strong)", color: "var(--ink-2)", opacity: syncing ? 0.6 : 1 }}
        >
          <RefreshCw size={14} className={syncing ? "spin" : ""} />
          Sync from ElevenLabs
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={18} className="spin" style={{ color: "var(--ink-3)" }} />
        </div>
      ) : error ? (
        <div className="text-center py-20">
          <Bot size={32} className="mx-auto mb-3" style={{ color: "var(--ink-3)" }} />
          <p className="text-sm mb-2" style={{ color: "var(--red)" }}>
            Couldn&apos;t load agents from ElevenLabs.
          </p>
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>
            Check that your ElevenLabs key has the <code>convai_read</code> permission.
          </p>
        </div>
      ) : agents.length === 0 ? (
        <div className="text-center py-20">
          <Bot size={32} className="mx-auto mb-3" style={{ color: "var(--ink-3)" }} />
          <p className="text-sm mb-1" style={{ color: "var(--ink-2)" }}>No agents found in your ElevenLabs account.</p>
          <p className="text-xs" style={{ color: "var(--ink-3)" }}>
            Create a Conversational AI agent in ElevenLabs, then sync.
          </p>
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
              style={{ borderTop: idx === 0 ? "none" : "1px solid var(--border)", display: "flex" }}
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
                <p className="text-xs mt-0.5 truncate font-mono" style={{ color: "var(--ink-3)", maxWidth: "420px" }}>
                  {agent.el_agent_id}
                </p>
              </div>
              <ArrowRight
                size={14}
                className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                style={{ color: "var(--blue)" }}
              />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
