"""
fetch.py — Recogida de contenido de todas las fuentes.

- Para YouTube: convierte el @handle en el feed RSS del canal.
- Para blogs/newsletters: usa el feed indicado o intenta descubrirlo.
- Devuelve una lista de "items" nuevos (de las últimas N horas),
  ya sin duplicados exactos (misma URL/ID).
"""

from __future__ import annotations
import re
import time
import datetime as dt
from dataclasses import dataclass, field

import requests
import feedparser
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"}
TIMEOUT = 20


@dataclass
class Item:
    source_name: str
    source_type: str          # youtube | blog | newsletter
    topic_hint: str           # ia | geo
    title: str
    url: str
    published: dt.datetime
    snippet: str = ""         # resumen/transcripción recortada (contexto para la IA)
    lang: str = ""

    def key(self) -> str:
        """Identificador para detectar duplicados exactos."""
        return self.url.split("?")[0].rstrip("/").lower()


# ----------------------------------------------------------------------
#  YouTube: @handle -> channel_id -> feed RSS
# ----------------------------------------------------------------------
def resolve_youtube_feed(handle: str, cache: dict) -> str | None:
    """Convierte un @handle de YouTube en su feed RSS. Cachea el resultado."""
    handle = handle.strip()
    if handle in cache:
        return cache[handle]
    try:
        url = f"https://www.youtube.com/{handle}"
        html = requests.get(url, headers=UA, timeout=TIMEOUT).text
        m = re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html) or \
            re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html)
        if not m:
            m = re.search(r'channel_id=(UC[0-9A-Za-z_-]{22})', html)
        if not m:
            print(f"   [!] No pude resolver el canal de YouTube {handle}")
            return None
        feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
        cache[handle] = feed
        return feed
    except Exception as e:
        print(f"   [!] Error resolviendo {handle}: {e}")
        return None


def fetch_youtube_transcript(video_id: str) -> str:
    """Intenta sacar la transcripción (es o en). Es opcional: si falla, no pasa nada."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        # Compatible con varias versiones de la librería
        try:
            data = YouTubeTranscriptApi().fetch(video_id, languages=["es", "en"])
            text = " ".join(seg.text for seg in data)
        except Exception:
            chunks = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "en"])
            text = " ".join(c["text"] for c in chunks)
        return text[:4000]  # recortamos para no gastar tokens de más
    except Exception:
        return ""


# ----------------------------------------------------------------------
#  Blogs / newsletters: descubrir RSS si no se ha indicado
# ----------------------------------------------------------------------
def discover_feed(url: str, cache: dict) -> str | None:
    if url in cache:
        return cache[url]
    try:
        html = requests.get(url, headers=UA, timeout=TIMEOUT).text
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("link", attrs={"type": re.compile(r"application/(rss|atom)\+xml")})
        if link and link.get("href"):
            feed = requests.compat.urljoin(url, link["href"])
            cache[url] = feed
            return feed
    except Exception as e:
        print(f"   [!] No pude descubrir RSS en {url}: {e}")
    # último intento: patrones habituales
    for suffix in ("/feed", "/rss", "/feed/", "/index.xml"):
        guess = url.rstrip("/") + suffix
        try:
            parsed = feedparser.parse(guess)
            if parsed.entries:
                cache[url] = guess
                return guess
        except Exception:
            pass
    return None


# ----------------------------------------------------------------------
#  Parseo de fechas
# ----------------------------------------------------------------------
def _entry_datetime(entry) -> dt.datetime:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _clean(text: str, limit: int = 600) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)[:limit]


# ----------------------------------------------------------------------
#  Recogida principal
# ----------------------------------------------------------------------
def collect(sources: list[dict], settings: dict, state: dict) -> list[Item]:
    lookback = dt.timedelta(hours=settings.get("lookback_hours", 28))
    cutoff = dt.datetime.now(dt.timezone.utc) - lookback
    seen = set(state.get("seen", []))
    yt_cache = state.setdefault("youtube_feeds", {})
    feed_cache = state.setdefault("discovered_feeds", {})

    items: list[Item] = []

    for src in sources:
        name = src["name"]
        stype = src["type"]
        topic = src.get("topic", "ia")
        lang = src.get("lang", "")

        # 1) Determinar el feed RSS
        if stype == "youtube":
            feed_url = resolve_youtube_feed(src["handle"], yt_cache)
        else:
            feed_url = src.get("feed") or discover_feed(src["url"], feed_cache)

        if not feed_url:
            continue

        # 2) Leer el feed
        try:
            parsed = feedparser.parse(feed_url, request_headers=UA)
        except Exception as e:
            print(f"   [!] Error leyendo {name}: {e}")
            continue

        new_count = 0
        for entry in parsed.entries[:30]:
            link = entry.get("link", "")
            if not link:
                continue
            published = _entry_datetime(entry)
            if published < cutoff:
                continue

            item = Item(
                source_name=name, source_type=stype, topic_hint=topic,
                title=entry.get("title", "(sin título)").strip(),
                url=link, published=published, lang=lang,
                snippet=_clean(entry.get("summary", "") or entry.get("description", "")),
            )
            if item.key() in seen:
                continue
            seen.add(item.key())

            # 3) YouTube: añadir transcripción como contexto extra
            if stype == "youtube":
                vid = entry.get("yt_videoid") or (link.split("v=")[-1].split("&")[0] if "v=" in link else "")
                if vid:
                    tr = fetch_youtube_transcript(vid)
                    if tr:
                        item.snippet = (item.snippet + " " + tr).strip()[:4000]

            items.append(item)
            new_count += 1

        if new_count:
            print(f"   + {name}: {new_count} nuevos")
        time.sleep(0.2)  # cortesía con los servidores

    # Guardamos lo visto (limitado para que el archivo no crezca infinito)
    state["seen"] = list(seen)[-8000:]

    # Ordenamos por fecha (lo más nuevo primero) y limitamos volumen
    items.sort(key=lambda i: i.published, reverse=True)
    return items[: settings.get("max_items_per_run", 200)]
