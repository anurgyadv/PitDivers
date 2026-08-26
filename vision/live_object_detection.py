"""Run Hugging Face object detection against an ESP32 camera stream."""

from __future__ import annotations

import argparse
import time
from contextlib import nullcontext

import cv2
import torch
from transformers import AutoImageProcessor, AutoModelForObjectDetection


DEFAULT_MODEL = "PekingU/rtdetr_r18vd"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display an ESP32 MJPEG stream with object-detection boxes."
    )
    parser.add_argument(
        "--stream-url",
        required=True,
        help="ESP32 MJPEG URL, commonly http://<ESP32-IP>:81/stream",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="Optional COCO labels to show, for example: person car truck",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Force CPU inference even when CUDA is available.",
    )
    parser.add_argument(
        "--half",
        action="store_true",
        help="Use CUDA automatic mixed precision. Enable only after the basic run works.",
    )
    return parser.parse_args()


def draw_detections(
    frame,
    result: dict[str, torch.Tensor],
    id_to_label: dict[int, str],
    allowed_classes: set[str] | None,
) -> int:
    detection_count = 0

    for score, label_id, box in zip(
        result["scores"], result["labels"], result["boxes"]
    ):
        label = id_to_label[int(label_id)]
        if allowed_classes is not None and label.lower() not in allowed_classes:
            continue

        x1, y1, x2, y2 = (int(value) for value in box.tolist())
        confidence = float(score)
        detection_count += 1

        cv2.rectangle(frame, (x1, y1), (x2, y2), (65, 220, 80), 2)
        caption = f"{label} {confidence:.2f}"
        (text_width, text_height), _ = cv2.getTextSize(
            caption, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        text_y = max(y1, text_height + 8)
        cv2.rectangle(
            frame,
            (x1, text_y - text_height - 8),
            (x1 + text_width + 6, text_y),
            (65, 220, 80),
            -1,
        )
        cv2.putText(
            frame,
            caption,
            (x1 + 3, text_y - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    return detection_count


def main() -> None:
    args = parse_args()
    if not 0.0 <= args.threshold <= 1.0:
        raise SystemExit("--threshold must be between 0 and 1")

    device = torch.device(
        "cpu" if args.cpu or not torch.cuda.is_available() else "cuda"
    )
    if args.half and device.type != "cuda":
        raise SystemExit("--half requires a CUDA GPU")

    print(f"Loading {args.model} on {device} ...")
    processor = AutoImageProcessor.from_pretrained(args.model)
    model = AutoModelForObjectDetection.from_pretrained(args.model)
    model.to(device).eval()

    print(f"Opening {args.stream_url} ...")
    capture = cv2.VideoCapture(args.stream_url)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not capture.isOpened():
        raise SystemExit(
            "Could not open the stream. Check the URL in a browser and try "
            "http://<ESP32-IP>:81/stream or the stream URL shown by the camera page."
        )

    allowed_classes = (
        {label.lower() for label in args.classes} if args.classes else None
    )
    smoothed_fps = 0.0

    print("Detector running. Press Q in the video window to stop.")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("Stream ended or a frame could not be read.")
                break

            started_at = time.perf_counter()
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            inputs = processor(images=rgb_frame, return_tensors="pt").to(device)

            amp_context = (
                torch.autocast(device_type="cuda", dtype=torch.float16)
                if args.half
                else nullcontext()
            )
            with torch.inference_mode(), amp_context:
                outputs = model(**inputs)

            height, width = frame.shape[:2]
            target_sizes = torch.tensor([[height, width]], device=device)
            result = processor.post_process_object_detection(
                outputs,
                threshold=args.threshold,
                target_sizes=target_sizes,
            )[0]

            result = {key: value.detach().cpu() for key, value in result.items()}
            detection_count = draw_detections(
                frame, result, model.config.id2label, allowed_classes
            )

            elapsed = max(time.perf_counter() - started_at, 1e-6)
            current_fps = 1.0 / elapsed
            smoothed_fps = (
                current_fps if smoothed_fps == 0.0 else 0.9 * smoothed_fps + 0.1 * current_fps
            )
            status = (
                f"{device.type.upper()} | {smoothed_fps:.1f} FPS | "
                f"{elapsed * 1000:.0f} ms | {detection_count} objects"
            )
            cv2.putText(
                frame,
                status,
                (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

            cv2.imshow("PitDivers - Live Object Detection", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
