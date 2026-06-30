import type { TranscriptTurn } from "@/lib/types";

import { RecordingPlayer } from "./recording-player";

interface Props {
  turns: TranscriptTurn[];
  audioRunId?: string;
}

export function Transcript({ turns, audioRunId }: Props) {
  if (!turns || turns.length === 0) {
    return (
      <div className="py-10 text-center text-sm" style={{ color: "var(--ink-3)" }}>
        No transcript available.
      </div>
    );
  }

  return (
    <div>
      {/* Audio player */}
      {audioRunId && (
        <div className="mb-5 pb-5" style={{ borderBottom: "1px solid var(--border)" }}>
          <p className="text-xs font-medium mb-2" style={{ color: "var(--ink-3)" }}>Recording</p>
          <RecordingPlayer runId={audioRunId} />
        </div>
      )}

      {/* Turns */}
      <div>
        {turns.map((turn, i) => {
          const isCaller = turn.speaker?.toLowerCase() === "caller";
          const last = i === turns.length - 1;

          return (
            <div
              key={i}
              className="flex gap-3 py-3"
              style={{
                borderBottom: last ? "none" : "1px solid var(--border)",
              }}
            >
              {/* Speaker tag */}
              <div className="flex-shrink-0 pt-0.5" style={{ width: "52px" }}>
                <span
                  className="inline-block text-xs font-semibold px-1.5 py-0.5 rounded"
                  style={{
                    background: isCaller ? "#f0fdf4" : "#eff6ff",
                    color: isCaller ? "#15803d" : "#1d4ed8",
                    fontSize: "10px",
                  }}
                >
                  {isCaller ? "User" : "Agent"}
                </span>
                {turn.ts_ms != null && (
                  <p className="font-mono mt-1" style={{ color: "var(--ink-3)", fontSize: "9px" }}>
                    {(turn.ts_ms / 1000).toFixed(1)}s
                  </p>
                )}
              </div>

              {/* Text */}
              <div className="flex-1 min-w-0 text-sm" style={{ color: "var(--ink)", lineHeight: "1.65" }}>
                {turn.quirks?.map((q, qi) => (
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
                {turn.text}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
