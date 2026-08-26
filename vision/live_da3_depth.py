"""Display live Depth Anything 3 depth from an ESP32 MJPEG stream.

The capture thread always keeps only the newest frame so inference does not
build up seconds of latency behind the live camera.
"""

from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import cv2
import torch

from depth_anything_3.api import DepthAnything3
from depth_anything_3.utils.visualize import visualize_depth


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DA3 monocular depth on the newest ESP32 stream frame."
    )
    parser.add_argument(
        "--stream-url",
        required=True,
        help="MJPEG URL, commonly http://<ESP32-IP>:81/stream",
    )
    parser.add_argument("--model", default="depth-anything/DA3-BASE")
    parser.add_argument(
        "--process-res",
        type=int,
        default=392,
        help="DA3 processing resolution. Try 504 for quality or 336 for speed.",
    )
    parser.add_argument(
        "--inference-fps",
        type=float,
        default=5.0,
        help="Maximum DA3 updates per second.",
    )
    parser.add_argument(
        "--keyframe-dir",
        type=Path,
        default=None,
        help="Optional folder in which to save frames for final 3D reconstruction.",
    )
    parser.add_argument(
        "--keyframe-fps",
        type=float,
        default=2.0,
        help="Frames saved per second when --keyframe-dir is supplied.",
    )
    return parser.parse_args()


class LatestFrameCapture:
    """Read continuously while exposing only the newest complete frame."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._capture: cv2.VideoCapture | None = None
        self._frame = None
        self._sequence = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)

    def start(self) -> "LatestFrameCapture":
        self._thread.start()
        return self

    def _open(self) -> bool:
        capture = cv2.VideoCapture(self.url)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            return False
        self._capture = capture
        return True

    def _reader(self) -> None:
        while not self._stop.is_set():
            if self._capture is None and not self._open():
                time.sleep(1.0)
                continue

            assert self._capture is not None
            ok, frame = self._capture.read()
            if not ok:
                self._capture.release()
                self._capture = None
                time.sleep(0.25)
                continue

            with self._lock:
                self._frame = frame
                self._sequence += 1

    def latest(self):
        with self._lock:
            if self._frame is None:
                return None, self._sequence
            return self._frame.copy(), self._sequence

    def close(self) -> None:
        self._stop.set()
        if self._capture is not None:
            self._capture.release()
        self._thread.join(timeout=2.0)


def add_status(image, status: str) -> None:
    cv2.rectangle(image, (0, 0), (image.shape[1], 30), (0, 0, 0), -1)
    cv2.putText(
        image,
        status,
        (8, 21),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )


def main() -> None:
    args = parse_args()
    if args.inference_fps <= 0:
        raise SystemExit("--inference-fps must be greater than zero")
    if args.keyframe_fps <= 0:
        raise SystemExit("--keyframe-fps must be greater than zero")

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable. This live mode requires the NVIDIA GPU.")

    device = torch.device("cuda")
    print(f"Loading {args.model} on {torch.cuda.get_device_name(0)} ...")
    model = DepthAnything3.from_pretrained(args.model).to(device=device).eval()

    if args.keyframe_dir is not None:
        args.keyframe_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving keyframes to {args.keyframe_dir.resolve()}")

    stream = LatestFrameCapture(args.stream_url).start()
    print("Waiting for the ESP32 stream. Press Q in the window to stop.")

    last_sequence = -1
    last_inference_at = 0.0
    last_keyframe_at = 0.0
    keyframe_count = 0
    display = None

    try:
        while True:
            frame, sequence = stream.latest()
            now = time.perf_counter()

            if frame is None:
                if cv2.waitKey(20) & 0xFF in (ord("q"), ord("Q")):
                    break
                time.sleep(0.02)
                continue

            if (
                args.keyframe_dir is not None
                and now - last_keyframe_at >= 1.0 / args.keyframe_fps
            ):
                keyframe_path = args.keyframe_dir / f"frame_{keyframe_count:06d}.jpg"
                cv2.imwrite(str(keyframe_path), frame)
                keyframe_count += 1
                last_keyframe_at = now

            should_infer = (
                sequence != last_sequence
                and now - last_inference_at >= 1.0 / args.inference_fps
            )
            if should_infer:
                started_at = time.perf_counter()
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                prediction = model.inference(
                    [rgb_frame],
                    process_res=args.process_res,
                    process_res_method="upper_bound_resize",
                )

                rgb_processed = prediction.processed_images[0].astype("uint8")
                depth_rgb = visualize_depth(prediction.depth[0])
                rgb_bgr = cv2.cvtColor(rgb_processed, cv2.COLOR_RGB2BGR)
                depth_bgr = cv2.cvtColor(depth_rgb, cv2.COLOR_RGB2BGR)
                display = cv2.hconcat([rgb_bgr, depth_bgr])

                elapsed = time.perf_counter() - started_at
                status = (
                    f"DA3 LIVE | {elapsed * 1000:.0f} ms | "
                    f"{1.0 / max(elapsed, 1e-6):.1f} FPS | "
                    f"saved {keyframe_count}"
                )
                add_status(display, status)
                last_sequence = sequence
                last_inference_at = time.perf_counter()

            if display is not None:
                cv2.imshow("PitDivers - Live DA3 Depth", display)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
    finally:
        stream.close()
        cv2.destroyAllWindows()
        print(f"Stopped. Saved {keyframe_count} keyframes.")


if __name__ == "__main__":
    main()
