export interface Health {
  ok: boolean;
  cuda: boolean;
  gpu: string | null;
}

export type LiveState =
  | "disconnected"
  | "connecting"
  | "reconnecting"
  | "live"
  | "error";

export interface LiveStatus {
  state: LiveState;
  model_state: "idle" | "loading" | "ready" | "error";
  error: string | null;
  stream_url: string;
  model_id: string;
  process_res: number;
  inference_fps: number;
  connected_at: string | null;
  capture_fps: number;
  depth_fps: number;
  inference_ms: number;
  width: number;
  height: number;
  recording: boolean;
  recording_name: string | null;
  frames_saved: number;
  keyframe_fps: number;
}

export interface Sensor {
  ok: boolean;
  temperature_c?: number;
  humidity_percent?: number;
  gpio?: number;
  status_code?: number;
  age_ms?: number;
  error?: string;
  url?: string;
}

export interface CaptureManifest {
  name?: string;
  state?: string;
  frames?: number;
  frame_width?: number;
  frame_height?: number;
  model_id?: string;
  [key: string]: unknown;
}

export interface Capture {
  name: string;
  images: number;
  size_bytes: number;
  updated_at: string;
  cover_url: string;
  manifest: CaptureManifest;
}

export interface Photo {
  name: string;
  url: string;
}

export interface PhotoPage {
  name: string;
  total: number;
  offset: number;
  photos: Photo[];
}

export interface Run {
  name: string;
  size_bytes: number;
  updated_at: string;
  model_url: string;
  download_url: string;
  thumbnail_url: string | null;
}

export type JobState =
  | "queued"
  | "running"
  | "cancelling"
  | "cancelled"
  | "complete"
  | "error";

export interface Job {
  id: string;
  state: JobState;
  capture: string;
  run_name: string;
  model_id: string;
  process_res: number;
  images: number;
  progress: number;
  stage: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  logs: string[];
}

export interface JobsStatus {
  active_job: string | null;
  jobs: Job[];
}

export interface ModelDownload {
  state: "downloading" | "complete" | "error";
  started_at?: string;
  completed_at?: string;
  error?: string | null;
}

export interface Model {
  id: string;
  name: string;
  parameters: string;
  license: string;
  recommended: string;
  vram: string;
  cached: boolean;
  download: ModelDownload | null;
}
