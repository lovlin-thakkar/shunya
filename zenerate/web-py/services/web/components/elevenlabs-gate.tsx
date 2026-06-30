"use client";

import { useState, useEffect, ReactNode } from "react";
import { apiFetch } from "@/lib/api";
import type { ElevenLabsIntegration } from "@/lib/types";
import { Mic } from "lucide-react";

/**
 * Step 2 of sign-in: once the Shunya API key is set (ApiKeyGate), require the
 * tenant to connect their own ElevenLabs key before using the app. Only prompts
 * when no key is saved server-side; after that it passes through.
 */
export function ElevenLabsGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<"loading" | "needed" | "ready">("loading");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<ElevenLabsIntegration>("/api/v1/integrations/elevenlabs/")
      .then((d) => setStatus(d.configured ? "ready" : "needed"))
      .catch(() => setStatus("needed"));
  }, []);

  if (status === "loading") return null;
  if (status === "ready") return <>{children}</>;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    setSaving(true);
    setError("");
    try {
      await apiFetch<ElevenLabsIntegration>("/api/v1/integrations/elevenlabs/", {
        method: "PUT",
        body: JSON.stringify({ api_key: trimmed }),
      });
      setStatus("ready");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Could not save the key.";
      // apiFetch throws "<status>: <body>" — show the server's reason if present.
      setError(msg.replace(/^\d+:\s*/, "").slice(0, 200) || "Could not save the key.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "var(--bg)" }}>
      <div className="w-full max-w-[380px] fade-in">
        <div className="flex items-center gap-3 mb-8">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm text-white"
            style={{ background: "var(--blue)" }}
          >
            S
          </div>
          <div>
            <p className="font-semibold text-sm" style={{ color: "var(--ink)" }}>Shunya</p>
            <p className="text-xs" style={{ color: "var(--ink-3)" }}>Connect ElevenLabs</p>
          </div>
        </div>

        <div
          className="rounded-2xl p-6"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            boxShadow: "0 2px 12px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.03)",
          }}
        >
          <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-4" style={{ background: "var(--blue-bg)" }}>
            <Mic size={15} style={{ color: "var(--blue)" }} />
          </div>

          <h1 className="font-semibold text-[15px] mb-1" style={{ color: "var(--ink)" }}>
            Connect your ElevenLabs account
          </h1>
          <p className="text-sm mb-4 leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Paste an ElevenLabs API key so we can list and test your Conversational AI agents.
          </p>

          {/* Permission guidance — set scopes before generating/copying the key */}
          <div
            className="rounded-lg p-3.5 mb-5 text-xs leading-relaxed"
            style={{ background: "var(--blue-bg)", border: "1px solid var(--border)" }}
          >
            <p className="font-semibold mb-1.5" style={{ color: "var(--ink-2)" }}>
              Before you copy the key, set its permissions
            </p>
            <p style={{ color: "var(--ink-3)" }}>
              In ElevenLabs → <span style={{ color: "var(--ink-2)" }}>Settings → API Keys</span>,
              edit or create a key and set:
            </p>
            <p className="mt-1.5">
              <span
                className="font-mono px-1.5 py-0.5 rounded"
                style={{ background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--border-strong)" }}
              >
                ElevenAgents → Write
              </span>
            </p>
            <p className="mt-1.5" style={{ color: "var(--ink-3)" }}>
              <code>Read</code> lets us list your agents; <code>Write</code> lets us reach
              private agents. Everything else can stay <code>No Access</code>.
            </p>
            <a
              href="https://elevenlabs.io/app/settings/api-keys"
              target="_blank"
              rel="noreferrer"
              className="inline-block mt-2 underline underline-offset-2"
              style={{ color: "var(--blue)" }}
            >
              Open ElevenLabs API Keys →
            </a>
          </div>

          <form onSubmit={save} className="space-y-3">
            <input
              type="password"
              value={input}
              onChange={(e) => { setInput(e.target.value); setError(""); }}
              placeholder="sk_…"
              autoFocus
              autoComplete="off"
              className="w-full px-3 py-2.5 rounded-lg text-sm font-mono outline-none"
              style={{
                background: "var(--bg)",
                border: `1px solid ${error ? "var(--red)" : "var(--border-strong)"}`,
                color: "var(--ink)",
              }}
            />
            {error && <p className="text-xs" style={{ color: "var(--red)" }}>{error}</p>}
            <button
              type="submit"
              disabled={saving || !input.trim()}
              className="w-full py-2.5 rounded-lg text-sm font-semibold text-white"
              style={{ background: "var(--blue)", opacity: saving || !input.trim() ? 0.5 : 1 }}
            >
              {saving ? "Verifying…" : "Save & continue"}
            </button>
          </form>

          <p className="mt-4 text-xs leading-relaxed" style={{ color: "var(--ink-3)" }}>
            The key is stored on your tenant and never shown again. Manage permissions in your
            ElevenLabs dashboard under API Keys.
          </p>
        </div>
      </div>
    </div>
  );
}
