import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { endpoints } from "../../lib/api";
import type { Photo } from "../../lib/types";
import { Modal, ModalHeader } from "../ui/Modal";

export function PhotoDialog({
  captureName,
  onClose,
  onOpenLightbox,
}: {
  captureName: string | null;
  onClose: () => void;
  onOpenLightbox: (photo: Photo) => void;
}) {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!captureName) return;
    let cancelled = false;
    setStatus("loading");
    setPhotos([]);

    (async () => {
      try {
        const collected: Photo[] = [];
        let offset = 0;
        let total = 1;
        while (offset < total) {
          const page = await endpoints.photos(captureName, offset, 500);
          if (cancelled) return;
          total = page.total;
          collected.push(...page.photos);
          offset += page.photos.length;
          if (page.photos.length === 0) break;
        }
        if (!cancelled) {
          setPhotos(collected);
          setStatus("ready");
        }
      } catch (caught) {
        if (!cancelled) {
          setError((caught as Error).message);
          setStatus("error");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [captureName]);

  return (
    <Modal
      open={Boolean(captureName)}
      onClose={onClose}
      className="flex max-h-[86vh] max-w-5xl flex-col"
    >
      <ModalHeader
        eyebrow="Capture review"
        title={captureName ?? "Photos"}
        onClose={onClose}
      />
      <div className="border-b border-line px-6 py-2.5 text-xs text-muted">
        {status === "ready"
          ? `${photos.length} photos • click any frame for full size`
          : status === "loading"
            ? "Loading photos…"
            : error}
      </div>
      <div className="grid flex-1 grid-cols-3 gap-2 overflow-y-auto p-5 sm:grid-cols-4 md:grid-cols-6">
        {photos.map((photo, index) => (
          <motion.button
            key={photo.url}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: Math.min(index * 0.01, 0.3) }}
            whileHover={{ scale: 1.04 }}
            onClick={() => onOpenLightbox(photo)}
            title={photo.name}
            className="aspect-square overflow-hidden rounded-lg ring-1 ring-line"
          >
            <img
              src={photo.url}
              alt={photo.name}
              loading="lazy"
              className="size-full object-cover"
            />
          </motion.button>
        ))}
      </div>
    </Modal>
  );
}
