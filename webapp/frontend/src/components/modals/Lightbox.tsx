import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect } from "react";
import type { Photo } from "../../lib/types";

export function Lightbox({
  photo,
  onClose,
}: {
  photo: Photo | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!photo) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [photo, onClose]);

  return (
    <AnimatePresence>
      {photo && (
        <motion.div
          className="fixed inset-0 z-[130] grid place-items-center bg-black/85 p-6 backdrop-blur-lg"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <button
            onClick={onClose}
            aria-label="Close image"
            className="absolute right-6 top-6 grid size-10 place-items-center rounded-xl glass text-muted transition hover:text-ink"
          >
            <X className="size-5" />
          </button>
          <motion.img
            key={photo.url}
            src={photo.url}
            alt={photo.name}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            onClick={(event) => event.stopPropagation()}
            className="max-h-[85vh] max-w-[90vw] rounded-2xl object-contain ring-1 ring-line"
          />
          <span className="num absolute bottom-6 rounded-lg bg-black/60 px-3 py-1.5 text-xs text-ink-soft backdrop-blur">
            {photo.name}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
