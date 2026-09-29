from __future__ import annotations

import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from .rover_control import RoverControlError, normalize_rover_url, rover_request


class GamepadBridgeManager:
    """Run the fixed project gamepad bridge as one managed background process."""

    def __init__(self, script_path: Path) -> None:
        self.script_path = script_path.resolve()
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._rover_url: str | None = None
        self._started_at: str | None = None
        self._last_exit_code: int | None = None
        self._error: str | None = None

    def start(self, rover_url: str, api_key: str, max_speed: int) -> dict:
        origin = normalize_rover_url(rover_url)
        if not api_key.strip():
            raise ValueError("Enter the motion ESP API key")
        if not self.script_path.is_file():
            raise RuntimeError(f"Gamepad bridge is missing: {self.script_path}")

        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("The gamepad bridge is already running")

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script_path),
                "-Rover",
                origin,
                "-ApiKey",
                api_key,
                "-MaxSpeed",
                str(max_speed),
            ]
            try:
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
            except OSError as exc:
                self._error = str(exc)
                raise RuntimeError(f"Could not start PowerShell gamepad bridge: {exc}") from exc

            self._rover_url = origin
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._last_exit_code = None
            self._error = None
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            process = self._process
            rover_url = self._rover_url

        if rover_url:
            try:
                rover_request(rover_url, "/stop", timeout=0.6)
            except (ValueError, RoverControlError):
                pass

        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)

        if rover_url:
            try:
                rover_request(rover_url, "/mode", method="POST", params={"value": "human"}, timeout=0.6)
            except (ValueError, RoverControlError):
                pass

        with self._lock:
            if process is not None:
                self._last_exit_code = process.poll()
            self._process = None
            self._rover_url = None
            self._started_at = None
            return self.status()

    def status(self) -> dict:
        with self._lock:
            running = self._process is not None and self._process.poll() is None
            if self._process is not None and not running:
                self._last_exit_code = self._process.returncode
                self._process = None
            return {
                "running": running,
                "pid": self._process.pid if running and self._process is not None else None,
                "rover_url": self._rover_url if running else None,
                "started_at": self._started_at if running else None,
                "last_exit_code": self._last_exit_code,
                "script_exists": self.script_path.is_file(),
                "error": self._error,
            }
