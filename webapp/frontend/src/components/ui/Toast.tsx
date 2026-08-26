import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Info, TriangleAlert, X } from "lucide-react";

type ToastKind = "info" | "success" | "error";

interface ToastItem {
  id: number;
  title: string;
  message?: string;
  kind: ToastKind;
}

interface ToastApi {
  toast: (title: string, message?: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const kindStyles: Record<
  ToastKind,
  { icon: typeof Info; accent: string; glow: string }
> = {
  info: { icon: Info, accent: "text-cyan", glow: "rgba(42,211,196,0.25)" },
  success: {
    icon: CheckCircle2,
    accent: "text-ok",
    glow: "rgba(67,209,127,0.28)",
  },
  error: {
    icon: TriangleAlert,
    accent: "text-danger",
    glow: "rgba(255,90,95,0.3)",
  },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);

  const remove = useCallback((id: number) => {
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (title: string, message?: string, kind: ToastKind = "info") => {
      const id = ++counter.current;
      setItems((current) => [...current, { id, title, message, kind }]);
      window.setTimeout(() => remove(id), 4800);
    },
    [remove],
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[120] flex w-[min(92vw,22rem)] flex-col gap-2.5">
        <AnimatePresence>
          {items.map((item) => {
            const { icon: Icon, accent, glow } = kindStyles[item.kind];
            return (
              <motion.div
                key={item.id}
                layout
                initial={{ opacity: 0, x: 40, scale: 0.96 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40, scale: 0.9 }}
                transition={{ type: "spring", stiffness: 380, damping: 30 }}
                className="glass-strong pointer-events-auto flex items-start gap-3 rounded-2xl px-4 py-3"
                style={{ boxShadow: `0 18px 50px -20px ${glow}` }}
              >
                <Icon className={`mt-0.5 size-5 shrink-0 ${accent}`} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-ink">{item.title}</p>
                  {item.message && (
                    <p className="mt-0.5 text-xs leading-relaxed text-muted">
                      {item.message}
                    </p>
                  )}
                </div>
                <button
                  onClick={() => remove(item.id)}
                  className="text-faint transition hover:text-ink"
                  aria-label="Dismiss"
                >
                  <X className="size-4" />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
}
