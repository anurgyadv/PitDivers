import { useEffect, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { cx } from "./primitives";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Extra classes for the panel (width, height). */
  className?: string;
  /** Render a bare panel with no chrome (used by the immersive 3D viewer). */
  bare?: boolean;
  labelledBy?: string;
}

export function Modal({
  open,
  onClose,
  children,
  className,
  bare,
  labelledBy,
}: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[100] grid place-items-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          <motion.div
            className="absolute inset-0 bg-black/65 backdrop-blur-md"
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            initial={{ opacity: 0, y: 22, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
            className={cx(
              "relative z-10 w-full",
              bare
                ? ""
                : "glass-strong ring-brand overflow-hidden rounded-[26px]",
              className,
            )}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function ModalHeader({
  eyebrow,
  title,
  onClose,
  actions,
  floating,
  titleId,
}: {
  eyebrow: string;
  title: string;
  onClose: () => void;
  actions?: ReactNode;
  floating?: boolean;
  titleId?: string;
}) {
  return (
    <div
      className={cx(
        "flex items-center justify-between gap-4",
        floating
          ? "absolute inset-x-0 top-0 z-10 bg-gradient-to-b from-black/70 to-transparent px-6 py-4"
          : "border-b border-line px-6 py-4",
      )}
    >
      <div>
        <p className="text-[10.5px] font-semibold uppercase tracking-[0.22em] text-brand/80">
          {eyebrow}
        </p>
        <h2 id={titleId} className="mt-1 text-lg font-semibold text-ink">
          {title}
        </h2>
      </div>
      <div className="flex items-center gap-2">
        {actions}
        <button
          onClick={onClose}
          aria-label="Close"
          className="grid size-9 place-items-center rounded-xl text-muted transition hover:bg-white/5 hover:text-ink"
        >
          <X className="size-5" />
        </button>
      </div>
    </div>
  );
}
