"""開発サーバー: ビルドして配信し、ソースが変わったら自動で再ビルドする。"""

from __future__ import annotations

import functools
import os
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from build import ROOT, build

OUT = Path(os.environ.get("BUILD_DIR", "/data/dist"))
PORT = int(os.environ.get("PORT", "8000"))
WATCH = [ROOT / "web", ROOT / "hanafuda"]


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".wasm": "application/wasm",
        ".webmanifest": "application/manifest+json",
    }

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # アクセスログは出さない


def snapshot() -> dict[Path, float]:
    return {p: p.stat().st_mtime for d in WATCH for p in d.rglob("*") if p.is_file()}


def watch() -> None:
    last = snapshot()
    while True:
        time.sleep(1)
        now = snapshot()
        if now != last:
            last = now
            try:
                print(f"rebuilt (version {build(OUT)})", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"build failed: {e}", flush=True)


def main() -> None:
    print(f"built (version {build(OUT)})", flush=True)
    threading.Thread(target=watch, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), functools.partial(Handler, directory=str(OUT)))
    print(f"serving http://localhost:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
