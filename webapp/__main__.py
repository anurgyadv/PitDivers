from __future__ import annotations

import argparse
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def dashboard_is_running(url: str) -> bool:
    """Recognize an existing PitDivers instance before attempting to bind."""
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            page = response.read(4096).decode("utf-8", errors="ignore")
        return response.status == 200 and "PitDivers" in page
    except Exception:
        return False


def open_dashboard_when_ready(url: str) -> None:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=0.5):
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(0.25)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the PitDivers dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"

    print("PitDivers Rover Vision Console")
    if dashboard_is_running(url):
        print(f"Dashboard is already running at {url}; opening the existing instance.")
        if not args.no_browser:
            webbrowser.open(url)
        return
    print(f"Opening {url}")
    print("Keep this window open while using the dashboard. Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Thread(target=open_dashboard_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("webapp.app:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
