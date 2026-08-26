import {
  forwardRef,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { motion, useMotionValue, useSpring, useTransform } from "framer-motion";
import { useEffect } from "react";

/* ---------------------------------------------------------------- classnames */

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/* --------------------------------------------------------------------- Button */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "record";

const variants: Record<Variant, string> = {
  primary:
    "bg-brand text-[#1a0a02] font-semibold hover:bg-brand-soft shadow-[0_10px_30px_-12px_rgba(255,106,44,0.8)]",
  secondary:
    "glass text-ink-soft hover:text-ink hover:border-line-strong",
  ghost: "text-muted hover:text-ink hover:bg-white/5",
  danger:
    "bg-danger/15 text-danger font-semibold hover:bg-danger/25 border border-danger/30",
  record:
    "glass-strong text-ink font-semibold hover:border-line-strong",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  children: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "secondary", className, children, ...rest }, ref) => (
    <motion.button
      ref={ref}
      whileTap={{ scale: 0.96 }}
      whileHover={{ y: -1 }}
      transition={{ type: "spring", stiffness: 500, damping: 30 }}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-45",
        variants[variant],
        className,
      )}
      {...(rest as Record<string, unknown>)}
    >
      {children}
    </motion.button>
  ),
);
Button.displayName = "Button";

/* ------------------------------------------------------------------ StatusDot */

type DotTone = "idle" | "online" | "busy" | "error" | "rec";

const dotTones: Record<DotTone, string> = {
  idle: "bg-faint",
  online: "bg-ok animate-pulse-ring",
  busy: "bg-warn",
  error: "bg-danger",
  rec: "bg-danger animate-pulse-ring-rec",
};

export function StatusDot({ tone }: { tone: DotTone }) {
  return (
    <span
      className={cx("inline-block size-2.5 rounded-full", dotTones[tone])}
    />
  );
}

/* ------------------------------------------------------------------------ Pill */

export function Pill({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "brand" | "cyan";
}) {
  const tones = {
    default: "text-muted border-line bg-white/[0.03]",
    brand: "text-brand border-brand/30 bg-brand/10",
    cyan: "text-cyan border-cyan/30 bg-cyan/10",
  };
  return (
    <span
      className={cx(
        "rounded-full border px-2.5 py-1 text-[11px] font-medium tracking-wide",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

/* --------------------------------------------------------------- Eyebrow label */

export function Eyebrow({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "cyan";
}) {
  return (
    <p
      className={cx(
        "text-[10.5px] font-semibold uppercase tracking-[0.22em]",
        tone === "cyan" ? "text-cyan/80" : "text-faint",
      )}
    >
      {children}
    </p>
  );
}

/* ------------------------------------------------------------- AnimatedNumber */

export function AnimatedNumber({
  value,
  decimals = 0,
  className,
}: {
  value: number;
  decimals?: number;
  className?: string;
}) {
  const motionValue = useMotionValue(value);
  const spring = useSpring(motionValue, { stiffness: 140, damping: 22 });
  const display = useTransform(spring, (latest) =>
    Number.isFinite(latest) ? latest.toFixed(decimals) : "—",
  );
  useEffect(() => {
    motionValue.set(value);
  }, [value, motionValue]);
  return <motion.span className={className}>{display}</motion.span>;
}
