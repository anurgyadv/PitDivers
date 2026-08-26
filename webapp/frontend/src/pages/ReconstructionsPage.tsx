import { AnimatePresence, motion } from "framer-motion";
import { Boxes, Download, Eye, Square } from "lucide-react";
import { formatBytes, formatDate, modelShortName } from "../lib/format";
import type { Job, Run } from "../lib/types";
import { Button, Eyebrow, cx } from "../components/ui/primitives";
import { EmptyState } from "./CapturesPage";

interface ReconstructionsPageProps {
  jobs: Job[];
  runs: Run[];
  onView: (run: Run) => void;
  onCancel: (id: string) => void;
  onGoCaptures: () => void;
}

const ACTIVE_STATES = ["queued", "running", "cancelling", "error"];

const stateTone: Record<string, string> = {
  queued: "text-muted",
  running: "text-cyan",
  cancelling: "text-warn",
  error: "text-danger",
};

export function ReconstructionsPage({
  jobs,
  runs,
  onView,
  onCancel,
  onGoCaptures,
}: ReconstructionsPageProps) {
  const activeJobs = jobs.filter((job) => ACTIVE_STATES.includes(job.state));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <p className="max-w-2xl text-sm text-muted">
          Completed GLB point clouds and active reconstruction jobs.
        </p>
        <Button variant="secondary" onClick={onGoCaptures}>
          Choose capture
        </Button>
      </div>

      <AnimatePresence>
        {activeJobs.map((job) => (
          <motion.article
            key={job.id}
            layout
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="glass-strong overflow-hidden rounded-2xl p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Eyebrow>
                  <span className={stateTone[job.state]}>
                    {job.state.toUpperCase()}
                  </span>
                </Eyebrow>
                <h3 className="mt-1 truncate text-[15px] font-semibold text-ink">
                  {job.capture} → {job.run_name}
                </h3>
                <p className="mt-0.5 text-xs text-muted">
                  {job.stage} • {job.images} images •{" "}
                  {modelShortName(job.model_id)}
                </p>
              </div>
              {["queued", "running"].includes(job.state) && (
                <Button variant="danger" onClick={() => onCancel(job.id)}>
                  <Square className="size-3.5 fill-current" /> Stop
                </Button>
              )}
            </div>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-white/[0.05]">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-brand-deep via-brand to-brand-soft"
                animate={{ width: `${job.progress || 0}%` }}
                transition={{ type: "spring", stiffness: 120, damping: 24 }}
              />
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px]">
              <span className="truncate text-muted">
                {job.error ?? job.stage}
              </span>
              <strong className="num text-ink-soft">
                {job.progress || 0}%
              </strong>
            </div>

            {job.logs.length > 0 && (
              <pre className="num mt-3 max-h-28 overflow-auto rounded-xl bg-base/70 p-3 text-[11px] leading-relaxed text-muted ring-1 ring-line">
                {job.logs.slice(-8).join("\n")}
              </pre>
            )}
          </motion.article>
        ))}
      </AnimatePresence>

      {runs.length === 0 ? (
        <EmptyState
          icon={<Boxes className="size-7 text-faint" />}
          title="No 3D models yet"
          hint="Choose a capture and run DA3 reconstruction."
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {runs.map((run, index) => (
            <motion.article
              key={run.name}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
              whileHover={{ y: -3 }}
              className="glass group overflow-hidden rounded-2xl"
            >
              <div className="relative grid aspect-video place-items-center overflow-hidden bg-gradient-to-br from-panel-2 to-base">
                {run.thumbnail_url ? (
                  <img
                    src={run.thumbnail_url}
                    alt={`Depth preview for ${run.name}`}
                    loading="lazy"
                    className="size-full object-cover transition duration-500 group-hover:scale-105"
                  />
                ) : (
                  <Boxes className="size-10 text-faint" />
                )}
                <span className="absolute left-3 top-3 rounded-md bg-black/60 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-ink-soft backdrop-blur">
                  GLB Scene
                </span>
              </div>
              <div className="flex flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="truncate text-[15px] font-semibold text-ink">
                    {run.name}
                  </h3>
                  <time className="shrink-0 text-[11px] text-faint">
                    {formatDate(run.updated_at)}
                  </time>
                </div>
                <div className="flex flex-wrap gap-x-3 text-[11px] text-muted">
                  <span>{formatBytes(run.size_bytes)}</span>
                  <span>Interactive point cloud</span>
                </div>
                <div className="grid grid-cols-[1fr_auto] gap-2">
                  <Button variant="primary" onClick={() => onView(run)}>
                    <Eye className="size-4" /> Open 3D viewer
                  </Button>
                  <a
                    href={run.download_url}
                    className={cx(
                      "inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm glass text-ink-soft transition hover:text-ink",
                    )}
                    aria-label={`Download ${run.name}`}
                  >
                    <Download className="size-4" />
                  </a>
                </div>
              </div>
            </motion.article>
          ))}
        </div>
      )}
    </div>
  );
}
