"""
El Niño / La Niña news ingestion from Google News RSS.

Free, no auth, covers Peruvian outlets (El Comercio, La República, La
Industria, RPP, Infobae, Andina, etc.) plus international wires. Returns the
most recent items mentioning the El Niño / La Niña phenomenon in Peru.

NGO meeting 2026-05-05 asked for an in-dashboard alert card showing source +
date + relevant fragment so the field team can see the official narrative
without leaving the tool.
"""
from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import quote_plus

import requests

from ._cache import ttl_cache

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
DEFAULT_QUERY = '("fenómeno del niño" OR "fenómeno el niño" OR "fenómeno de la niña" OR ENFEN) Perú'
DEFAULT_HL = "es-419"
DEFAULT_GL = "PE"
DEFAULT_CEID = "PE:es-419"

# RSS namespace used by Google News
ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    published: dt.datetime
    url: str
    snippet: str

    def published_es(self) -> str:
        """Spanish-readable date (e.g. '5 may 2026')."""
        meses = ["ene", "feb", "mar", "abr", "may", "jun",
                 "jul", "ago", "sep", "oct", "nov", "dic"]
        return f"{self.published.day} {meses[self.published.month - 1]} {self.published.year}"

    def age_days(self, now: dt.datetime | None = None) -> int:
        ref = now or dt.datetime.now(self.published.tzinfo)
        return (ref - self.published).days


# Google News RSS — refresh every 30 min, fine for a "news ticker" use case.
@ttl_cache(30 * 60)
def fetch_enso_news(
    query: str = DEFAULT_QUERY,
    max_items: int = 5,
    max_age_days: int = 60,
    timeout: int = 15,
) -> list[NewsItem]:
    """Fetch recent Peruvian news on El Niño / La Niña / ENFEN.

    Filters out items older than `max_age_days`. Returns at most `max_items`,
    newest first. Returns an empty list on network failure (caller should
    surface a "no hay noticias" placeholder rather than crash the dashboard).
    """
    params = {
        "q": query,
        "hl": DEFAULT_HL,
        "gl": DEFAULT_GL,
        "ceid": DEFAULT_CEID,
    }
    try:
        r = requests.get(GOOGLE_NEWS_RSS, params=params, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (CropGuard/1.0)"})
        r.raise_for_status()
    except requests.RequestException:
        return []

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    items: list[NewsItem] = []
    for raw in channel.findall("item"):
        item = _parse_item(raw)
        if item is None:
            continue
        if item.published < cutoff:
            continue
        items.append(item)

    items.sort(key=lambda it: it.published, reverse=True)
    return items[:max_items]


def _parse_item(node: ET.Element) -> NewsItem | None:
    title_raw = (node.findtext("title") or "").strip()
    link = (node.findtext("link") or "").strip()
    pub_date_raw = (node.findtext("pubDate") or "").strip()
    source_node = node.find("source")
    source = (source_node.text or "").strip() if source_node is not None else ""
    description = (node.findtext("description") or "").strip()

    if not title_raw or not link or not pub_date_raw:
        return None

    try:
        published = _parse_pub_date(pub_date_raw)
    except ValueError:
        return None

    # Google News titles end with " - Source" — strip it for cleanliness
    title = re.sub(r"\s+-\s+[^-]+$", "", title_raw) if " - " in title_raw else title_raw
    if not source and " - " in title_raw:
        source = title_raw.rsplit(" - ", 1)[-1].strip()

    snippet = _strip_html(description)
    return NewsItem(
        title=title,
        source=source or "Google News",
        published=published,
        url=link,
        snippet=snippet,
    )


def _parse_pub_date(value: str) -> dt.datetime:
    """RSS pubDate is RFC-822 (e.g. 'Mon, 05 May 2026 10:00:00 GMT')."""
    from email.utils import parsedate_to_datetime
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html_text: str) -> str:
    import html as _html
    text = _TAG_RE.sub(" ", html_text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > 280:
        text = text[:277].rstrip() + "…"
    return text
