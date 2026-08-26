import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { RefreshCw } from "lucide-react";
import type { NavMeta } from "../nav";

export function Topbar({
  meta,
  onRefresh,
}: {
  meta: NavMeta;
  onRefresh: () => void;
}) {
  const [clock, setClock] = useState("");
  const [spin, setSpin] = useState(false);

  useEffect(() => {
    const tick = () =>
      setClock(
        new Intl.DateTimeFormat(undefined, {
          weekday: "short",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(new Date()),
      );
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <header className="flex items-center justify-between gap-4 border-b border-line px-7 py-5">
      <div className="min-w-0">
        <motion.p
          key={meta.eyebrow}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-[10.5px] font-semibold uppercase tracking-[0.24em] text-brand/80"
        >
          {meta.eyebrow}
        </motion.p>
        <motion.h1
          key={meta.title}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="mt-0.5 text-[22px] font-bold tracking-tight text-ink"
        >
          {meta.title}
        </motion.h1>
      </div>
      <div className="flex items-center gap-3">
        <span className="num hidden text-sm text-muted sm:block">{clock}</span>
        <motion.button
          whileTap={{ scale: 0.92 }}
          onClick={() => {
            setSpin(true);
            onRefresh();
            window.setTimeout(() => setSpin(false), 700);
          }}
          aria-label="Refresh all data"
          className="grid size-10 place-items-center rounded-xl glass text-muted transition hover:text-ink"
        >
          <RefreshCw
            className={`size-[18px] ${spin ? "animate-spin-slow" : ""}`}
          />
        </motion.button>
      </div>
    </header>
  );
}
