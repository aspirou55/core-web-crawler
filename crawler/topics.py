"""Topic extraction: rank unigrams/bigrams/trigrams by zone-weighted frequency.

Text from high-signal zones (title, meta description, keywords, headings)
counts more than body text. Longer phrases get a length bonus so that
"machine learning" beats "machine" and "learning" separately, and phrases
subsumed by a higher-ranked longer phrase are dropped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from crawler.parser import PageMetadata

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been
    before being below between both but by can cannot could did do does doing down
    during each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just me more most my myself no nor
    not now of off on once only or other our ours ourselves out over own same she
    should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves
    also get got like may might must one two new use using via says said say
    inc com www http https amp nbsp""".split()
)

# Zone weights: where a term appears matters more than raw frequency.
ZONE_WEIGHTS = {
    "title": 5.0,
    "keywords": 5.0,
    "description": 3.0,
    "headings": 2.5,
    "og": 3.0,
    "body": 1.0,
}

TOKEN_RE = re.compile(r"[a-z][a-z0-9'\-]+")


@dataclass
class Topic:
    phrase: str
    score: float

    def to_dict(self) -> dict:
        return {"topic": self.phrase, "score": round(self.score, 2)}


def _tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def _ngrams(tokens: list[str], n: int) -> list[str]:
    grams = []
    for i in range(len(tokens) - n + 1):
        window = tokens[i : i + n]
        # Interior stopwords are fine ("state of the art"); edges must be content words.
        if window[0] in STOPWORDS or window[-1] in STOPWORDS:
            continue
        if any(len(w) < 3 and not w.isdigit() for w in (window[0], window[-1])):
            continue
        grams.append(" ".join(window))
    return grams


def _score_zone(text: str, weight: float, counter: Counter) -> None:
    tokens = _tokenize(text)
    for token in tokens:
        if token not in STOPWORDS and len(token) >= 3:
            counter[token] += weight
    for n, bonus in ((2, 2.2), (3, 3.0)):
        for gram in _ngrams(tokens, n):
            counter[gram] += weight * bonus


def extract_topics(meta: PageMetadata, max_topics: int = 10, body_char_limit: int = 30000) -> list[Topic]:
    """Return the top-ranked topics for a parsed page."""
    counter: Counter = Counter()

    _score_zone(meta.title, ZONE_WEIGHTS["title"], counter)
    _score_zone(meta.description, ZONE_WEIGHTS["description"], counter)
    _score_zone(" ".join(meta.keywords), ZONE_WEIGHTS["keywords"], counter)
    _score_zone(
        " ".join(h for level in meta.headings.values() for h in level),
        ZONE_WEIGHTS["headings"],
        counter,
    )
    og_text = " ".join(
        meta.open_graph.get(k, "") for k in ("title", "description", "site_name")
    )
    _score_zone(og_text, ZONE_WEIGHTS["og"], counter)
    _score_zone(meta.body_text[:body_char_limit], ZONE_WEIGHTS["body"], counter)

    if not counter:
        return []

    ranked = counter.most_common(max_topics * 6)

    # Drop phrases fully contained in a higher-scoring longer phrase, and
    # longer phrases that merely repeat an already-kept shorter one.
    topics: list[Topic] = []
    for phrase, score in ranked:
        contained = any(
            (f" {phrase} " in f" {kept.phrase} ") or (f" {kept.phrase} " in f" {phrase} ")
            for kept in topics
        )
        if contained:
            continue
        topics.append(Topic(phrase=phrase, score=score))
        if len(topics) >= max_topics:
            break

    return topics
