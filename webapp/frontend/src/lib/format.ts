export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 MB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown date";
  const date = new Date(value);
  return new Intl.DateTimeFormat(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function createCaptureName(): string {
  const date = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `live_capture_${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(
    date.getDate(),
  )}_${pad(date.getHours())}${pad(date.getMinutes())}`;
}

export function modelShortName(modelId: string | undefined): string {
  if (!modelId) return "DA3";
  return modelId.split("/").pop()?.replaceAll("-", " ") ?? "DA3";
}
