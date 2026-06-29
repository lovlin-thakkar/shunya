"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bot, FlaskConical, ListChecks, LogOut } from "lucide-react";
import { API_KEY_STORAGE } from "@/lib/api";
import clsx from "clsx";

const nav = [
  { href: "/agents",    label: "Agents",    icon: Bot },
  { href: "/scenarios", label: "Scenarios", icon: ListChecks },
  { href: "/tests",     label: "Tests",     icon: FlaskConical },
];

export function Sidebar() {
  const path = usePathname();

  function signOut() {
    localStorage.removeItem(API_KEY_STORAGE);
    window.location.reload();
  }

  return (
    <aside
      className="w-56 flex-shrink-0 flex flex-col h-screen sticky top-0 bg-surface"
      style={{ borderRight: "1px solid var(--border)" }}
    >
      {/* Logo */}
      <div className="px-5 py-5" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center gap-2.5">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold"
            style={{ background: "var(--blue)" }}
          >
            S
          </div>
          <div>
            <p className="font-semibold text-sm leading-tight" style={{ color: "var(--ink)" }}>
              Shunya
            </p>
            <p className="text-xs" style={{ color: "var(--ink-3)" }}>Voice AI QA</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-3 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = path === href || path.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium relative",
                active
                  ? "bg-blue-bg text-blue"
                  : "text-ink-2 hover:bg-surface-3 hover:text-ink"
              )}
              style={active ? { color: "var(--blue)", background: "var(--blue-bg)" } : {}}
            >
              {active && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r"
                  style={{ background: "var(--blue)" }}
                />
              )}
              <Icon
                size={15}
                className="flex-shrink-0"
                style={{ color: active ? "var(--blue)" : "var(--ink-3)" }}
              />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 pb-4" style={{ borderTop: "1px solid var(--border)", paddingTop: "12px" }}>
        <button
          onClick={signOut}
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full text-left"
          style={{ color: "var(--ink-3)" }}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLElement;
            el.style.color = "var(--red)";
            el.style.background = "var(--red-bg)";
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLElement;
            el.style.color = "var(--ink-3)";
            el.style.background = "transparent";
          }}
        >
          <LogOut size={14} />
          Change API Key
        </button>
      </div>
    </aside>
  );
}
