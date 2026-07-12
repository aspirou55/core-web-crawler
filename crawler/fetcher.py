"""HTTP fetching with retries, realistic headers, and graceful error reporting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests

from crawler.safety import BlockedUrlError, validate_public_url

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB: generous for HTML, small enough to never hurt
CHUNK_SIZE = 64 * 1024


def _read_body(response, max_bytes: int, deadline: float) -> tuple[bytes, bool]:
    """Read a streaming response body, capped at max_bytes and a wall-clock deadline.

    Returns (bytes, truncated). We count bytes as they ARRIVE rather than
    trusting the Content-Length header, because that header is just the
    server's claim. The deadline guards against drip-feed responses: the
    request timeout only limits silence between bytes, not total duration.
    """
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
        if time.monotonic() > deadline:
            raise requests.Timeout("total download time exceeded")
        total += len(chunk)
        if total > max_bytes:
            keep = max_bytes - (total - len(chunk))
            chunks.append(chunk[:keep])
            return b"".join(chunks), True
        chunks.append(chunk)
    return b"".join(chunks), False


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status_code: int | None = None
    html: str = ""
    content_type: str = ""
    elapsed_seconds: float = 0.0
    error: str | None = None
    blocked: bool = False  # True when the SSRF guard refused the URL (caller error, not site failure)
    truncated: bool = False  # True when the body hit the size cap; html holds the first max_bytes
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200 and bool(self.html)


def _get_with_guarded_redirects(
    session: requests.Session, url: str, timeout: float, max_redirects: int
) -> requests.Response:
    """GET a URL, following redirects manually and SSRF-validating every hop.

    requests' automatic redirect following is disabled because each redirect
    target is a brand-new URL an attacker may control; each one must pass the
    same public-address check as the original.
    """
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current)
        # stream=True: receive headers now, but do NOT download the body yet.
        # The caller reads it chunk-by-chunk with a size cap (_read_body).
        response = session.get(current, timeout=timeout, allow_redirects=False, stream=True)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()  # a redirect's body is irrelevant; release the connection
            if not location:
                return response
            # Location may be relative ("/new/path"); resolve it against the current URL.
            current = urljoin(current, location)
            continue
        return response
    raise requests.TooManyRedirects(f"more than {max_redirects} redirects")


def fetch(
    url: str,
    timeout: float = 15.0,
    max_retries: int = 2,
    backoff: float = 1.5,
    max_redirects: int = 5,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> FetchResult:
    """Fetch a URL and return the raw HTML plus response details.

    Refuses non-public targets (SSRF guard), retries on transient status codes
    (429/5xx) with exponential backoff, and caps the downloaded body at
    max_bytes (oversized pages are truncated, not failed — metadata lives at
    the top of the document).
    Never raises: failures are reported in FetchResult.error.
    """
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    result = FetchResult(url=url)
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for attempt in range(max_retries + 1):
        start = time.monotonic()
        try:
            response = _get_with_guarded_redirects(session, url, timeout, max_redirects)
        except BlockedUrlError as exc:
            result.error = f"Blocked by SSRF guard: {exc}"
            result.blocked = True
            return result  # deliberate refusal: never retry
        except requests.RequestException as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(backoff * (2**attempt))
                continue
            return result

        result.status_code = response.status_code
        result.final_url = response.url
        result.content_type = response.headers.get("Content-Type", "")
        result.headers = dict(response.headers)

        if response.status_code in RETRYABLE_STATUS and attempt < max_retries:
            response.close()
            time.sleep(backoff * (2**attempt))
            continue

        if response.status_code != 200:
            response.close()
            result.error = f"HTTP {response.status_code}"
            return result

        # Body download: streamed, size-capped, wall-clock-bounded. Reading can
        # fail mid-stream (connection drop), so it gets the same retry treatment
        # as the initial request.
        try:
            raw, result.truncated = _read_body(response, max_bytes, deadline=start + timeout * 4)
        except requests.RequestException as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            if attempt < max_retries:
                time.sleep(backoff * (2**attempt))
                continue
            return result
        finally:
            response.close()

        result.elapsed_seconds = round(time.monotonic() - start, 3)

        # We bypassed response.text, so we decode ourselves: the charset the
        # server declared in its headers, else UTF-8. errors="replace" swaps
        # undecodable bytes for a placeholder instead of crashing.
        try:
            text = raw.decode(response.encoding or "utf-8", errors="replace")
        except LookupError:  # server declared a charset Python has never heard of
            text = raw.decode("utf-8", errors="replace")

        if "html" not in result.content_type and not text.lstrip().lower().startswith(("<!doctype", "<html")):
            result.error = f"Non-HTML content: {result.content_type or 'unknown'}"
            return result

        result.html = text
        result.error = None
        return result

    return result
