"""
fetch.py — Recogida de contenido de todas las fuentes.

Endurecido contra cuelgues:
- Cada descarga de RSS y de artículo tiene LÍMITE DE ESPERA.
- TOPE DE TIEMPO global: pasado X, deja de recoger y sigue con lo que haya.
- Imprime el progreso al instante (fuente por fuente).
- YouTube: título, descripción y miniatura. Blogs: cuerpo real del artículo.
- Memoria de vistos con fecha + informe de salud por fuente.
"""

from __future__ import annotations
import re
import time
import socket
import datetime as dt
from dataclasses import dataclass

import requests
import feedparser
from bs4 import BeautifulSoup
import trafilatura

socket.setdefaulttimeout(20)  # red de seguridad para cualquier conexión perdida
UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"}
FEED_TIMEOUT = 15
ARTICLE_TIMEOUT = 10


@dataclass
class Item:
    source_name: str
    source_type: str
    topic_hint: str
    title: str
    url: str
    published: dt.datetime
    snippet: str = ""
    body: str = ""
    image: str = ""
    lang: str = ""

    def key(self) -> str:
        return self.url.split("?")[0].rstrip("/").lower()


def fetch_feed(url):
    """Descarga un feed con límite de espera y lo parsea (evita cuelgues de feedparser)."""
    try:
        r = requests.get(url, headers=UA, timeout=FEED_TIMEOUT)
        return feedparser.parse(r.content)
    except Exception:
        return None


def resolve_youtube_feed(handle, cache):
    handle = handle.strip()
    if handle in cache:
        return cache[handle]
    try:
        html = requests.get(f"https://www.youtube.com/{handle}", headers=UA, timeout=FEED_TIMEOUT).text
        m = (re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
             or re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html)
             or re.search(r'channel_id=(UC[0-9A-Za-z_-]{22})', html))
        if not m:
            return None
        feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
        cache[handle] = feed
        return feed
    except Exception:
        return None


def discover_feed(url, cache):
    if url in cache:
        return cache[url]
    try:
        html = requests.get(url, headers=UA, timeout=FEED_TIMEOUT).text
        soup = BeautifulSoup(html, "html.parser")
        link = soup.find("link", attrs={"type": re.compile(r"application/(rss|atom)\+xml")})
        if link and link.get("href"):
            feed = requests.compat.urljoin(url, link["href"])
            cache[url] = feed
            return feed
    except Exception:
        pass
    for suffix in ("/feed", "/rss", "/feed/", "/index.xml"):
        guess = url.rstrip("/") + suffix
        parsed = fetch_feed(guess)
        if parsed and parsed.entries:
            cache[url] = guess
            return guess
    return None


def fetch_article(url):
    try:
        html = requests.get(url, headers=UA, timeout=ARTICLE_TIMEOUT).text
    except Exception:
        return "", ""
    try:
        body = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    except Exception:
        body = ""
    image = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        og = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
        if og and og.get("content"):
            image = requests.compat.urljoin(url, og["content"])
    except Exception:
        pass
    return body.strip()[:5000], image


def _entry_datetime(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return dt.datetime(*t[:6], tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _clean(text, limit):
    if not text:
        return ""
    if "<" not in text:                 # texto plano: evita el warning de BeautifulSoup
        return text[:limit]
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)[:limit]


def _entry_image(entry):
    for key in ("media_thumbnail", "media_content"):
        val = entry.get(key)
        if val and isinstance(val, list) and val[0].get("url"):
            return val[0]["url"]
    for enc in entry.get("links", []):
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]
    return ""


