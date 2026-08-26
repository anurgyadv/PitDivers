import { motion } from "framer-motion";
import { Cpu } from "lucide-react";
import { NAV, type Tab } from "../nav";
import { cx } from "./ui/primitives";
import type { Health, LiveStatus } from "../lib/types";

interface SidebarProps {
  active: Tab;
  onTab: (tab: Tab) => void;
  captureCount: number;
  runCount: number;
  live?: LiveStatus;
  health?: Health;
  healthError?: boolean;
}

export function Sidebar({
  active,
  onTab,
  captureCount,
  runCount,
  live,
  health,
  healthError,
}: SidebarProps) {
  const badges: Partial<Record<Tab, number>> = {
    captures: captureCount,
    reconstructions: runCount,
  };

  const systemTone = healthError
    ? "bg-danger"
    : health?.cuda
      ? "bg-ok animate-pulse-ring"
      : "bg-warn";

  return (
    <aside className="flex w-[248px] shrink-0 flex-col gap-6 border-r border-line bg-base-2/60 px-4 py-6 backdrop-blur-xl">
      {/* Brand */}
      <div className="flex items-center gap-3 px-2">
        <div className="relative grid size-10 place-items-center rounded-2xl bg-gradient-to-br from-brand to-brand-deep shadow-[0_10px_24px_-10px_rgba(255,106,44,0.9)]">
          <div className="flex items-end gap-[3px]">
            <span className="h-2 w-[3px] rounded-full bg-black/70" />
            <span className="h-3.5 w-[3px] rounded-full bg-black/80" />
            <span className="h-2.5 w-[3px] rounded-full bg-black/70" />
          </div>
        </div>
        <div className="leading-tight">
          <strong className="block text-[15px] font-bold tracking-tight text-ink">
            PITDIVERS
          </strong>
          <small className="text-[11px] text-faint">Rover vision console</small>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex flex-col gap-1">
        {NAV.map((item) => {
          const Icon = item.icon;
          const isActive = active === item.id;
          const badge = badges[item.id];
          const showLiveDot = item.id === "live" && live?.state === "live";
          return (
            <button
              key={item.id}
              onClick={() => onTab(item.id)}
              className={cx(
                "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                isActive ? "text-ink" : "text-muted hover:text-ink-soft",
              )}
            >
              {isActive && (
                <motion.span
                  layoutId="nav-active"
                  className="glass absolute inset-0 -z-10 rounded-xl"
                  transition={{ type: "spring", stiffness: 400, damping: 32 }}
                />
              )}
              <Icon
                className={cx(
                  "size-[18px] transition-colors",
                  isActive ? "text-brand" : "text-faint group-hover:text-muted",
                )}
              />
              <span className="flex-1 text-left">{item.label}</span>
              {showLiveDot && (
                <span className="size-2 rounded-full bg-ok animate-pulse-ring-rec" />
              )}
              {badge !== undefined && badge > 0 && (
                <span className="num rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[11px] text-ink-soft">
                  {badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="flex-1" />

      {/* System card */}
      <div className="glass rounded-2xl p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
          <span className={cx("size-2 rounded-full", systemTone)} />
          Base station
        </div>
        <div className="mt-2.5 flex items-center gap-2">
          <Cpu className="size-4 shrink-0 text-brand" />
          <strong className="truncate text-[13px] text-ink">
            {healthError
              ? "Service unavailable"
              : (health?.gpu ?? "Checking GPU…")}
          </strong>
        </div>
        <small className="mt-1 block text-[11px] leading-relaxed text-muted">
          {healthError
            ? "Connecting to local service"
            : health?.cuda
              ? "CUDA ready • Local processing"
              : "CUDA unavailable"}
        </small>
      </div>
    </aside>
  );
}
