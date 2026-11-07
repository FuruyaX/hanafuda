"""web/ と hanafuda/ と Pyodide をまとめて、静的サイト（PWA）を出力する。

    python scripts/build.py [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_pyodide import FILES as PYODIDE_FILES, pyodide_dir  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ---- アイコン（外部ライブラリなしで PNG を生成） ----
def _png(size: int) -> bytes:
    """緑の地に和紙色の札、赤い月（光札の意匠）を描いたアイコン。"""
    felt, washi, red, edge = (31, 77, 43), (247, 240, 225), (179, 38, 30), (59, 45, 32)
    cw, ch = size * 0.50, size * 0.72
    x0, y0 = (size - cw) / 2, (size - ch) / 2
    cx, cy, r = size / 2, y0 + ch * 0.40, cw * 0.30
    border = max(2, size // 64)
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            if x0 <= x < x0 + cw and y0 <= y < y0 + ch:
                inner = x0 + border <= x < x0 + cw - border and y0 + border <= y < y0 + ch - border
                if not inner:
                    color = edge
                elif (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    color = red
                else:
                    color = washi
            else:
                color = felt
            row.extend(color)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def _copy_if_changed(src: Path, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build(out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    expected: set[str] = set()

    def put(src: Path, rel: str) -> None:
        _copy_if_changed(src, out / rel)
        expected.add(rel)

    # Pyodide
    pdir = pyodide_dir()
    missing = [f for f in PYODIDE_FILES if not (pdir / f).exists()]
    if missing:
        raise SystemExit(f"Pyodide がありません: {missing}。先に scripts/fetch_pyodide.py を実行してください")
    for f in PYODIDE_FILES:
        put(pdir / f, f"pyodide/{f}")

    # Web ファイル（sw.js は最後に生成）
    for src in (ROOT / "web").iterdir():
        if src.is_file() and src.name != "sw.js":
            put(src, src.name)

    # Python パッケージ
    py_files = ["main.py"]
    for src in sorted((ROOT / "hanafuda").glob("*.py")):
        put(src, f"hanafuda/{src.name}")
        py_files.append(f"hanafuda/{src.name}")
    (out / "app-files.json").write_text(json.dumps(py_files), encoding="utf-8")
    expected.add("app-files.json")

    # アイコン
    for size in (180, 192, 512):
        icon = out / "icons" / f"icon-{size}.png"
        if not icon.exists():
            icon.parent.mkdir(parents=True, exist_ok=True)
            icon.write_bytes(_png(size))
        expected.add(f"icons/icon-{size}.png")

    # 削除されたソースの残骸を消す
    for p in list(out.rglob("*")):
        if p.is_file() and p.relative_to(out).as_posix() not in expected | {"sw.js"}:
            p.unlink()

    # Service Worker: 全ファイルのハッシュをバージョンにする（変更があれば更新される）
    assets = sorted(expected)
    digest = hashlib.sha256()
    for a in assets:
        digest.update(a.encode())
        digest.update((out / a).read_bytes())
    version = digest.hexdigest()[:12]
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    sw = sw.replace("__VERSION__", version).replace("__ASSETS__", json.dumps(["./"] + [f"./{a}" for a in assets]))
    (out / "sw.js").write_text(sw, encoding="utf-8")
    return version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.environ.get("BUILD_DIR", "/data/dist"))
    args = parser.parse_args()
    version = build(Path(args.out))
    print(f"built {args.out} (version {version})")


if __name__ == "__main__":
    main()
