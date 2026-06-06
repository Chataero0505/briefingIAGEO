#!/usr/bin/env python3
"""
main.py — Punto de entrada. Hace todo de principio a fin:
  1) Lee tus fuentes (sources.yaml) y el estado anterior (state/state.json)
  2) Recoge lo nuevo de cada fuente, sin duplicados exactos
  3) Agrupa por hecho y resume en español con Gemini
  4) Genera docs/index.html (lo que abres en el móvil)
  5) Guarda el estado para la próxima vez

Se ejecuta solo en GitHub Actions cada mañana. Tú no tienes que correrlo a mano.
"""

import json
import pathlib
import datetime as dt

import yaml

from aggregator.fetch import collect
from aggregator.summarize import build_digest
from aggregator.render import render

ROOT = pathlib.Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    print(f"== Briefing · {dt.datetime.now():%Y-%m-%d %H:%M} ==")

    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    sources = cfg.get("sources", [])
    settings = cfg.get("settings", {})
    model = settings.get("model", "gemini-2.5-flash")
    detalle = settings.get("resumen_detalle", "detallado")
    print(f"Fuentes configuradas: {len(sources)} · modelo: {model} · detalle: {detalle}")

    state = load_state()

    print("\n[1/3] Recogiendo novedades…")
    items = collect(sources, settings, state)
    print(f"   = {len(items)} noticias nuevas en total.")

    if items:
        print("\n[2/3] Agrupando y resumiendo con Gemini…")
        digest = build_digest(items, model, detalle=detalle)
    else:
        print("\n[2/3] No hay novedades; mantengo el briefing anterior vacío.")
        digest = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "count": 0, "top": [], "stories": []}

    print("\n[3/3] Generando la página…")
    render(digest)

    save_state(state)
    print("\nListo. ✅")


if __name__ == "__main__":
    main()
