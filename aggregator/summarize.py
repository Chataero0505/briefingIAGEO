"""
summarize.py — Capa de IA (Gemini, gratis).

Dos pasos:
  1) AGRUPAR: junta los items que hablan del MISMO hecho (aunque vengan
     de fuentes distintas). Así una noticia no se repite.
  2) RESUMIR: por cada grupo, escribe UN resumen en español con título,
     contexto, "por qué importa", importancia (1-5) y etiquetas.
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


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta la variable GEMINI_API_KEY (la clave de Gemini).")
        _client = genai.Client(api_key=api_key)
    return _client


def _generate(model: str, prompt: str, retries: int = 4) -> str:
    """Llama a Gemini pidiendo JSON, con reintentos si hay límite de ritmo (429)."""
    client = _get_client()
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                ),
            )
            return resp.text or ""
        except Exception as e:
            msg = str(e).lower()
            if ("429" in msg or "resource" in msg or "rate" in msg) and attempt < retries - 1:
                wait = 20 * (attempt + 1)
                print(f"   [i] Límite de ritmo, esperando {wait}s…")
                time.sleep(wait)
                continue
            print(f"   [!] Error de Gemini: {e}")
            return ""
    return ""


def _parse_json(text: str):
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
        # intento de rescate: buscar el primer corchete/llave
        for open_c, close_c in (("[", "]"), ("{", "}")):
            i, j = text.find(open_c), text.rfind(close_c)
            if i != -1 and j != -1:
                try:
                    return json.loads(text[i:j + 1])
                except Exception:
                    pass
    return None


# ----------------------------------------------------------------------
#  Paso 1: agrupar items del mismo hecho
# ----------------------------------------------------------------------
def cluster(items: list[Item], model: str) -> list[dict]:
    if not items:
        return []

    listing = []
    for idx, it in enumerate(items):
        listing.append(f'{idx}. [{it.topic_hint}] ({it.source_name}) {it.title} :: {it.snippet[:160]}')
    joined = "\n".join(listing)

    prompt = f"""Eres un editor de noticias. Abajo hay una lista numerada de noticias/vídeos
sobre Inteligencia Artificial y/o Geopolítica, de fuentes distintas y en varios idiomas.

Agrupa las que tratan EXACTAMENTE EL MISMO hecho o anuncio concreto (mismo evento,
mismo lanzamiento, misma noticia), aunque las cuenten medios diferentes. Sé CONSERVADOR:
si dudas, déjalas separadas. Cada noticia debe aparecer en un único grupo. Las que no
se parezcan a ninguna otra forman su propio grupo de un solo elemento.

Para cada grupo asigna un tema: "ia" si es sobre inteligencia artificial, "geo" si es
sobre geopolítica/relaciones internacionales/economía política. Si encaja en ambos,
elige el que predomine.

Devuelve SOLO un JSON con esta forma, sin texto extra:
[{{"indices": [0, 4], "topic": "ia"}}, {{"indices": [1], "topic": "geo"}}]

Lista:
{joined}
"""
    data = _parse_json(_generate(model, prompt))
    if not isinstance(data, list):
        # si la IA falla, cada item va por su cuenta
        return [{"indices": [i], "topic": it.topic_hint} for i, it in enumerate(items)]

    groups, used = [], set()
    for g in data:
        idxs = [i for i in g.get("indices", []) if isinstance(i, int) and 0 <= i < len(items) and i not in used]
        if not idxs:
            continue
        used.update(idxs)
        groups.append({"indices": idxs, "topic": g.get("topic", items[idxs[0]].topic_hint)})
    # cualquier item que la IA se haya dejado fuera, lo añadimos solo
    for i, it in enumerate(items):
        if i not in used:
            groups.append({"indices": [i], "topic": it.topic_hint})
    return groups


# ----------------------------------------------------------------------
#  Paso 2: resumir cada grupo en español (en lotes para gastar menos)
# ----------------------------------------------------------------------
def summarize_groups(groups: list[dict], items: list[Item], model: str, batch_size: int = 6) -> list[dict]:
    stories: list[dict] = []

    for start in range(0, len(groups), batch_size):
        batch = groups[start:start + batch_size]
        blocks = []
        for n, g in enumerate(batch):
            srcs = [items[i] for i in g["indices"]]
            txt = "\n".join(f"  - ({s.source_name}) {s.title}: {s.snippet[:300]}" for s in srcs)
            blocks.append(f"GRUPO {n} (tema={g['topic']}):\n{txt}")
        joined = "\n\n".join(blocks)

        prompt = f"""Eres un redactor de un boletín diario en ESPAÑOL (castellano de España).
Abajo hay varios GRUPOS de noticias. Cada grupo es UN solo hecho contado por una o más fuentes.

Para CADA grupo escribe, SIEMPRE en español aunque las fuentes estén en inglés u otro idioma:
- "titular": un titular claro y conciso en español.
- "resumen": 2-4 frases explicando qué ha pasado, sintetizando todas las fuentes del grupo
  sin repetir datos. Tono neutral e informativo.
- "por_que_importa": 1 frase sobre por qué es relevante.
- "importancia": número del 1 (menor) al 5 (gran impacto).
- "etiquetas": 2-4 etiquetas cortas en español.

Devuelve SOLO un JSON (lista), un objeto por grupo y EN EL MISMO ORDEN:
[{{"titular":"...","resumen":"...","por_que_importa":"...","importancia":3,"etiquetas":["..."]}}]

{joined}
"""
        data = _parse_json(_generate(model, prompt))
        if not isinstance(data, list) or len(data) != len(batch):
            data = [{} for _ in batch]  # degradado: usamos el título original

        for g, res in zip(batch, data):
            srcs = [items[i] for i in g["indices"]]
            first = srcs[0]
            published = max(s.published for s in srcs)
            sid = hashlib.md5(("|".join(sorted(s.key() for s in srcs))).encode()).hexdigest()[:10]
            stories.append({
                "id": sid,
                "topic": g["topic"] if g["topic"] in ("ia", "geo") else first.topic_hint,
                "title": res.get("titular") or first.title,
                "summary": res.get("resumen") or first.snippet[:300],
                "why": res.get("por_que_importa", ""),
                "importance": int(res.get("importancia", 2) or 2),
                "tags": res.get("etiquetas", [])[:4],
                "published": published.isoformat(),
                "sources": [
                    {"name": s.source_name, "url": s.url, "type": s.source_type}
                    for s in srcs
                ],
            })
        time.sleep(4)  # respeta el ritmo del nivel gratis

    stories.sort(key=lambda s: (s["importance"], s["published"]), reverse=True)
    return stories


def build_digest(items: list[Item], model: str) -> dict:
    print(f"   · Agrupando {len(items)} noticias por hecho…")
    groups = cluster(items, model)
    print(f"   · {len(groups)} hechos únicos tras agrupar. Resumiendo en español…")
    stories = summarize_groups(groups, items, model)
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "count": len(stories),
        "stories": stories,
    }
