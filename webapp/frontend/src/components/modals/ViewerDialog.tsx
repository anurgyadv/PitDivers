import { useRef } from "react";
import "@google/model-viewer";
import { Download, Maximize } from "lucide-react";
import { Modal, ModalHeader } from "../ui/Modal";
import { Button, cx } from "../ui/primitives";
import type { Run } from "../../lib/types";
import { useToast } from "../ui/Toast";

export function ViewerDialog({
  run,
  onClose,
}: {
  run: Run | null;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) {
        await containerRef.current?.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch (error) {
      toast("Fullscreen unavailable", (error as Error).message, "error");
    }
  }

  return (
    <Modal
      open={Boolean(run)}
      onClose={onClose}
      bare
      className="max-w-5xl"
    >
      <div
        ref={containerRef}
        className="glass-strong ring-brand relative aspect-[16/10] w-full overflow-hidden rounded-[26px] bg-base"
      >
        <ModalHeader
          floating
          eyebrow="3D Reconstruction"
          title={run?.name ?? "Scene"}
          onClose={onClose}
          actions={
            <>
              <a
                href={run?.download_url}
                className={cx(
                  "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm glass text-ink-soft transition hover:text-ink",
                )}
              >
                <Download className="size-4" /> GLB
              </a>
              <Button variant="secondary" onClick={toggleFullscreen}>
                <Maximize className="size-4" /> Full screen
              </Button>
            </>
          }
        />
        {run && (
          <model-viewer
            key={run.name}
            src={`${run.model_url}?t=${Date.now()}`}
            alt="Interactive DA3 reconstruction"
            camera-controls
            auto-rotate
            interaction-prompt="auto"
            shadow-intensity="0"
            exposure="1.1"
            style={{ width: "100%", height: "100%", background: "transparent" }}
          />
        )}
      </div>
    </Modal>
  );
}
