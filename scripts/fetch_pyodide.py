"""Pyodide 本体（ブラウザで動く Python）を取得する。取得済みなら何もしない（オフライン可）。"""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

PYODIDE_VERSION = "314.0.7"
FILES = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
BASE_URL = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"


def pyodide_dir() -> Path:
    return Path(os.environ.get("PYODIDE_DIR", "/data/pyodide")) / PYODIDE_VERSION


def main() -> int:
    dest = pyodide_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.exists():
            continue
        print(f"downloading {name} ...", flush=True)
        tmp = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(BASE_URL + name, tmp)
        tmp.rename(target)
    print(f"Pyodide {PYODIDE_VERSION} ready: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
