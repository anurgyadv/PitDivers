from __future__ import annotations

import json
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


class RoverControlError(RuntimeError):
    pass


# Direction and STOP requests can arrive from separate FastAPI worker threads.
# Serializing them guarantees a release/STOP cannot be overtaken by an older
# hold-to-drive refresh that was still in flight.
rover_command_lock = threading.Lock()


def normalize_rover_url(value: str) -> str:
    """Return a safe controller origin such as http://192.168.0.70."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a valid HTTP rover controller URL")
    if parsed.username or parsed.password:
        raise ValueError("Rover controller URLs cannot contain credentials")
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def rover_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 1.5,
) -> dict[str, Any]:
    origin = normalize_rover_url(base_url)
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{origin}/{path.lstrip('/')}{query}",
        method=method,
        headers={"Accept": "application/json, text/plain", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get_content_type()
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("error", raw)
        except (json.JSONDecodeError, AttributeError):
            detail = raw
        raise RoverControlError(detail or f"Rover returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RoverControlError(f"Rover controller unavailable: {exc}") from exc

    if content_type == "application/json":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RoverControlError("Rover returned invalid JSON") from exc
        if isinstance(payload, dict):
            return payload
    return {"ok": True, "response": raw.strip()}


def corrected_drive_request(base_url: str, command: str, speed: int) -> dict[str, Any]:
    """Use the signed wheel channels shared with mapping/drive_commands.py."""
    signs = {"forward": (1, 1), "backward": (-1, -1),
             "left": (-1, 1), "right": (1, -1)}
    if command == "stop":
        return rover_request(base_url, "/stop")
    if command not in signs or not 80 <= speed <= 255:
        raise ValueError("Invalid drive command or speed")
    a, b = signs[command]
    try:
        return rover_request(base_url, "/api/wheels", method="POST",
                             params={"a": a * speed, "b": b * speed})
    except RoverControlError as exc:
        if "404" in str(exc) or "not found" in str(exc).lower():
            raise RoverControlError("The rover needs the updated signed-wheel firmware for corrected manual controls") from exc
        raise
