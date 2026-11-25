"""Regenerate docs/diagrams/er-core.{svg,png} from db/schema.dbml.

    python scripts/render_er.py

The diagram shows the seven core tables with their relationships. Enumerations
are removed from the picture (they are listed as tables in the design document)
so the relationship lines stay readable. db/schema.dbml itself keeps the enums,
which dbdiagram.io renders nicely for the interactive version.

Rendering uses kroki.io (Graphviz) because it keeps font metrics consistent.
The script falls back to the local dbml-renderer SVG when there is no network.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DBML = ROOT / "db" / "schema.dbml"
OUT_DIR = ROOT / "docs" / "diagrams"
BUILD_DIR = ROOT / "build"

ENUM_BLOCK = re.compile(r"^Enum \w+ \{.*?^\}\n", re.MULTILINE | re.DOTALL)


def render_with_kroki(dot_path: Path, fmt: str) -> bytes:
    target = BUILD_DIR / f"er-core.{fmt}"
    curl = shutil.which("curl")
    if curl:
        subprocess.run(
            [
                curl, "-sS", "-A", "Mozilla/5.0", "-X", "POST",
                "-H", "Content-Type: text/plain",
                "--data-binary", f"@{dot_path}",
                f"https://kroki.io/graphviz/{fmt}",
                "-o", str(target), "--max-time", "120",
            ],
            check=True,
        )
        return target.read_bytes()

    request = urllib.request.Request(
        f"https://kroki.io/graphviz/{fmt}",
        data=dot_path.read_bytes(),
        headers={"Content-Type": "text/plain", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def main() -> int:
    npx = shutil.which("npx")
    if not npx:
        print("npx not found: install Node.js to render the diagram.", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(exist_ok=True)

    # Tables only: keep the ER readable, list enums in prose instead.
    dbml = ENUM_BLOCK.sub("", DBML.read_text(encoding="utf-8"))
    dbml_path = BUILD_DIR / "er-core.dbml"
    dbml_path.write_text(dbml, encoding="utf-8")

    dot = subprocess.run(
        [npx, "-y", "@softwaretechnik/dbml-renderer", "-i", str(dbml_path), "-f", "dot"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    dot = (
        dot.replace("fontsize=32", "fontsize=12")
        .replace("penwidth=3", "penwidth=1.2")
        .replace('CELLPADDING="10"', 'CELLPADDING="6"')
        .replace('bgcolor="transparent"', 'bgcolor="white"')
        .replace('fontname="helvetica"', 'fontname="DejaVu Sans"')
    )
    (BUILD_DIR / "er-core.dot").write_text(dot, encoding="utf-8")

    try:
        for fmt in ("svg", "png"):
            data = render_with_kroki(BUILD_DIR / "er-core.dot", fmt)
            (OUT_DIR / f"er-core.{fmt}").write_bytes(data)
            print(f"wrote docs/diagrams/er-core.{fmt} ({len(data):,} bytes)")
    except Exception as exc:  # noqa: BLE001 - offline fallback
        print(f"kroki.io unavailable ({exc}); writing local SVG instead.", file=sys.stderr)
        subprocess.run(
            [npx, "-y", "@softwaretechnik/dbml-renderer", "-i", str(dbml_path),
             "-o", str(OUT_DIR / "er-core.svg")],
            check=True,
        )
        print("wrote docs/diagrams/er-core.svg (run again with network for the PNG)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
