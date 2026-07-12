"""End-to-end pipeline: fetch -> parse -> classify -> extract topics."""

from __future__ import annotations

from dataclasses import dataclass

from crawler.classifier import Classification, classify
from crawler.fetcher import FetchResult, fetch
from crawler.parser import PageMetadata, extract_metadata
from crawler.topics import Topic, extract_topics


@dataclass
class CrawlResult:
    url: str
    success: bool
    error: str | None
    fetch: FetchResult | None
    metadata: PageMetadata | None
    classification: Classification | None
    topics: list[Topic]

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "success": self.success,
            "error": self.error,
            # Fetch worked but the site served an anti-bot wall instead of
            # real content: metadata below describes the wall, not the page.
            "bot_challenged": bool(
                self.classification and self.classification.page_type == "bot_challenge"
            ),
            "fetch": {
                "final_url": self.fetch.final_url,
                "status_code": self.fetch.status_code,
                "content_type": self.fetch.content_type,
                "elapsed_seconds": self.fetch.elapsed_seconds,
                "truncated": self.fetch.truncated,
            }
            if self.fetch
            else None,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "classification": self.classification.to_dict() if self.classification else None,
            "topics": [t.to_dict() for t in self.topics],
        }


def crawl(url: str, max_topics: int = 10, timeout: float = 15.0) -> CrawlResult:
    """Crawl a single URL and return metadata, page classification, and topics."""
    fetch_result = fetch(url, timeout=timeout)

    if not fetch_result.ok:
        return CrawlResult(
            url=url,
            success=False,
            error=fetch_result.error or f"HTTP {fetch_result.status_code}",
            fetch=fetch_result,
            metadata=None,
            classification=None,
            topics=[],
        )

    metadata = extract_metadata(fetch_result.html, url=fetch_result.final_url or url)
    classification = classify(metadata)
    topics = extract_topics(metadata, max_topics=max_topics)

    return CrawlResult(
        url=url,
        success=True,
        error=None,
        fetch=fetch_result,
        metadata=metadata,
        classification=classification,
        topics=topics,
    )


def crawl_html(html: str, url: str = "", max_topics: int = 10) -> CrawlResult:
    """Run the parse/classify/topics stages on HTML you already have (offline mode)."""
    metadata = extract_metadata(html, url=url)
    classification = classify(metadata)
    topics = extract_topics(metadata, max_topics=max_topics)
    return CrawlResult(
        url=url,
        success=True,
        error=None,
        fetch=None,
        metadata=metadata,
        classification=classification,
        topics=topics,
    )
