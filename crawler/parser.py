"""HTML metadata extraction: title, description, Open Graph, body text, headings, links."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# Tags whose text content is noise, not page body.
NOISE_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "form", "nav", "footer", "aside"]


@dataclass
class PageMetadata:
    url: str = ""
    domain: str = ""
    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    canonical_url: str = ""
    language: str = ""
    author: str = ""
    published_date: str = ""
    open_graph: dict = field(default_factory=dict)
    twitter_card: dict = field(default_factory=dict)
    json_ld_types: list[str] = field(default_factory=list)
    headings: dict = field(default_factory=dict)  # {"h1": [...], "h2": [...], "h3": [...]}
    body_text: str = ""
    word_count: int = 0
    link_count: int = 0
    image_count: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "domain": self.domain,
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "canonical_url": self.canonical_url,
            "language": self.language,
            "author": self.author,
            "published_date": self.published_date,
            "open_graph": self.open_graph,
            "twitter_card": self.twitter_card,
            "json_ld_types": self.json_ld_types,
            "headings": self.headings,
            "word_count": self.word_count,
            "link_count": self.link_count,
            "image_count": self.image_count,
            "body_text_preview": self.body_text[:500],
        }


def _meta_content(soup: BeautifulSoup, **attrs) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


def _collect_prefixed_meta(soup: BeautifulSoup, attr: str, prefix: str) -> dict:
    collected = {}
    for tag in soup.find_all("meta"):
        key = tag.get(attr, "")
        if key.startswith(prefix) and tag.get("content"):
            collected[key[len(prefix):]] = tag["content"].strip()
    return collected


def _extract_json_ld_types(soup: BeautifulSoup) -> list[str]:
    types: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                node_type = item.get("@type")
                if isinstance(node_type, str):
                    types.append(node_type)
                elif isinstance(node_type, list):
                    types.extend(t for t in node_type if isinstance(t, str))
                for nested in item.get("@graph", []) if isinstance(item.get("@graph"), list) else []:
                    if isinstance(nested, dict) and isinstance(nested.get("@type"), str):
                        types.append(nested["@type"])
    return list(dict.fromkeys(types))


def _extract_body_text(soup: BeautifulSoup) -> str:
    body = BeautifulSoup(str(soup), "lxml")  # work on a copy so callers keep the full tree
    for tag in body.find_all(NOISE_TAGS):
        tag.decompose()
    main = body.find("main") or body.find("article") or body.body or body
    text = main.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_metadata(html: str, url: str = "") -> PageMetadata:
    """Parse raw HTML into structured page metadata."""
    soup = BeautifulSoup(html, "lxml")
    meta = PageMetadata(url=url, domain=urlparse(url).netloc.replace("www.", "") if url else "")

    if soup.title and soup.title.string:
        meta.title = soup.title.string.strip()

    meta.open_graph = _collect_prefixed_meta(soup, "property", "og:")
    meta.twitter_card = _collect_prefixed_meta(soup, "name", "twitter:")

    meta.description = (
        _meta_content(soup, name="description")
        or meta.open_graph.get("description", "")
        or meta.twitter_card.get("description", "")
    )
    if not meta.title:
        meta.title = meta.open_graph.get("title", "") or meta.twitter_card.get("title", "")

    raw_keywords = _meta_content(soup, name="keywords")
    meta.keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]

    canonical = soup.find("link", rel="canonical")
    meta.canonical_url = canonical.get("href", "").strip() if canonical else ""

    html_tag = soup.find("html")
    meta.language = html_tag.get("lang", "").strip() if html_tag else ""

    meta.author = _meta_content(soup, name="author") or _meta_content(soup, property="article:author")
    meta.published_date = (
        _meta_content(soup, property="article:published_time")
        or _meta_content(soup, name="date")
        or _meta_content(soup, name="pubdate")
    )

    meta.json_ld_types = _extract_json_ld_types(soup)

    meta.headings = {
        level: [h.get_text(strip=True) for h in soup.find_all(level) if h.get_text(strip=True)][:10]
        for level in ("h1", "h2", "h3")
    }

    meta.body_text = _extract_body_text(soup)
    meta.word_count = len(meta.body_text.split())
    meta.link_count = len(soup.find_all("a", href=True))
    meta.image_count = len(soup.find_all("img"))

    return meta
