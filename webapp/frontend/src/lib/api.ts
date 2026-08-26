import type {
  Capture,
  Health,
  JobsStatus,
  LiveStatus,
  Model,
  PhotoPage,
  Run,
  Sensor,
} from "./types";

interface ApiOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body,
    signal: options.signal,
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    /* no JSON body */
  }
  if (!response.ok) {
    const detail =
      (payload as { detail?: string; error?: string } | null)?.detail ??
      (payload as { detail?: string; error?: string } | null)?.error ??
      `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return payload as T;
}

export interface ConnectPayload {
  stream_url: string;
  model_id: string;
  process_res: number;
  inference_fps: number;
}

export interface ReconstructPayload {
  capture_name: string;
  model_id: string;
  process_res: number;
}

export const endpoints = {
  health: () => api<Health>("/api/health"),
  liveStatus: () => api<LiveStatus>("/api/live/status"),
  sensors: () => api<Sensor>("/api/sensors"),
  captures: () => api<Capture[]>("/api/captures"),
  runs: () => api<Run[]>("/api/runs"),
  jobs: () => api<JobsStatus>("/api/jobs"),
  models: () => api<Model[]>("/api/models"),

  connect: (payload: ConnectPayload) =>
    api<LiveStatus>("/api/live/connect", { method: "POST", body: payload }),
  disconnect: () => api<LiveStatus>("/api/live/disconnect", { method: "POST" }),
  recordStart: (name: string, keyframe_fps: number) =>
    api<{ name: string; status: LiveStatus }>("/api/live/record/start", {
      method: "POST",
      body: { name, keyframe_fps },
    }),
  recordStop: () =>
    api<{ manifest: { frames?: number } | null; status: LiveStatus }>(
      "/api/live/record/stop",
      { method: "POST" },
    ),

  photos: (capture: string, offset: number, limit: number) =>
    api<PhotoPage>(
      `/api/captures/${encodeURIComponent(capture)}/photos?offset=${offset}&limit=${limit}`,
    ),

  reconstruct: (payload: ReconstructPayload) =>
    api<{ id: string; images: number; model_id: string }>(
      "/api/jobs/reconstruct",
      { method: "POST", body: payload },
    ),
  cancelJob: (id: string) =>
    api<JobsStatus>(`/api/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  downloadModel: (model_id: string) =>
    api<{ ok: boolean }>("/api/models/download", {
      method: "POST",
      body: { model_id },
    }),
};
