import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Circle, Plug, PlugZap, Square } from "lucide-react";
import { endpoints } from "../lib/api";
import { createCaptureName, modelShortName } from "../lib/format";
import type { LiveStatus, Model, Sensor } from "../lib/types";
import { Button, StatusDot, cx } from "../components/ui/primitives";
import { Field, Input, ModelSelect, Select } from "../components/ui/form";
import { StreamCard } from "../components/live/StreamCard";
import { MetricsGrid } from "../components/live/MetricsGrid";
import { SensorCharts } from "../components/live/SensorCharts";
import type { SensorPoint } from "../hooks/queries";
import { useToast } from "../components/ui/Toast";

interface LivePageProps {
  live?: LiveStatus;
  models: Model[];
  sensor?: Sensor;
  history: SensorPoint[];
}

const RES_OPTIONS = [
  { value: 392, label: "392 · Faster" },
  { value: 504, label: "504 · Balanced" },
  { value: 672, label: "672 · Detailed" },
];

export function LivePage({ live, models, sensor, history }: LivePageProps) {
  const client = useQueryClient();
  const { toast } = useToast();

  const [streamUrl, setStreamUrl] = useState("http://192.168.0.69:81/stream");
  const [modelId, setModelId] = useState("depth-anything/DA3-BASE");
  const [processRes, setProcessRes] = useState(504);
  const [inferenceFps, setInferenceFps] = useState(5);
  const [captureName, setCaptureName] = useState(createCaptureName);
  const [keyframeFps, setKeyframeFps] = useState(2);
  const [nonce, setNonce] = useState(0);

  const connected = live ? live.state !== "disconnected" : false;
  const cameraReady = Boolean(live?.width && live?.height);
  const modelReady = live?.model_state === "ready";
  const failed = live?.state === "error" || live?.model_state === "error";
  const busy = connected && (!cameraReady || !modelReady);
  const recording = Boolean(live?.recording);

  useEffect(() => {
    if (connected) setNonce((current) => current || Date.now());
    else setNonce(0);
  }, [connected]);

  const refreshLive = () =>
    client.invalidateQueries({ queryKey: ["live-status"] });

  const connectMutation = useMutation({
    mutationFn: () =>
      endpoints.connect({
        stream_url: streamUrl.trim(),
        model_id: modelId,
        process_res: processRes,
        inference_fps: inferenceFps,
      }),
    onSuccess: () => {
      toast("Connecting", "Camera appears first; DA3 depth follows once the model loads.");
      refreshLive();
    },
    onError: (error: Error) => toast("Connection failed", error.message, "error"),
  });

  const disconnectMutation = useMutation({
    mutationFn: endpoints.disconnect,
    onSuccess: () => {
      toast("Stream disconnected");
      refreshLive();
    },
  });

  const recordStartMutation = useMutation({
    mutationFn: () => endpoints.recordStart(captureName.trim(), keyframeFps),
    onSuccess: (result) => {
      toast("Recording started", `Saving keyframes to data/${result.name}`);
      refreshLive();
    },
    onError: (error: Error) => toast("Recording failed", error.message, "error"),
  });

  const recordStopMutation = useMutation({
    mutationFn: endpoints.recordStop,
    onSuccess: (result) => {
      toast("Recording saved", `${result.manifest?.frames ?? 0} keyframes captured.`);
      setCaptureName(createCaptureName());
      client.invalidateQueries({ queryKey: ["captures"] });
      refreshLive();
    },
    onError: (error: Error) => toast("Recording failed", error.message, "error"),
  });

  function handleConnect() {
    if (connected) {
      disconnectMutation.mutate();
      return;
    }
    const url = streamUrl.trim();
    if (url.includes("[") || url.includes("](") || !/^https?:\/\//i.test(url)) {
      toast(
        "Connection failed",
        "Use the raw URL, e.g. http://192.168.0.69:81/stream",
        "error",
      );
      return;
    }
    connectMutation.mutate();
  }

  const statusText = useMemo(() => {
    if (failed) return "Attention required";
    if (!connected) return "Disconnected";
    if (live?.state === "reconnecting") return "Reconnecting camera";
    return cameraReady ? "Camera connected" : "Connecting camera";
  }, [failed, connected, live?.state, cameraReady]);

  const statusDetail = connected
    ? (live?.error ??
      (modelReady
        ? `${live?.model_id} ready`
        : `Loading ${live?.model_id ?? "DA3"}…`))
    : "Enter the ESP32 URL to begin";

  const statusTone = failed
    ? "error"
    : busy
      ? "busy"
      : live?.state === "live"
        ? "online"
        : "idle";

  const connectBusy = connectMutation.isPending || disconnectMutation.isPending;
  const recordBusy = recordStartMutation.isPending || recordStopMutation.isPending;

  return (
    <div className="flex flex-col gap-4">
      {/* Connection panel */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass ring-brand grid grid-cols-1 items-end gap-3 rounded-2xl p-4 lg:grid-cols-[1.6fr_1fr_0.9fr_0.7fr_auto]"
      >
        <Field label="ESP32 stream URL" htmlFor="streamUrl">
          <Input
            id="streamUrl"
            value={streamUrl}
            spellCheck={false}
            disabled={connected}
            onChange={(event) => setStreamUrl(event.target.value)}
          />
        </Field>
        <Field label="Live model">
          <ModelSelect models={models} value={modelId} onChange={setModelId} />
        </Field>
        <Field label="Process res">
          <Select
            value={processRes}
            disabled={connected}
            onChange={(event) => setProcessRes(Number(event.target.value))}
          >
            {RES_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Depth FPS">
          <Input
            type="number"
            min={1}
            max={30}
            step={1}
            value={inferenceFps}
            disabled={connected}
            onChange={(event) => setInferenceFps(Number(event.target.value))}
          />
        </Field>
        <Button
          variant={connected ? "danger" : "primary"}
          onClick={handleConnect}
          disabled={connectBusy}
          className="h-[42px] whitespace-nowrap"
        >
          {connected ? <PlugZap className="size-4" /> : <Plug className="size-4" />}
          {connected ? "Disconnect" : "Connect stream"}
        </Button>
      </motion.div>

      {/* Status + record toolbar */}
      <div className="glass flex flex-col gap-4 rounded-2xl p-4 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <StatusDot tone={statusTone} />
          <div>
            <strong className="block text-sm text-ink">{statusText}</strong>
            <small className="text-xs text-muted">{statusDetail}</small>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Capture name" className="w-44">
            <Input
              value={captureName}
              placeholder="live_capture_03"
              disabled={recording}
              onChange={(event) => setCaptureName(event.target.value)}
            />
          </Field>
          <Field label="Save FPS" className="w-24">
            <Input
              type="number"
              min={0.2}
              max={15}
              step={0.2}
              value={keyframeFps}
              disabled={recording}
              onChange={(event) => setKeyframeFps(Number(event.target.value))}
            />
          </Field>
          <Button
            variant={recording ? "danger" : "record"}
            disabled={!cameraReady || recordBusy}
            onClick={() =>
              recording
                ? recordStopMutation.mutate()
                : recordStartMutation.mutate()
            }
            className={cx("h-[42px]", recording && "animate-pulse-ring-rec")}
          >
            {recording ? (
              <Square className="size-3.5 fill-current" />
            ) : (
              <Circle className="size-3.5 fill-current text-danger" />
            )}
            {recording ? "Stop recording" : "Start recording"}
          </Button>
        </div>
      </div>

      {/* Streams */}
      <div className="grid gap-3 xl:grid-cols-2">
        <StreamCard
          eyebrow="Camera 01"
          title="Live stream"
          pill={{
            text: cameraReady ? `${live?.width} × ${live?.height}` : "No signal",
          }}
          src={connected && nonce ? `/api/live/raw.mjpg?t=${nonce}` : null}
          active={cameraReady}
          emptyIcon="◉"
          emptyTitle="Camera offline"
          emptyHint="Connect the ESP32 stream to begin"
        />
        <StreamCard
          eyebrow="DA3 Depth"
          title="Live depth output"
          pill={{ text: modelShortName(live?.model_id), tone: "brand" }}
          src={
            connected && nonce && modelReady
              ? `/api/live/depth.mjpg?t=${nonce}`
              : null
          }
          active={modelReady && Boolean(live?.inference_ms)}
          emptyIcon="◇"
          emptyTitle="Depth idle"
          emptyHint="The model loads after the stream connects"
        />
      </div>

      <MetricsGrid live={live} sensor={sensor} />
      <SensorCharts history={history} />
    </div>
  );
}
