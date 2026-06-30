"use client";

import { useState, useEffect, useRef } from "react";
import { apiFetch } from "@/lib/api";
import type { ElevenLabsIntegration } from "@/lib/types";
import { Mic, X, ExternalLink } from "lucide-react";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onConnected: () => void;
}

export function ConnectElevenLabsModal({ isOpen, onClose, onConnected }: Props) {
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      setInput("");
      setError("");
      setSaving(false);
      // Focus the input after the modal animates in
      setTimeout(() => inputRef.current?.focus(), 60);
    }
  }, [isOpen]);

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

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
      onConnected();
      onClose();
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "Could not save the key.";
      setError(raw.replace(/^\d+:\s*/, "").slice(0, 200) || "Could not save the key.");
    } finally {
      setSaving(false);
    }
  }

  return (
    // Backdrop
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.4)", backdropFilter: "blur(2px)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Dialog */}
      <div
        className="w-full max-w-[420px] rounded-2xl fade-in"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.16), 0 0 0 1px rgba(0,0,0,0.04)",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div className="flex items-center gap-2.5">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: "var(--blue-bg)" }}
            >
              <Mic size={14} style={{ color: "var(--blue)" }} />
            </div>
            <p className="font-semibold text-sm" style={{ color: "var(--ink)" }}>
              Connect ElevenLabs
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center"
            style={{ color: "var(--ink-3)" }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.background = "var(--surface-3)";
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
        <div className="px-6 py-5 space-y-4">
          <p className="text-sm leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Paste your ElevenLabs API key to list and test your Conversational AI agents.
            The key is stored on your tenant and never shown again.
          </p>

          {/* Permission guide */}
          <div
            className="rounded-xl p-4 text-xs leading-relaxed space-y-2"
            style={{ background: "var(--bg)", border: "1px solid var(--border)" }}
          >
            <p className="font-semibold text-[11px] uppercase tracking-wide" style={{ color: "var(--ink-3)" }}>
              Required permissions
            </p>
            <p style={{ color: "var(--ink-2)" }}>
              In your ElevenLabs dashboard, go to{" "}
              <span className="font-medium">Settings → API Keys</span> and
              create or edit a key with:
            </p>
            <div className="flex items-center gap-2 py-1">
              <span
                className="font-mono px-2 py-0.5 rounded text-[11px]"
                style={{
                  background: "var(--surface)",
                  color: "var(--ink)",
                  border: "1px solid var(--border-strong)",
                }}
              >
                Conversational AI → Read
              </span>
              <span style={{ color: "var(--ink-3)" }}>to list your agents</span>
            </div>
            <p style={{ color: "var(--ink-3)" }}>
              Everything else can stay <span className="font-medium">No Access</span>.
            </p>
            <a
              href="https://elevenlabs.io/app/settings/api-keys"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-medium"
              style={{ color: "var(--blue)" }}
            >
              Open ElevenLabs API Keys
              <ExternalLink size={11} />
            </a>
          </div>

          {/* Form */}
          <form onSubmit={save} className="space-y-3">
            <input
              ref={inputRef}
              type="password"
              value={input}
              onChange={(e) => { setInput(e.target.value); setError(""); }}
              placeholder="sk_…"
              autoComplete="off"
              spellCheck={false}
              className="w-full px-3 py-2.5 rounded-lg text-sm font-mono outline-none"
              style={{
                background: "var(--bg)",
                border: `1px solid ${error ? "var(--red)" : "var(--border-strong)"}`,
                color: "var(--ink)",
              }}
            />
            {error && (
              <p className="text-xs" style={{ color: "var(--red)" }}>{error}</p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 py-2.5 rounded-lg text-sm font-medium"
                style={{
                  border: "1px solid var(--border-strong)",
                  color: "var(--ink-2)",
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || !input.trim()}
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold text-white"
                style={{
                  background: "var(--blue)",
                  opacity: saving || !input.trim() ? 0.5 : 1,
                }}
              >
                {saving ? "Verifying…" : "Save & connect"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
