import { motion } from "framer-motion";
import { Boxes, ImageOff, Images, Plus } from "lucide-react";
import { formatBytes, formatDate } from "../lib/format";
import type { Capture } from "../lib/types";
import { Button } from "../components/ui/primitives";

interface CapturesPageProps {
  captures: Capture[];
  onOpenPhotos: (name: string) => void;
  onReconstruct: (name: string) => void;
  onGoLive: () => void;
}

export function CapturesPage({
  captures,
  onOpenPhotos,
  onReconstruct,
  onGoLive,
}: CapturesPageProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <p className="max-w-2xl text-sm text-muted">
          Saved keyframes from rover recordings. Open a capture to inspect its
          photos or send it to DA3.
        </p>
        <Button variant="secondary" onClick={onGoLive}>
          <Plus className="size-4" /> New capture
        </Button>
      </div>

      {captures.length === 0 ? (
        <EmptyState
          icon={<Images className="size-7 text-faint" />}
          title="No captures yet"
          hint="Connect the rover and press Start recording."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {captures.map((capture, index) => (
            <motion.article
              key={capture.name}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
              whileHover={{ y: -3 }}
              className="glass group overflow-hidden rounded-2xl"
            >
              <div className="relative aspect-video overflow-hidden bg-base">
                <img
                  src={capture.cover_url}
                  alt={`First frame from ${capture.name}`}
                  loading="lazy"
                  className="size-full object-cover transition duration-500 group-hover:scale-105"
                />
                <span className="absolute left-3 top-3 rounded-md bg-black/60 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-ink-soft backdrop-blur">
                  Keyframes
                </span>
              </div>
              <div className="flex flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="truncate text-[15px] font-semibold text-ink">
                    {capture.name}
                  </h3>
                  <time className="shrink-0 text-[11px] text-faint">
                    {formatDate(capture.updated_at)}
                  </time>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
                  <span>{capture.images} photos</span>
                  <span>{formatBytes(capture.size_bytes)}</span>
                  {capture.manifest?.frame_width ? (
                    <span>
                      {capture.manifest.frame_width}×
                      {capture.manifest.frame_height}
                    </span>
                  ) : null}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => onOpenPhotos(capture.name)}
                  >
                    View photos
                  </Button>
                  <Button
                    variant="primary"
                    onClick={() => onReconstruct(capture.name)}
                  >
                    <Boxes className="size-4" /> Build 3D
                  </Button>
                </div>
              </div>
            </motion.article>
          ))}
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <div className="glass grid place-items-center gap-2 rounded-2xl px-6 py-16 text-center">
      <div className="grid size-14 place-items-center rounded-2xl bg-white/[0.03]">
        {icon ?? <ImageOff className="size-7 text-faint" />}
      </div>
      <strong className="text-sm text-ink">{title}</strong>
      <span className="max-w-xs text-xs text-muted">{hint}</span>
    </div>
  );
}
