from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np


MODEL_PATH = Path(__file__).resolve().parent / "models" / "scunet_color_real_psnr.onnx"


class LowLightProcessor:
    """Fast classical enhancement plus optional SCUNet neural denoising."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: Any = None
        self._input_name = "image"
        self.provider = "none"
        self._previous: np.ndarray | None = None
        self.mode = "off"
        self.strength = 55
        self.model_state = "idle"
        self.error: str | None = None
        self.last_ms = 0.0

    def configure(self, mode: str, strength: int) -> None:
        if mode not in {"off", "fast", "ai"}:
            raise ValueError("Low-light mode must be off, fast, or ai")
        with self._lock:
            if mode != self.mode:
                self._previous = None
            self.mode = mode
            self.strength = max(0, min(100, int(strength)))
            self.error = None
            if mode == "off":
                self.model_state = "idle"
            elif mode == "fast":
                self.model_state = "ready"
            elif self._session is None:
                self.model_state = "loading"

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "strength": self.strength,
                "model_state": self.model_state,
                "provider": self.provider,
                "error": self.error,
                "processing_ms": round(self.last_ms),
            }

    def reset(self) -> None:
        with self._lock:
            self._previous = None
            self.error = None
            self.last_ms = 0.0

    def process(self, frame: np.ndarray) -> np.ndarray:
        with self._lock:
            mode = self.mode
            strength = self.strength
        if mode == "off" or strength <= 0:
            return frame

        started = time.perf_counter()
        try:
            if mode == "ai":
                denoised = self._neural_denoise(frame)
                output = self._enhance_illumination(denoised, strength)
            else:
                output = self._fast_enhance(frame, strength)
            with self._lock:
                self.error = None
                self.last_ms = (time.perf_counter() - started) * 1000.0
            return output
        except Exception as exc:
            # Keep the rover view usable if the neural runtime/model fails.
            fallback = self._fast_enhance(frame, strength)
            with self._lock:
                self.model_state = "error"
                self.error = f"AI denoiser unavailable; using Fast mode: {exc}"
                self.last_ms = (time.perf_counter() - started) * 1000.0
            return fallback

    def _fast_enhance(self, frame: np.ndarray, strength: int) -> np.ndarray:
        amount = strength / 100.0
        spatial = cv2.bilateralFilter(frame, 5, 18 + 34 * amount, 18 + 34 * amount)
        with self._lock:
            previous = self._previous
            self._previous = spatial.copy()
        if previous is not None and previous.shape == spatial.shape:
            motion = float(cv2.mean(cv2.absdiff(spatial, previous))[0])
            temporal_weight = max(0.0, min(0.42 * amount, (16.0 - motion) / 40.0))
            if temporal_weight > 0:
                spatial = cv2.addWeighted(spatial, 1.0 - temporal_weight, previous, temporal_weight, 0)
        enhanced = self._enhance_illumination(spatial, strength)
        return cv2.addWeighted(frame, 1.0 - 0.82 * amount, enhanced, 0.82 * amount, 0)

    @staticmethod
    def _enhance_illumination(frame: np.ndarray, strength: int) -> np.ndarray:
        amount = strength / 100.0
        gamma = 1.0 - 0.48 * amount
        lut = np.clip(((np.arange(256, dtype=np.float32) / 255.0) ** gamma) * 255.0, 0, 255).astype(np.uint8)
        brightened = cv2.LUT(frame, lut)
        lab = cv2.cvtColor(brightened, cv2.COLOR_BGR2LAB)
        light, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=1.0 + 1.8 * amount, tileGridSize=(8, 8))
        light = clahe.apply(light)
        return cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2BGR)

    def _load_session(self) -> Any:
        with self._lock:
            if self._session is not None:
                return self._session
            if not MODEL_PATH.is_file() or not MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".data").is_file():
                raise FileNotFoundError("SCUNet model files are missing")
            self.model_state = "loading"
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.log_severity_level = 3
        session = ort.InferenceSession(
            str(MODEL_PATH),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        with self._lock:
            self._session = session
            self._input_name = session.get_inputs()[0].name
            self.provider = "cpu"
            self.model_state = "ready"
        return session

    def _neural_denoise(self, frame: np.ndarray) -> np.ndarray:
        session = self._load_session()
        height, width = frame.shape[:2]
        # A 256 px neural working size keeps CPU inference near interactive
        # rates; the full-resolution original remains available in the UI.
        scale = min(1.0, 256.0 / max(height, width))
        small_w = max(64, int(round(width * scale / 64.0)) * 64)
        small_h = max(64, int(round(height * scale / 64.0)) * 64)
        small = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])
        output = session.run(None, {self._input_name: tensor})[0][0]
        output = np.clip(output.transpose(1, 2, 0) * 255.0, 0, 255).astype(np.uint8)
        denoised = cv2.cvtColor(output, cv2.COLOR_RGB2BGR)
        return cv2.resize(denoised, (width, height), interpolation=cv2.INTER_CUBIC)
