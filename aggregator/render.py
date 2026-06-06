"""
render.py — Genera las páginas que se publican.
- render(): el briefing (docs/index.html), con el JSON blindado.
- render_status(): la página de salud de fuentes (docs/estado.html).
"""

from __future__ import annotations
import json
import html as _html
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "index.html"
OUTPUT = ROOT / "docs" / "index.html"
STATUS_OUT = ROOT / "docs" / "estado.html"


def _safe_json(obj) -> str:
    """JSON seguro para incrustar dentro de <script> (evita romper con </script>, etc.)."""
    return (json.dumps(obj, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def render(digest: dict) -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__DIGEST_DATA__", _safe_json(digest))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"   · Escrito docs/index.html con {digest.get('count', 0)} hechos.")


def _fmt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return dt.datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except Exception:
        return iso[:16]


def render_status(report: list) -> None:
    orden = {"error": 0, "sin_feed": 1, "sin_novedades": 2, "ok": 3}
    rows = sorted(report, key=lambda r: (orden.get(r["status"], 9), -r["new"], r["name"].lower()))
    label = {"ok": "OK", "sin_novedades": "Sin novedades", "sin_feed": "Sin feed", "error": "Error"}
    color = {"ok": "#36c98e", "sin_novedades": "#9aa3b8", "sin_feed": "#f0a13c", "error": "#ef5b6b"}

    n_ok = sum(1 for r in report if r["status"] in ("ok", "sin_novedades"))
    n_bad = sum(1 for r in report if r["status"] in ("error", "sin_feed"))
    n_new = sum(r["new"] for r in report)

    trs = []
    for r in rows:
        c = color.get(r["status"], "#9aa3b8")
        note = _html.escape(r.get("note", "") or "")
        trs.append(
            f"<tr><td>{_html.escape(r['name'])}</td>"
            f"<td class='dim'>{r['type']}</td><td class='dim'>{r['topic']}</td>"
            f"<td><span class='dot' style='background:{c}'></span>{label.get(r['status'], r['status'])}</td>"
            f"<td class='num'>{r['new']}</td>"
            f"<td class='dim'>{_fmt(r.get('last_success',''))}</td>"
            f"<td class='note'>{note}</td></tr>")

    page = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estado de las fuentes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600&family=Spline+Sans:wght@400;500&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0c0d12;--card:#161924;--ink:#eef1f8;--muted:#9aa3b8;--faint:#5b6378;--line:#272c3a}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font-family:"Spline Sans",sans-serif;padding:28px 16px 60px}}
.wrap{{max-width:820px;margin:0 auto}}
a.back{{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--muted);text-decoration:none}}
h1{{font-family:"Fraunces",serif;font-weight:600;font-size:30px;margin:10px 0 4px}}
.sub{{font-family:"JetBrains Mono",monospace;font-size:12px;color:var(--faint);margin-bottom:18px}}
.cards{{display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;flex:1;min-width:120px}}
.kpi b{{font-family:"Fraunces",serif;font-size:26px;display:block}}
.kpi span{{font-size:12px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:10px 12px;font-size:13.5px;border-bottom:1px solid var(--line)}}
th{{font-family:"JetBrains Mono",monospace;font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}}
tr:last-child td{{border-bottom:0}}
.dim{{color:var(--muted)}} .num{{text-align:center;font-family:"JetBrains Mono",monospace}}
.note{{color:var(--faint);font-size:12px}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:middle}}
</style></head><body><div class="wrap">
<a class="back" href="index.html">← Volver al briefing</a>
<h1>Estado de las fuentes</h1>
<div class="sub">Última comprobación: {dt.datetime.now().strftime('%d/%m/%Y %H:%M')}</div>
<div class="cards">
  <div class="kpi"><b>{len(report)}</b><span>fuentes</span></div>
  <div class="kpi"><b style="color:#36c98e">{n_ok}</b><span>funcionando</span></div>
  <div class="kpi"><b style="color:#ef5b6b">{n_bad}</b><span>con problemas</span></div>
  <div class="kpi"><b>{n_new}</b><span>noticias nuevas</span></div>
</div>
<table><thead><tr><th>Fuente</th><th>Tipo</th><th>Tema</th><th>Estado</th><th>Nuevas</th><th>Último éxito</th><th>Nota</th></tr></thead>
<tbody>{''.join(trs)}</tbody></table>
</div></body></html>"""
    STATUS_OUT.write_text(page, encoding="utf-8")
    print(f"   · Escrito docs/estado.html ({n_bad} fuentes con problemas).")
