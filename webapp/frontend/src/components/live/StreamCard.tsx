import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Eyebrow, Pill } from "../ui/primitives";

interface StreamCardProps {
  eyebrow: string;
  title: string;
  pill: { text: string; tone?: "brand" | "cyan" | "default" };
  src: string | null;
  active: boolean;
  emptyIcon: string;
  emptyTitle: string;
  emptyHint: string;
}

export function StreamCard({
  eyebrow,
  title,
  pill,
  src,
  active,
  emptyIcon,
  emptyTitle,
  emptyHint,
}: StreamCardProps) {
  const [loaded, setLoaded] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    if (!src) setLoaded(false);
  }, [src]);

  return (
    <article className="glass overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between px-5 pt-4">
        <div>
          <Eyebrow>{eyebrow}</Eyebrow>
          <h2 className="mt-1 text-[15px] font-semibold text-ink">{title}</h2>
        </div>
        <Pill tone={pill.tone}>{pill.text}</Pill>
      </div>
      <div className="relative mx-4 mb-4 mt-3 aspect-video overflow-hidden rounded-xl bg-base ring-1 ring-line">
        {/* Scanline sweep while a stream is active */}
        {active && (
          <div className="pointer-events-none absolute inset-0 z-10 overflow-hidden opacity-60">
            <div
              className="absolute inset-x-0 h-16 bg-gradient-to-b from-transparent via-brand/10 to-transparent"
              style={{ animation: "scanline 4.5s linear infinite" }}
            />
          </div>
        )}
        {src && (
          <img
            ref={imgRef}
            src={src}
            alt={title}
            onLoad={() => setLoaded(true)}
            className="size-full object-cover"
          />
        )}
        {!(src && loaded) && (
          <div className="absolute inset-0 grid place-content-center gap-2 text-center">
            <motion.span
              animate={{ opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 2.4, repeat: Infinity }}
              className="text-3xl text-faint"
            >
              {emptyIcon}
            </motion.span>
            <strong className="text-sm text-ink-soft">{emptyTitle}</strong>
            <small className="text-xs text-muted">{emptyHint}</small>
          </div>
        )}
      </div>
    </article>
  );
}
