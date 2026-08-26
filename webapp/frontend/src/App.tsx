import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { endpoints } from "./lib/api";
import { NAV, type Tab } from "./nav";
import type { Photo, Run } from "./lib/types";
import {
  useCaptures,
  useHealth,
  useJobs,
  useLiveStatus,
  useModels,
  useRuns,
  useSensorHistory,
} from "./hooks/queries";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { LivePage } from "./pages/LivePage";
import { CapturesPage } from "./pages/CapturesPage";
import { ReconstructionsPage } from "./pages/ReconstructionsPage";
import { ModelsPage } from "./pages/ModelsPage";
import { PhotoDialog } from "./components/modals/PhotoDialog";
import { ReconstructDialog } from "./components/modals/ReconstructDialog";
import { Lightbox } from "./components/modals/Lightbox";

// The 3D viewer pulls in model-viewer / three.js, so load it on demand.
const ViewerDialog = lazy(() =>
  import("./components/modals/ViewerDialog").then((module) => ({
    default: module.ViewerDialog,
  })),
);
import { useToast } from "./components/ui/Toast";

export default function App() {
  const client = useQueryClient();
  const { toast } = useToast();

  const [tab, setTab] = useState<Tab>("live");
  const [photoCapture, setPhotoCapture] = useState<string | null>(null);
  const [reconstructCapture, setReconstructCapture] = useState<string | null>(null);
  const [viewerRun, setViewerRun] = useState<Run | null>(null);
  const [lightboxPhoto, setLightboxPhoto] = useState<Photo | null>(null);

  const health = useHealth();
  const live = useLiveStatus();
  const captures = useCaptures();
  const runs = useRuns();
  const jobs = useJobs();
  const models = useModels();
  const { sensor, history } = useSensorHistory();

  // Announce reconstructions the moment they finish, once each.
  const announced = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const job of jobs.data?.jobs ?? []) {
      if (job.state === "complete" && !announced.current.has(job.id)) {
        announced.current.add(job.id);
        toast("3D reconstruction complete", `${job.run_name}/scene.glb is ready.`);
        client.invalidateQueries({ queryKey: ["runs"] });
      }
    }
  }, [jobs.data, client, toast]);

  const cancelMutation = useMutation({
    mutationFn: endpoints.cancelJob,
    onSuccess: () => {
      toast("Stopping reconstruction", "The DA3 process is being terminated.");
      client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error: Error) => toast("Could not stop job", error.message, "error"),
  });

  const downloadMutation = useMutation({
    mutationFn: endpoints.downloadModel,
    onSuccess: () => {
      toast("Model download started");
      client.invalidateQueries({ queryKey: ["models"] });
    },
    onError: (error: Error) => toast("Download failed", error.message, "error"),
  });

  function refreshAll() {
    client.invalidateQueries();
  }

  const meta = NAV.find((item) => item.id === tab)!;
  const modelList = models.data ?? [];

  return (
    <div className="flex h-full">
      <Sidebar
        active={tab}
        onTab={setTab}
        captureCount={captures.data?.length ?? 0}
        runCount={runs.data?.length ?? 0}
        live={live.data}
        health={health.data}
        healthError={health.isError}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <Topbar meta={meta} onRefresh={refreshAll} />
        <div className="flex-1 overflow-y-auto px-7 py-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.22 }}
            >
              {tab === "live" && (
                <LivePage
                  live={live.data}
                  models={modelList}
                  sensor={sensor}
                  history={history}
                />
              )}
              {tab === "captures" && (
                <CapturesPage
                  captures={captures.data ?? []}
                  onOpenPhotos={setPhotoCapture}
                  onReconstruct={setReconstructCapture}
                  onGoLive={() => setTab("live")}
                />
              )}
              {tab === "reconstructions" && (
                <ReconstructionsPage
                  jobs={jobs.data?.jobs ?? []}
                  runs={runs.data ?? []}
                  onView={setViewerRun}
                  onCancel={(id) => cancelMutation.mutate(id)}
                  onGoCaptures={() => setTab("captures")}
                />
              )}
              {tab === "models" && (
                <ModelsPage
                  models={modelList}
                  onDownload={(id) => downloadMutation.mutate(id)}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* Overlays */}
      <PhotoDialog
        captureName={photoCapture}
        onClose={() => setPhotoCapture(null)}
        onOpenLightbox={setLightboxPhoto}
      />
      <ReconstructDialog
        captureName={reconstructCapture}
        captures={captures.data ?? []}
        models={modelList}
        live={live.data}
        onClose={() => setReconstructCapture(null)}
        onStarted={() => setTab("reconstructions")}
      />
      {viewerRun && (
        <Suspense fallback={null}>
          <ViewerDialog run={viewerRun} onClose={() => setViewerRun(null)} />
        </Suspense>
      )}
      <Lightbox photo={lightboxPhoto} onClose={() => setLightboxPhoto(null)} />
    </div>
  );
}
