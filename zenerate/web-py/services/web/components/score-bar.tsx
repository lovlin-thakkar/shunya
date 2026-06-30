interface Props {
  field: string;
  score: number;
  passed: boolean;
  reasoning: string;
}

export function ScoreBar({ field, score, passed, reasoning }: Props) {
  const pct = Math.round(score * 100);
  const color = passed ? "var(--green)" : "var(--red)";
  const bgColor = passed ? "var(--green-bg)" : "var(--red-bg)";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium capitalize" style={{ color: "var(--ink-2)" }}>
          {field.replace(/_/g, " ")}
        </span>
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-semibold px-1.5 py-0.5 rounded"
            style={{ background: bgColor, color }}
          >
            {pct}%
          </span>
          <span className="text-xs" style={{ color: passed ? "var(--green)" : "var(--red)" }}>
            {passed ? "✓" : "✗"}
          </span>
        </div>
      </div>

      {/* Track */}
      <div
        className="relative h-1.5 rounded-full overflow-hidden mb-2"
        style={{ background: "var(--border)" }}
      >
        <div
          className="absolute left-0 top-0 h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: color,
            transition: "width 0.5s ease",
          }}
        />
        {/* 70% threshold */}
        <div
          className="absolute top-0 bottom-0 w-px"
          style={{ left: "70%", background: "rgba(0,0,0,0.15)" }}
        />
      </div>

      {reasoning && (
        <p className="text-xs leading-relaxed" style={{ color: "var(--ink-3)" }}>
          {reasoning}
        </p>
      )}
    </div>
  );
}
