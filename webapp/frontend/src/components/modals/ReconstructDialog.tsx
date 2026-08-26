import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Boxes, TriangleAlert } from "lucide-react";
import { endpoints } from "../../lib/api";
import { formatBytes, modelShortName } from "../../lib/format";
import type { Capture, LiveStatus, Model } from "../../lib/types";
import { Modal, ModalHeader } from "../ui/Modal";
import { Button } from "../ui/primitives";
import { Field, ModelSelect, Select } from "../ui/form";
import { useToast } from "../ui/Toast";

const RES_OPTIONS = [
  { value: 392, label: "392 · Lower memory" },
  { value: 504, label: "504 · Recommended" },
  { value: 672, label: "672 · Higher detail / memory" },
];

export function ReconstructDialog({
  captureName,
  captures,
  models,
  live,
  onClose,
  onStarted,
}: {
  captureName: string | null;
  captures: Capture[];
  models: Model[];
  live?: LiveStatus;
  onClose: () => void;
  onStarted: () => void;
}) {
  const client = useQueryClient();
  const { toast } = useToast();
  const [modelId, setModelId] = useState("depth-anything/DA3-BASE");
  const [processRes, setProcessRes] = useState(504);

  const capture = captures.find((item) => item.name === captureName);

  const mutation = useMutation({
    mutationFn: async () => {
      if (live && live.state !== "disconnected") {
        await endpoints.disconnect();
        await client.invalidateQueries({ queryKey: ["live-status"] });
      }
      return endpoints.reconstruct({
        capture_name: captureName!,
        model_id: modelId,
        process_res: processRes,
      });
    },
    onSuccess: (job) => {
      toast(
        "Reconstruction started",
        `${job.images} images with ${modelShortName(job.model_id)}`,
      );
      client.invalidateQueries({ queryKey: ["jobs"] });
      onClose();
      onStarted();
    },
    onError: (error: Error) =>
      toast("Could not start reconstruction", error.message, "error"),
  });

  return (
    <Modal
      open={Boolean(captureName)}
      onClose={onClose}
      className="max-w-lg"
    >
      <ModalHeader
        eyebrow="DA3 Pipeline"
        title="Build 3D reconstruction"
        onClose={onClose}
      />
      <form
        className="flex flex-col gap-4 p-6"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <div className="glass flex items-center gap-3 rounded-xl p-3.5">
          <div className="grid size-10 place-items-center rounded-lg bg-brand/15 text-brand">
            <Boxes className="size-5" />
          </div>
          <div className="min-w-0">
            <strong className="block truncate text-sm text-ink">
              {captureName}
            </strong>
            <small className="text-xs text-muted">
              {capture?.images ?? 0} keyframes •{" "}
              {formatBytes(capture?.size_bytes ?? 0)}
            </small>
          </div>
        </div>

        <Field label="DA3 model">
          <ModelSelect models={models} value={modelId} onChange={setModelId} />
        </Field>
        <Field label="Processing resolution">
          <Select
            value={processRes}
            onChange={(event) => setProcessRes(Number(event.target.value))}
          >
            {RES_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>

        <div className="flex items-start gap-2.5 rounded-xl border border-warn/25 bg-warn/[0.07] p-3 text-xs text-ink-soft">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warn" />
          Live mode disconnects while reconstruction runs, so two DA3 processes
          do not compete for GPU memory.
        </div>

        <Button
          type="submit"
          variant="primary"
          disabled={mutation.isPending}
          className="w-full"
        >
          {mutation.isPending ? "Starting…" : "Start reconstruction"}
        </Button>
      </form>
    </Modal>
  );
}
