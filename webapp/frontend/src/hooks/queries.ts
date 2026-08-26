import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { endpoints } from "../lib/api";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: endpoints.health,
    refetchInterval: 5000,
  });
}

export function useLiveStatus() {
  return useQuery({
    queryKey: ["live-status"],
    queryFn: endpoints.liveStatus,
    refetchInterval: 1000,
  });
}

export function useCaptures() {
  return useQuery({
    queryKey: ["captures"],
    queryFn: endpoints.captures,
    refetchInterval: 6000,
  });
}

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: endpoints.runs,
    refetchInterval: 6000,
  });
}

export function useJobs() {
  return useQuery({
    queryKey: ["jobs"],
    queryFn: endpoints.jobs,
    refetchInterval: 1500,
  });
}

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: endpoints.models,
    refetchInterval: 6000,
  });
}

export interface SensorPoint {
  time: number;
  temperature: number;
  humidity: number;
}

const MAX_SENSOR_POINTS = 240;

/**
 * Polls the DHT11 proxy and keeps a rolling in-memory history for the charts,
 * mirroring the original dashboard's browser-session history behaviour.
 */
export function useSensorHistory() {
  const query = useQuery({
    queryKey: ["sensors"],
    queryFn: endpoints.sensors,
    refetchInterval: 2500,
  });

  const [history, setHistory] = useState<SensorPoint[]>([]);
  const lastAppended = useRef<number>(0);

  useEffect(() => {
    const sensor = query.data;
    if (
      !sensor?.ok ||
      !Number.isFinite(sensor.temperature_c) ||
      !Number.isFinite(sensor.humidity_percent)
    ) {
      return;
    }
    const stamp = query.dataUpdatedAt;
    if (stamp === lastAppended.current) return;
    lastAppended.current = stamp;
    setHistory((previous) => {
      const next = [
        ...previous,
        {
          time: Date.now(),
          temperature: sensor.temperature_c as number,
          humidity: sensor.humidity_percent as number,
        },
      ];
      return next.length > MAX_SENSOR_POINTS
        ? next.slice(next.length - MAX_SENSOR_POINTS)
        : next;
    });
  }, [query.data, query.dataUpdatedAt]);

  return { sensor: query.data, history };
}
