"use client";

import { useState, useEffect, ReactNode } from "react";
import { API_KEY_STORAGE } from "@/lib/api";
import { Key } from "lucide-react";

export function ApiKeyGate({ children }: { children: ReactNode }) {
  const [key, setKey] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setKey(localStorage.getItem(API_KEY_STORAGE));
    setHydrated(true);
  }, []);

  if (!hydrated) return null;
  if (key) return <>{children}</>;

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    setChecking(true);
    setError("");
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/agents/`,
        { headers: { Authorization: `Api-Key ${trimmed}` } }
      );
      if (!res.ok) { setError("Invalid API key — double-check and try again."); return; }
      localStorage.setItem(API_KEY_STORAGE, trimmed);
      setKey(trimmed);
    } catch {
      setError("Cannot reach the server. Make sure it's running.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center p-6"
      style={{ background: "var(--bg)" }}
    >
      <div className="w-full max-w-[360px] fade-in">
        {/* Logo */}
        <div className="flex items-center gap-3 mb-8">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-sm text-white"
            style={{ background: "var(--blue)" }}
          >
            S
          </div>
          <div>
            <p className="font-semibold text-sm" style={{ color: "var(--ink)" }}>Shunya</p>
            <p className="text-xs" style={{ color: "var(--ink-3)" }}>Voice AI QA</p>
          </div>
        </div>

        {/* Form card */}
        <div
          className="rounded-2xl p-6"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            boxShadow: "0 2px 12px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.03)",
          }}
        >
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center mb-4"
            style={{ background: "var(--blue-bg)" }}
          >
            <Key size={15} style={{ color: "var(--blue)" }} />
          </div>

          <h1 className="font-semibold text-[15px] mb-1" style={{ color: "var(--ink)" }}>
            Sign in with API key
          </h1>
          <p className="text-sm mb-5 leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Enter your Shunya API key to access the dashboard.
          </p>

          <form onSubmit={connect} className="space-y-3">
            <input
              type="password"
              value={input}
              onChange={(e) => { setInput(e.target.value); setError(""); }}
              placeholder="sk-…"
              autoFocus
              autoComplete="off"
              className="w-full px-3 py-2.5 rounded-lg text-sm font-mono outline-none"
              style={{
                background: "var(--bg)",
                border: `1px solid ${error ? "var(--red)" : "var(--border-strong)"}`,
                color: "var(--ink)",
              }}
              onFocus={(e) => {
                if (!error) (e.target as HTMLInputElement).style.borderColor = "var(--blue)";
                (e.target as HTMLInputElement).style.boxShadow = error
                  ? "0 0 0 3px rgba(220,38,38,0.1)"
                  : "0 0 0 3px rgba(37,99,235,0.1)";
              }}
              onBlur={(e) => {
                if (!error) (e.target as HTMLInputElement).style.borderColor = "var(--border-strong)";
                (e.target as HTMLInputElement).style.boxShadow = "none";
              }}
            />

            {error && (
              <p className="text-xs" style={{ color: "var(--red)" }}>{error}</p>
            )}

            <button
              type="submit"
              disabled={checking || !input.trim()}
              className="w-full py-2.5 rounded-lg text-sm font-semibold text-white"
              style={{
                background: "var(--blue)",
                opacity: checking || !input.trim() ? 0.5 : 1,
              }}
            >
              {checking ? "Connecting…" : "Connect"}
            </button>
          </form>

          <p className="mt-4 text-xs" style={{ color: "var(--ink-3)" }}>
            Generate a key:{" "}
            <code
              className="px-1 py-0.5 rounded font-mono"
              style={{ background: "var(--bg)", color: "var(--ink-2)", fontSize: "11px" }}
            >
              python manage.py generate_api_key
            </code>
          </p>
        </div>
      </div>
    </div>
  );
}