def _parse_iso(s):
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def collect(sources, settings, state):
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = now.isoformat()
    lookback = dt.timedelta(hours=settings.get("lookback_hours", 28))
    cutoff = now - lookback
    fetch_bodies = settings.get("fetch_article_bodies", True)
    max_bodies = settings.get("max_bodies_per_source", 8)
    max_per_source = settings.get("max_items_per_source", 8)
    retention = dt.timedelta(days=settings.get("seen_retention_days", 60))
    budget = settings.get("collect_budget_minutes", 18) * 60
    start = time.monotonic()

    raw = state.get("seen", {})
    seen = {k: now_iso for k in raw} if isinstance(raw, list) else dict(raw)

    yt_cache = state.setdefault("youtube_feeds", {})
    feed_cache = state.setdefault("discovered_feeds", {})
    health = state.setdefault("source_health", {})

    items, report = [], []
    total = len(sources)

    for i, src in enumerate(sources, 1):
        name, stype = src["name"], src["type"]
        topic, lang = src.get("topic", "ia"), src.get("lang", "")
        status, note, new_count, thin = "ok", "", 0, 0

        if time.monotonic() - start > budget:
            print(f"   [i] Tope de tiempo alcanzado; sigo con lo recogido ({len(items)} noticias).", flush=True)
            report.append({"name": name, "type": stype, "topic": topic, "status": "no_revisada",
                           "new": 0, "note": "no dio tiempo en esta ejecución",
                           "last_success": health.get(name, {}).get("last_success", ""),
                           "last_error": health.get(name, {}).get("last_error", "")})
            continue

        print(f"   [{i}/{total}] {name}…", flush=True)

        if stype == "youtube":
            feed_url = resolve_youtube_feed(src["handle"], yt_cache)
        else:
            feed_url = src.get("feed") or discover_feed(src["url"], feed_cache)

        if not feed_url:
            status = "sin_feed"
        else:
            parsed = fetch_feed(feed_url)
            if parsed is None:
                status = "error"
                note = "no respondió a tiempo"
            else:
                bodies = 0
                for entry in parsed.entries[:30]:
                    link = entry.get("link", "")
                    if not link:
                        continue
                    published = _entry_datetime(entry)
                    if published < cutoff:
                        continue
                    k = link.split("?")[0].rstrip("/").lower()
                    if k in seen:
                        continue
                    if new_count >= max_per_source:
                        break  # tope por fuente: no acaparar el briefing
                    seen[k] = now_iso

                    rss_text = _clean(entry.get("summary", "") or entry.get("description", ""), 5000)
                    item = Item(source_name=name, source_type=stype, topic_hint=topic,
                                title=entry.get("title", "(sin título)").strip(),
                                url=link, published=published, lang=lang,
                                image=_entry_image(entry))
                    if stype == "youtube":
                        item.body = rss_text
                        item.snippet = rss_text[:220]
                    else:
                        body, image = ("", "")
                        over = time.monotonic() - start > budget
                        if fetch_bodies and not over and bodies < max_bodies:
                            body, image = fetch_article(link)
                            bodies += 1
                        item.body = body if len(body) > 200 else rss_text
                        item.snippet = (rss_text or body)[:220]
                        if image and not item.image:
                            item.image = image
                        if len(item.body) < 300:
                            thin += 1
                    items.append(item)
                    new_count += 1

        if status == "ok":
            status = "ok" if new_count > 0 else "sin_novedades"
            if new_count > 0:
                health.setdefault(name, {})["last_success"] = now_iso
            if thin and thin == new_count and new_count > 0:
                note = "titulares cortos (¿de pago?)"
        if status in ("error", "sin_feed"):
            health.setdefault(name, {})["last_error"] = now_iso
        h = health.setdefault(name, {})
        h["last_status"], h["last_check"] = status, now_iso

        report.append({"name": name, "type": stype, "topic": topic, "status": status,
                       "new": new_count, "note": note,
                       "last_success": h.get("last_success", ""), "last_error": h.get("last_error", "")})
        if new_count:
            print(f"        + {new_count} nuevas", flush=True)
        time.sleep(0.1)

    keep_after = now - retention
    seen = {k: v for k, v in seen.items() if (_parse_iso(v) or now) >= keep_after}
    state["seen"] = seen

    items.sort(key=lambda i: i.published, reverse=True)
    print(f"   · Recogida terminada en {int(time.monotonic()-start)}s.", flush=True)
    return items[: settings.get("max_items_per_run", 200)], report
