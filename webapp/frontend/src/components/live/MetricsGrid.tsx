import { motion } from "framer-motion";
import {
  Camera,
  Droplets,
  Gauge,
  Layers,
  Thermometer,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { AnimatedNumber } from "../ui/primitives";
import type { LiveStatus, Sensor } from "../../lib/types";

interface Metric {
  label: string;
  icon: LucideIcon;
  value: number | null;
  decimals?: number;
  suffix?: string;
  hint: string;
  tone?: string;
}

export function MetricsGrid({
  live,
  sensor,
}: {
  live?: LiveStatus;
  sensor?: Sensor;
}) {
  const sensorOk =
    sensor?.ok &&
    Number.isFinite(sensor.temperature_c) &&
    Number.isFinite(sensor.humidity_percent);

  const metrics: Metric[] = [
    {
      label: "Camera FPS",
      icon: Camera,
      value: live?.capture_fps ?? null,
      decimals: 1,
      hint: "Incoming MJPEG",
    },
    {
      label: "DA3 FPS",
      icon: Layers,
      value: live?.depth_fps ?? null,
      decimals: 1,
      hint: "Processed frames",
      tone: "text-cyan",
    },
    {
      label: "Inference",
      icon: Timer,
      value: live?.inference_ms ? live.inference_ms : null,
      suffix: " ms",
      hint: "Per depth frame",
    },
    {
      label: "Keyframes",
      icon: Gauge,
      value: live?.frames_saved ?? 0,
      hint: live?.recording ? (live.recording_name ?? "Recording") : "Not recording",
      tone: live?.recording ? "text-danger" : undefined,
    },
    {
      label: "Temperature",
      icon: Thermometer,
      value: sensorOk ? (sensor?.temperature_c ?? null) : null,
      decimals: 1,
      suffix: " °C",
      hint: sensorOk ? `DHT11 · GPIO ${sensor?.gpio}` : "DHT11 · sensor GPIO",
      tone: "text-brand",
    },
    {
      label: "Humidity",
      icon: Droplets,
      value: sensorOk ? (sensor?.humidity_percent ?? null) : null,
      decimals: 1,
      suffix: "%",
      hint: sensorOk ? "DHT11 online" : "Sensor offline",
      tone: "text-cyan",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      {metrics.map((metric, index) => {
        const Icon = metric.icon;
        return (
          <motion.div
            key={metric.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.04 }}
            className="glass rounded-2xl p-4"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10.5px] font-semibold uppercase tracking-wider text-faint">
                {metric.label}
              </span>
              <Icon className={`size-4 ${metric.tone ?? "text-muted"}`} />
            </div>
            <div className="num mt-2 text-[26px] font-semibold text-ink">
              {metric.value === null ? (
                <span className="text-faint">—</span>
              ) : (
                <>
                  <AnimatedNumber
                    value={metric.value}
                    decimals={metric.decimals ?? 0}
                  />
                  {metric.suffix && (
                    <span className="text-base text-muted">{metric.suffix}</span>
                  )}
                </>
              )}
            </div>
            <small className="mt-0.5 block truncate text-[11px] text-muted">
              {metric.hint}
            </small>
          </motion.div>
        );
      })}
    </div>
  );
}
