"""CLI entry point.

Usage:
    python -m crawler <url> [<url> ...] [--json] [--topics N]
"""

from __future__ import annotations

import argparse
import json
import sys

from crawler.pipeline import CrawlResult, crawl


def _print_human(result: CrawlResult) -> None:
    print("=" * 78)
    print(f"URL: {result.url}")
    if not result.success:
        print(f"  FAILED: {result.error}")
        if result.fetch and result.fetch.status_code:
            print(f"  Status: {result.fetch.status_code}")
        return

    meta = result.metadata
    cls = result.classification
    print(f"  Final URL:   {result.fetch.final_url}")
    print(f"  Status:      {result.fetch.status_code} ({result.fetch.elapsed_seconds}s)")
    print(f"  Title:       {meta.title[:100]}")
    print(f"  Description: {meta.description[:150]}")
    print(f"  Language:    {meta.language or '-'}   Author: {meta.author or '-'}   Published: {meta.published_date or '-'}")
    print(f"  Words: {meta.word_count}   Links: {meta.link_count}   Images: {meta.image_count}")
    if meta.json_ld_types:
        print(f"  JSON-LD:     {', '.join(meta.json_ld_types)}")
    print(f"  Page type:   {cls.page_type}  (confidence {cls.confidence:.0%})")
    for signal in cls.signals[:5]:
        print(f"      - {signal}")
    print("  Topics:")
    for topic in result.topics:
        print(f"      {topic.score:7.1f}  {topic.phrase}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crawler", description="Crawl URLs: metadata, page type, topics.")
    parser.add_argument("urls", nargs="+", help="One or more URLs to crawl")
    parser.add_argument("--json", action="store_true", help="Emit full JSON instead of the human summary")
    parser.add_argument("--topics", type=int, default=10, help="Max topics to return (default 10)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Request timeout in seconds")
    args = parser.parse_args(argv)

    results = [crawl(url, max_topics=args.topics, timeout=args.timeout) for url in args.urls]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        for result in results:
            _print_human(result)

    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
