"""Core web crawler: fetch a URL, extract metadata, classify the page, and surface topics."""

from crawler.fetcher import fetch
from crawler.parser import extract_metadata
from crawler.classifier import classify
from crawler.topics import extract_topics
from crawler.pipeline import crawl

__all__ = ["fetch", "extract_metadata", "classify", "extract_topics", "crawl"]
__version__ = "0.1.0"
