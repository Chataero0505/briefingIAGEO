"""
summarize.py — Capa de IA (Gemini, gratis).

  1) AGRUPAR: junta items del MISMO hecho (no se repite nada).
  2) RESUMIR + PUNTUAR: por cada grupo, resumen en español, importancia general,
     RELEVANCIA para TUS intereses, si es NOTICIA (filtro de ruido) y si es CRUCE IA-geo.
  3) RESUMEN DEL DÍA: un texto corto con lo más importante.
  4) DESTACAR: marca los hechos top por relevancia.
"""

from __future__ import annotations
import os
import json
import time
import hashlib
import datetime as dt

from google import genai
from google.genai import types

from .fetch import Item

_client = None


class _DailyQuotaExceeded(Exception):
    """Se ha agotado la cuota DIARIA de Gemini: reintentar no sirve de nada."""
    pass

SUBTEMAS_IA = ["Modelos", "Herramientas/Agentes", "Empresas", "Investigación",
               "IA China", "Regulación", "Uso profesional/Industria"]
SUBTEMAS_GEO = ["Europa", "EE. UU.", "China/Asia", "Defensa/Conflictos", "Energía", "Economía"]

DETALLE = {
    "breve": "1-2 frases, muy al grano.",
    "normal": "un párrafo de 3-5 frases.",
    "detallado": "2-3 párrafos. Primer párrafo: qué ha pasado con datos y nombres concretos. "
                 "Segundo: contexto y antecedentes. Tercero (si aplica): implicaciones y qué "
                 "vigilar. Separa los párrafos con una línea en blanco.",
}


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Falta la variable GEMINI_API_KEY (la clave de Gemini).")
        _client = genai.Client(api_key=key)
    return _client


def _generate(model, prompt, as_json=True, retries=5):
    client = _get_client()
    cfg = types.GenerateContentConfig(
        response_mime_type="application/json" if as_json else "text/plain",
        max_output_tokens=8192,
        temperature=0.3)
    for attempt in range(retries):
        try:
            return _get_client().models.generate_content(
                model=model, contents=prompt, config=cfg).text or ""
        except Exception as e:
            msg = str(e).lower()
            is_429 = "429" in msg or "resource" in msg or "rate" in msg or "quota" in msg
            is_overload = ("503" in msg or "unavailable" in msg or "overloaded" in msg
                           or "high demand" in msg)
            # Límite DIARIO agotado: insistir no sirve, se reinicia a medianoche (hora del Pacífico).
            if is_429 and ("perday" in msg or "per day" in msg or "requests per day" in msg
                           or "generaterequestsperday" in msg):
                print("   [!] Cuota DIARIA de Gemini agotada. Me quedo con lo ya generado.")
                raise _DailyQuotaExceeded()
            # Saturación temporal del modelo (503) o límite por minuto: esperar y reintentar.
            if (is_429 or is_overload) and attempt < retries - 1:
                wait = 15 * (attempt + 1)
                motivo = "Modelo saturado" if is_overload else "Límite por minuto"
                print(f"   [i] {motivo}, reintento en {wait}s…")
                time.sleep(wait)
                continue
            print(f"   [!] Error de Gemini: {e}")
            return ""
    return ""


def _parse_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("` \n")
    try:
        return json.loads(text)
    except Exception:
        for o, c in (("[", "]"), ("{", "}")):
            i, j = text.find(o), text.rfind(c)
            if i != -1 and j != -1:
                try:
                    return json.loads(text[i:j + 1])
                except Exception:
                    pass
    return None


