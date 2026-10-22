"""Projecute — main entry point.

Run `python main.py` to start the web app, then open http://127.0.0.1:8000.
The FastAPI application itself lives in app/main.py; this file only starts the
server. On a fresh database the demo team and project are staged automatically.

Environment variables (all optional):
  HOST            address to listen on (default 127.0.0.1; the Docker image uses 0.0.0.0)
  PORT            port to listen on (default 8000; Hugging Face Spaces uses 7860)
  GROQ_API_KEY    enables live AI; without it the app runs in labelled demo mode
  DEMO_PASSCODE   when set, "Load demo" asks for it before resetting the data
  OPEN_BROWSER    when set to 1, opens the app in your browser once it is ready
"""
import os
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def open_when_ready(url: str) -> None:
    """Wait until the server answers (the first start loads the AI model), then open the browser."""
    for _ in range(180):
        try:
            urllib.request.urlopen(url, timeout=2)
            webbrowser.open(url)
            return
        except Exception:
            time.sleep(1)


def main() -> None:
    """Start the Projecute web server."""
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    print(f"Projecute is starting on {url}  (the first start takes about a minute)")
    if os.environ.get("OPEN_BROWSER") == "1":
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
