"""HTTP API for the crawler.

Run locally:
    uvicorn crawler.api:app --reload

Then:
    GET http://127.0.0.1:8000/crawl?url=https://example.com
    GET http://127.0.0.1:8000/docs   (interactive API docs, auto-generated)

FastAPI turns each decorated function into an HTTP endpoint: it parses and
validates query parameters from the function signature, converts the returned
dict to a JSON response, and documents everything at /docs automatically.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from crawler import __version__
from crawler.pipeline import crawl

app = FastAPI(
    title="Core Web Crawler",
    description="Fetch a URL, extract HTML metadata, classify the page, and return relevant topics.",
    version=__version__,
)


@app.get("/")
def root() -> dict:
    """Landing route so the base URL isn't a 404 in a demo."""
    return {
        "service": "core-web-crawler",
        "version": __version__,
        "usage": "GET /crawl?url=<page url>",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict:
    """Liveness probe. AWS load balancers/App Runner poll this to know the service is up."""
    return {"status": "ok"}


@app.get("/crawl")
def crawl_url(
    url: str = Query(..., description="Page URL to crawl", min_length=4),
    max_topics: int = Query(10, ge=1, le=50, description="Maximum topics to return"),
    timeout: float = Query(15.0, ge=1.0, le=60.0, description="Fetch timeout in seconds"),
) -> dict:
    """Crawl one URL and return metadata, page classification, and topics.

    The heavy lifting is the existing pipeline; this function only translates
    between HTTP and Python: query params in, JSON out, HTTP status codes for
    failures.
    """
    result = crawl(url, max_topics=max_topics, timeout=timeout)

    if not result.success:
        if result.fetch is not None and result.fetch.blocked:
            # 400 Bad Request: WE refused this URL (SSRF guard) — the caller
            # asked for something this service will never do.
            raise HTTPException(status_code=400, detail={"url": url, "error": result.error})
        # 502 Bad Gateway = "the upstream site failed us", which is accurate:
        # our service worked, the target page couldn't be fetched.
        raise HTTPException(status_code=502, detail={"url": url, "error": result.error})

    return result.to_dict()
