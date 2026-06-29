type Status = "queued" | "running" | "completed" | "failed" | string;

const cfg: Record<string, { color: string; bg: string; dot: string; label: string }> = {
  queued:    { color: "#555554", bg: "#f4f4f3", dot: "#9d9d9b", label: "Queued" },
  running:   { color: "#1d4ed8", bg: "#eff6ff", dot: "#2563eb", label: "Running" },
  completed: { color: "#15803d", bg: "#f0fdf4", dot: "#16a34a", label: "Completed" },
  failed:    { color: "#b91c1c", bg: "#fff1f0", dot: "#dc2626", label: "Failed" },
};

export function StatusBadge({ status }: { status: Status }) {
  const c = cfg[status] ?? cfg.queued;
  const running = status === "running";

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium"
      style={{ background: c.bg, color: c.color }}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${running ? "pulse" : ""}`}
        style={{ background: c.dot }}
      />
      {c.label}
    </span>
  );
}