def cluster(items, model):
    if not items:
        return []
    listing = "\n".join(
        f'{i}. [{it.topic_hint}] ({it.source_name}) {it.title} :: {it.snippet[:160]}'
        for i, it in enumerate(items))
    prompt = f"""Eres un editor de noticias. Abajo hay una lista numerada de noticias/vídeos
sobre Inteligencia Artificial y/o Geopolítica, de fuentes distintas y en varios idiomas.

Agrupa las que tratan EXACTAMENTE EL MISMO hecho o anuncio concreto, aunque las cuenten
medios diferentes. Sé CONSERVADOR: si dudas, déjalas separadas. Cada noticia va en un único
grupo; las que no se parezcan a ninguna forman grupo de un solo elemento.

Asigna tema a cada grupo: "ia" o "geo" (el que predomine).

Devuelve SOLO un JSON: [{{"indices":[0,4],"topic":"ia"}}, {{"indices":[1],"topic":"geo"}}]

Lista:
{listing}
"""
    data = _parse_json(_generate(model, prompt))
    if not isinstance(data, list):
        return [{"indices": [i], "topic": it.topic_hint} for i, it in enumerate(items)]
    groups, used = [], set()
    for g in data:
        idxs = [i for i in g.get("indices", []) if isinstance(i, int) and 0 <= i < len(items) and i not in used]
        if idxs:
            used.update(idxs)
            groups.append({"indices": idxs, "topic": g.get("topic", items[idxs[0]].topic_hint)})
    for i, it in enumerate(items):
        if i not in used:
            groups.append({"indices": [i], "topic": it.topic_hint})
    return groups


def summarize_groups(groups, items, model, detalle="detallado", intereses="",
                     output_language="español (castellano)", batch_size=6):
    instruccion = DETALLE.get(detalle, DETALLE["detallado"])
    intereses_txt = intereses.strip() or "tecnología, IA y geopolítica en general"
    lista_ia = ", ".join(SUBTEMAS_IA)
    lista_geo = ", ".join(SUBTEMAS_GEO)
    stories = []
    for start in range(0, len(groups), batch_size):
        batch = groups[start:start + batch_size]
        blocks = []
        for n, g in enumerate(batch):
            srcs = [items[i] for i in g["indices"]]
            txt = "\n".join(f"  - ({s.source_name}) {s.title}\n    {(s.body or s.snippet)[:1400]}" for s in srcs)
            blocks.append(f"GRUPO {n} (tema={g['topic']}):\n{txt}")
        joined = "\n\n".join(blocks)
        prompt = f"""Eres el redactor de un boletín diario en {output_language}
para un lector con estos INTERESES: {intereses_txt}.

Abajo hay GRUPOS de noticias; cada grupo es UN solo hecho contado por una o más fuentes.

Para CADA grupo devuelve, SIEMPRE en {output_language} aunque las fuentes estén en otro idioma:
- "titular": titular claro.
- "resumen": {instruccion} Sintetiza todas las fuentes sin repetir. Neutral, concreto
  (cifras, nombres, fechas si aparecen). No inventes datos que no estén.
- "por_que_importa": 1 frase de relevancia.
- "importancia": 1-5 (impacto general de la noticia).
- "relevancia": 1-5 (cuánto encaja con los INTERESES de arriba; 5 = totalmente).
- "es_noticia": true SOLO si es un hecho o novedad informativa real. Pon false si es contenido
  promocional o patrocinado, sorteos, clickbait, tutoriales genéricos, listas de "mejores
  herramientas", publicaciones de foro o comunidad, hilos de dudas o preguntas de usuarios,
  logística de un hackathon o concurso, o cualquier cosa sin valor periodístico.
- "categoria": clasifica el hecho en EXACTAMENTE una de estas tres, según su TEMA CENTRAL:
    · "ia"    = el núcleo es la inteligencia artificial en sí: modelos, laboratorios y empresas
                de IA, investigación, productos y herramientas, una startup de IA y su valoración,
                un chip nuevo para IA visto como producto, etc.
    · "geo"   = el núcleo es geopolítica, economía, política, defensa o sociedad SIN que la IA sea
                protagonista: una divisa que se desploma, una elección, un conflicto, sanciones,
                energía o comercio no ligados a la IA, etc.
    · "cruce" = SOLO si la IA es a la vez el asunto Y tiene una dimensión geopolítica o de política
                económica de PRIMER PLANO: guerra de semiconductores y control de exportación de
                chips, soberanía tecnológica, IA militar, regulación estatal de la IA con peso
                geopolítico, energía para centros de datos como cuestión estratégica. NO uses
                "cruce" solo porque se mencionen ambos de pasada: debe ser el eje de la noticia.
                Ante la duda, elige "ia" o "geo", nunca "cruce".
- "subtema": elige el que mejor encaje de [{lista_ia}] o de [{lista_geo}]; si ninguno, "Otros".
- "etiquetas": 2-4 etiquetas cortas.

Devuelve SOLO un JSON (lista), un objeto por grupo y EN EL MISMO ORDEN.

{joined}
"""
        try:
            data = _parse_json(_generate(model, prompt))
        except _DailyQuotaExceeded:
            print(f"   [!] Cuota agotada; me quedo con {len(stories)} hechos ya resumidos.")
            break
        # Emparejar por orden lo que devuelva el modelo; si faltan objetos, relleno SOLO
        # esos (no se pierde el lote entero por un desajuste de longitud).
        if not isinstance(data, list):
            data = []
        data = (list(data) + [{}] * len(batch))[:len(batch)]
        for g, res in zip(batch, data):
            if not isinstance(res, dict):
                res = {}
            if res.get("es_noticia") is False:
                continue  # filtro de ruido
            srcs = [items[i] for i in g["indices"]]
            first = srcs[0]
            # Categoría tri-estado: ia / geo / cruce (con fallback robusto)
            cat = res.get("categoria")
            if cat not in ("ia", "geo", "cruce"):
                cat = "cruce" if res.get("cruce") else (
                    g["topic"] if g["topic"] in ("ia", "geo") else first.topic_hint)
            topic = g["topic"] if g["topic"] in ("ia", "geo") else first.topic_hint
            if cat in ("ia", "geo"):
                topic = cat
            image = next((s.image for s in srcs if s.image), "")
            sid = hashlib.md5("|".join(sorted(s.key() for s in srcs)).encode()).hexdigest()[:10]
            # Ordena fuentes: primero las primarias (oficial/blog), luego medios, luego vídeo
            order = {"blog": 0, "newsletter": 1, "youtube": 2}
            srcs_sorted = sorted(srcs, key=lambda s: order.get(s.source_type, 1))
            stories.append({
                "id": sid,
                "category": cat,
                "topic": topic,
                "subtopic": res.get("subtema") or "Otros",
                "cruce": cat == "cruce",
                "title": res.get("titular") or first.title,
                "summary": res.get("resumen") or (first.body or first.snippet)[:400],
                "why": res.get("por_que_importa", ""),
                "importance": int(res.get("importancia", 2) or 2),
                "relevance": int(res.get("relevancia", 2) or 2),
                "tags": res.get("etiquetas", [])[:4],
                "image": image,
                "published": max(s.published for s in srcs).isoformat(),
                "sources": [{"name": s.source_name, "url": s.url, "type": s.source_type} for s in srcs_sorted],
            })
        time.sleep(4)
    stories.sort(key=lambda s: (s["relevance"], s["importance"], s["published"]), reverse=True)
    return stories


