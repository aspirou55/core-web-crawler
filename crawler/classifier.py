"""Page-type classification from structured signals.

Combines evidence in priority order:
1. JSON-LD @type (site says exactly what the page is)
2. Open Graph og:type
3. URL path patterns
4. Content/DOM heuristics (word count, price mentions, headings)

Each signal contributes a weighted vote; the result includes the winning
label, a confidence score, and the signals that fired (for explainability).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from crawler.parser import PageMetadata

PAGE_TYPES = [
    "product",
    "article",
    "blog_post",
    "news",
    "video",
    "recipe",
    "forum_discussion",
    "documentation",
    "homepage",
    "category_listing",
    "bot_challenge",
    "other",
]

# JSON-LD @type -> (page_type, weight). Schema.org types are the strongest signal.
JSON_LD_MAP = {
    "product": ("product", 5.0),
    "offer": ("product", 3.0),
    "aggregateoffer": ("product", 3.0),
    "newsarticle": ("news", 5.0),
    "reportagenewsarticle": ("news", 5.0),
    "article": ("article", 4.0),
    "blogposting": ("blog_post", 5.0),
    "videoobject": ("video", 4.0),
    "recipe": ("recipe", 5.0),
    "qapage": ("forum_discussion", 4.0),
    "discussionforumposting": ("forum_discussion", 5.0),
    "faqpage": ("documentation", 3.0),
    "techarticle": ("documentation", 4.0),
    "collectionpage": ("category_listing", 3.0),
    "itemlist": ("category_listing", 2.5),
    "website": ("homepage", 1.0),
}

OG_TYPE_MAP = {
    "product": ("product", 4.0),
    "og:product": ("product", 4.0),
    "article": ("article", 3.0),
    "blog": ("blog_post", 3.0),
    "video": ("video", 3.0),
    "video.other": ("video", 3.0),
    "website": ("homepage", 0.5),
}

# URL path regex -> (page_type, weight)
URL_PATTERNS = [
    (r"/dp/|/gp/product/|/product[s]?/|/item/|/p/\d", "product", 3.0),
    (r"/blog[s]?/|/post[s]?/", "blog_post", 2.5),
    (r"/news/|/\d{4}/\d{2}/\d{2}/|/\d{4}/\d{2}/[a-z]", "news", 2.5),
    (r"/article[s]?/|/story/", "article", 2.0),
    (r"/watch|/video[s]?/", "video", 2.5),
    (r"/recipe[s]?/", "recipe", 3.0),
    (r"/docs?/|/documentation/|/manual/|/api/|/reference/", "documentation", 2.5),
    (r"/forum[s]?/|/thread[s]?/|/questions?/|/t/\d", "forum_discussion", 2.5),
    (r"/category/|/categories/|/c/|/shop/|/collections?/", "category_listing", 2.0),
]

NEWS_DOMAINS = re.compile(
    r"(cnn|bbc|nytimes|reuters|apnews|theguardian|washingtonpost|bloomberg|cnbc|foxnews|nbcnews|abcnews|npr)\."
)
PRICE_PATTERN = re.compile(r"[$€£]\s?\d[\d,]*(\.\d{2})?")
CART_PATTERN = re.compile(r"add to (cart|bag|basket)|buy now|in stock|free shipping", re.IGNORECASE)

# Anti-bot walls: sites serve these instead of real content (often with a
# deceptive 200 status). Titles seen in the wild: Reddit "Please wait for
# verification", Cloudflare "Just a moment...", Amazon "Robot Check".
CHALLENGE_TITLE = re.compile(
    r"please wait|verification|verify (you|your)|just a moment|attention required"
    r"|robot check|are you a (human|robot)|access denied|captcha|security check"
    r"|unusual traffic|pardon our interruption",
    re.IGNORECASE,
)
CHALLENGE_BODY = re.compile(
    r"verify (that )?you are (a )?(human|not a robot)|enable javascript and cookies"
    r"|complete the (security check|action below)|unusual traffic from your"
    r"|click the button below to continue|checking your browser",
    re.IGNORECASE,
)


@dataclass
class Classification:
    page_type: str
    confidence: float  # 0..1
    scores: dict = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_type": self.page_type,
            "confidence": round(self.confidence, 3),
            "scores": {k: round(v, 2) for k, v in sorted(self.scores.items(), key=lambda x: -x[1])},
            "signals": self.signals,
        }


def classify(meta: PageMetadata) -> Classification:
    """Classify a parsed page into one of PAGE_TYPES with an evidence trail."""
    scores: dict[str, float] = {}
    signals: list[str] = []

    def vote(page_type: str, weight: float, reason: str) -> None:
        scores[page_type] = scores.get(page_type, 0.0) + weight
        signals.append(f"{reason} -> {page_type} (+{weight})")

    # 0. Anti-bot challenge detection. A challenge page = telltale wording AND
    # suspicious emptiness (the real content was withheld). The word-count
    # gate stops a long article ABOUT captchas from being flagged.
    if CHALLENGE_TITLE.search(meta.title) and meta.word_count < 150:
        vote("bot_challenge", 4.0, f"challenge-pattern title {meta.title!r}")
        if meta.word_count < 30:
            vote("bot_challenge", 2.0, f"near-empty body ({meta.word_count} words)")
    if CHALLENGE_BODY.search(meta.body_text[:3000]) and meta.word_count < 150:
        vote("bot_challenge", 4.0, "challenge-pattern body text")

    # 1. JSON-LD structured data
    for ld_type in meta.json_ld_types:
        mapped = JSON_LD_MAP.get(ld_type.lower())
        if mapped:
            vote(mapped[0], mapped[1], f"json-ld @type={ld_type}")

    # 2. Open Graph type
    og_type = meta.open_graph.get("type", "").lower()
    if og_type:
        mapped = OG_TYPE_MAP.get(og_type)
        if mapped:
            vote(mapped[0], mapped[1], f"og:type={og_type}")

    # 3. URL patterns
    url = (meta.canonical_url or meta.url).lower()
    path = re.sub(r"^https?://[^/]+", "", url)
    for pattern, page_type, weight in URL_PATTERNS:
        if re.search(pattern, path):
            vote(page_type, weight, f"url matches {pattern!r}")
            break
    if url and path in ("", "/"):
        vote("homepage", 3.0, "url is site root")

    # 4. Domain and content heuristics
    if NEWS_DOMAINS.search(meta.domain):
        vote("news", 2.0, f"news domain {meta.domain}")

    sample = meta.body_text[:20000]
    price_hits = len(PRICE_PATTERN.findall(sample))
    if price_hits >= 3 and CART_PATTERN.search(sample):
        vote("product", 2.0, f"{price_hits} price mentions + cart language")
    elif price_hits >= 10:
        vote("category_listing", 1.5, f"{price_hits} price mentions (listing-like)")

    if meta.published_date:
        vote("article", 1.0, "has article:published_time/date meta")
    if meta.author:
        vote("article", 0.5, "has author meta")

    if meta.word_count > 600 and not scores.get("product"):
        vote("article", 1.0, f"long-form body ({meta.word_count} words)")
    if meta.word_count < 150 and meta.link_count > 80:
        vote("category_listing", 1.5, "link-dense, low text (nav/listing page)")

    if not scores:
        return Classification(page_type="other", confidence=0.0, scores={}, signals=["no signals fired"])

    total = sum(scores.values())
    winner = max(scores, key=scores.get)
    confidence = min(scores[winner] / max(total, 1e-9), 1.0)
    # Boost confidence when the winner clears an absolute evidence bar.
    if scores[winner] >= 5.0:
        confidence = min(confidence + 0.2, 1.0)

    return Classification(page_type=winner, confidence=confidence, scores=scores, signals=signals)
