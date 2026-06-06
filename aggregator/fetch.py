"""
fetch.py — Recogida de contenido de todas las fuentes.

- YouTube: del feed saca título, DESCRIPCIÓN del vídeo y MINIATURA.
- Blogs/newsletters: del RSS saca el enlace y baja el ARTÍCULO real (cuerpo + imagen).
- Memoria de "vistos" con fecha (se purga lo viejo automáticamente).
- Genera un informe de SALUD por fuente (ok / sin novedades / sin feed / error).
"""

from __future__ import annotations
import re
import time
import datetime as dt
from dataclasses import dataclass

import requests
import feedparser
from bs4 import BeautifulSoup
import trafilatura

UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"}
TIMEOUT = 15


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


def resolve_youtube_feed(handle, cache):
    handle = handle.strip()
    if handle in cache:
        return cache[handle]
    try:
        html = requests.get(f"https://www.youtube.com/{handle}", headers=UA, timeout=TIMEOUT).text
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
        html = requests.get(url, headers=UA, timeout=TIMEOUT).text
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
        try:
            if feedparser.parse(guess).entries:
                cache[url] = guess
                return guess
        except Exception:
            pass
    return None


def fetch_article(url):
    try:
        html = requests.get(url, headers=UA, timeout=TIMEOUT).text
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
    retention = dt.timedelta(days=settings.get("seen_retention_days", 60))

    # --- memoria de vistos con fecha (compatible con el formato antiguo de lista) ---
    raw = state.get("seen", {})
    if isinstance(raw, list):
        seen = {k: now_iso for k in raw}
    else:
        seen = dict(raw)

    yt_cache = state.setdefault("youtube_feeds", {})
    feed_cache = state.setdefault("discovered_feeds", {})
    health = state.setdefault("source_health", {})

    items, report = [], []

    for src in sources:
        name, stype = src["name"], src["type"]
        topic, lang = src.get("topic", "ia"), src.get("lang", "")
        status, note, new_count, thin = "ok", "", 0, 0

        if stype == "youtube":
            feed_url = resolve_youtube_feed(src["handle"], yt_cache)
        else:
            feed_url = src.get("feed") or discover_feed(src["url"], feed_cache)

        if not feed_url:
            status = "sin_feed"
        else:
            try:
                parsed = feedparser.parse(feed_url, request_headers=UA)
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
                        if fetch_bodies:
                            body, image = fetch_article(link)
                        item.body = body if len(body) > 200 else rss_text
                        item.snippet = (rss_text or body)[:220]
                        if image and not item.image:
                            item.image = image
                        if len(item.body) < 300:
                            thin += 1
                    items.append(item)
                    new_count += 1
            except Exception as e:
                status = "error"
                note = str(e)[:120]

        # --- estado y salud histórica de la fuente ---
        if status == "ok":
            status = "ok" if new_count > 0 else "sin_novedades"
            if new_count > 0:
                health.setdefault(name, {})["last_success"] = now_iso
            if thin and thin == new_count and new_count > 0:
                note = "titulares cortos (¿de pago?)"
        if status in ("error", "sin_feed"):
            health.setdefault(name, {})["last_error"] = now_iso
        h = health.setdefault(name, {})
        h["last_status"] = status
        h["last_check"] = now_iso

        report.append({
            "name": name, "type": stype, "topic": topic, "status": status,
            "new": new_count, "note": note,
            "last_success": h.get("last_success", ""), "last_error": h.get("last_error", ""),
        })
        if new_count:
            print(f"   + {name}: {new_count} nuevos")
        time.sleep(0.15)

    # purga de vistos antiguos
    keep_after = now - retention
    seen = {k: v for k, v in seen.items() if (_parse_iso(v) or now) >= keep_after}
    state["seen"] = seen

    items.sort(key=lambda i: i.published, reverse=True)
    return items[: settings.get("max_items_per_run", 200)], report
