import { motion } from "framer-motion";
import { Check, Download, Loader2, TriangleAlert } from "lucide-react";
import type { Model } from "../lib/types";
import { Button, StatusDot, cx } from "../components/ui/primitives";

interface ModelsPageProps {
  models: Model[];
  onDownload: (id: string) => void;
}

export function ModelsPage({ models, onDownload }: ModelsPageProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-sm text-muted">
          Download checkpoints once, then run them from the local Hugging Face
          cache.
        </p>
        <small className="text-xs text-faint">
          Base and Small are Apache-2.0. The larger research checkpoints have
          non-commercial licences.
        </small>
      </div>

      <div className="flex flex-col gap-2.5">
        {models.map((model, index) => {
          const job = model.download;
          const downloading = job?.state === "downloading";
          const failed = job?.state === "error";
          const tone = model.cached
            ? "online"
            : downloading
              ? "busy"
              : failed
                ? "error"
                : "idle";
          const stateLabel = model.cached
            ? "Available locally"
            : downloading
              ? "Downloading…"
              : failed
                ? "Download failed"
                : "Not downloaded";

          return (
            <motion.article
              key={model.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
              className="glass grid grid-cols-1 items-center gap-4 rounded-2xl p-4 md:grid-cols-[1.6fr_repeat(3,0.7fr)_1fr_auto]"
            >
              <div className="min-w-0">
                <strong className="block text-[15px] font-semibold text-ink">
                  {model.name}
                </strong>
                <small className="text-xs text-muted">{model.recommended}</small>
              </div>
              <Stat label="Parameters" value={model.parameters} />
              <Stat label="VRAM" value={model.vram} />
              <Stat label="Licence" value={model.license} />
              <div
                className="flex items-center gap-2 text-xs text-ink-soft"
                title={job?.error ?? ""}
              >
                <StatusDot tone={tone} />
                {stateLabel}
              </div>
              <Button
                variant={model.cached ? "secondary" : "primary"}
                disabled={model.cached || downloading}
                onClick={() => onDownload(model.id)}
                className="min-w-[130px]"
              >
                {model.cached ? (
                  <>
                    <Check className="size-4" /> Downloaded
                  </>
                ) : downloading ? (
                  <>
                    <Loader2 className="size-4 animate-spin" /> Downloading
                  </>
                ) : failed ? (
                  <>
                    <TriangleAlert className="size-4" /> Retry
                  </>
                ) : (
                  <>
                    <Download className="size-4" /> Download
                  </>
                )}
              </Button>
            </motion.article>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={cx("flex flex-col")}>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-faint">
        {label}
      </span>
      <strong className="text-sm text-ink-soft">{value}</strong>
    </div>
  );
}
