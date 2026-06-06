"""
render.py — Mete el briefing del día dentro de la plantilla HTML.
Escribe docs/index.html, que es lo que se publica y abres en el móvil/PC.
"""

from __future__ import annotations
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "index.html"
OUTPUT = ROOT / "docs" / "index.html"


def render(digest: dict) -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(digest, ensure_ascii=False)
    html = html.replace("__DIGEST_DATA__", data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"   · Escrito {OUTPUT.relative_to(ROOT)} con {digest.get('count', 0)} hechos.")
