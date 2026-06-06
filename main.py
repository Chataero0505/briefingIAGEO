#!/usr/bin/env python3
"""
main.py — Punto de entrada. Hace todo de principio a fin:
  1) Lee fuentes (sources.yaml) y estado anterior (state/state.json)
  2) Recoge novedades (sin duplicados) y mide la salud de cada fuente
  3) Agrupa, puntúa y resume en tu idioma con Gemini
  4) Genera docs/index.html (el briefing) y docs/estado.html (salud)
  5) Guarda el estado para la próxima vez

Si un día no hay novedades, NO borra el briefing anterior.
"""

import json
import pathlib
import datetime as dt

import yaml

from aggregator.fetch import collect
from aggregator.summarize import build_digest
from aggregator.render import render, render_status

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
    idioma = settings.get("output_language", "español (castellano)")
    intereses = settings.get("mis_intereses", "")
    if isinstance(intereses, list):
        intereses = ", ".join(intereses)
    print(f"Fuentes: {len(sources)} · modelo: {model} · detalle: {detalle}")

    state = load_state()

    print("\n[1/3] Recogiendo novedades y midiendo salud de fuentes…")
    items, report = collect(sources, settings, state)
    print(f"   = {len(items)} noticias nuevas en total.")

    print("\n[2/3] Procesando con Gemini…")
    if items:
        digest = build_digest(items, model, detalle=detalle,
                              intereses=intereses, output_language=idioma)
        render(digest)
    else:
        print("   Sin novedades: mantengo el briefing anterior intacto.")

    print("\n[3/3] Generando página de estado…")
    render_status(report)

    save_state(state)
    print("\nListo. ✅")


if __name__ == "__main__":
    main()