def daily_brief(stories, model, intereses="", output_language="español (castellano)"):
    if not stories:
        return ""
    top = stories[:15]
    lines = "\n".join(f"- [{s['topic']}] {s['title']}" for s in top)
    intereses_txt = intereses.strip() or "IA y geopolítica"
    prompt = f"""Eres el editor de un boletín. Con estos titulares del día, escribe en {output_language}
un resumen ejecutivo de 3-5 frases ("el día en 60 segundos") para alguien interesado en
{intereses_txt}. Destaca lo más importante de IA y de geopolítica y, si lo hay, el cruce
entre ambos. Tono directo, sin saludos ni despedidas. Devuelve solo el texto.

Titulares:
{lines}
"""
    try:
        return (_generate(model, prompt, as_json=False) or "").strip()
    except _DailyQuotaExceeded:
        return ""


def build_digest(items, model, detalle="detallado", intereses="", output_language="español (castellano)"):
    print(f"   · Agrupando {len(items)} noticias por hecho…")
    try:
        groups = cluster(items, model)
    except _DailyQuotaExceeded:
        print("   [!] Cuota agotada al empezar; hoy no se genera briefing nuevo.")
        return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "count": 0, "daily_brief": "", "top": [], "stories": []}
    print(f"   · {len(groups)} hechos únicos. Resumiendo y puntuando en español ({detalle})…")
    stories = summarize_groups(groups, items, model, detalle=detalle,
                               intereses=intereses, output_language=output_language)
    print(f"   · {len(stories)} tras filtrar ruido. Escribiendo el resumen del día…")
    brief = daily_brief(stories, model, intereses=intereses, output_language=output_language)
    top = [s["id"] for s in stories[:5]]
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "count": len(stories),
        "daily_brief": brief,
        "top": top,
        "stories": stories,
    }
