# Core Web Crawler

A generic single-page crawler: give it any URL and it returns the page's HTML
metadata, a page-type classification, and a ranked list of relevant topics.

**Live demo:** [edabpk62tn.us-east-1.awsapprunner.com/docs](https://edabpk62tn.us-east-1.awsapprunner.com/docs)
— deployed on AWS App Runner (Docker image on ECR). Try
[`/crawl?url=...`](https://edabpk62tn.us-east-1.awsapprunner.com/crawl?url=https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai)
directly, or use the interactive Swagger UI. *(Demo deployment — may be taken
down to save costs; everything runs locally per the instructions below.)*

## What it does

```
URL ──> fetch ──> extract metadata ──> classify page type ──> extract topics
```

1. **Fetch** ([fetcher.py](crawler/fetcher.py)) — HTTP GET with realistic browser
   headers, redirect following, retries with exponential backoff on 429/5xx, and
   encoding detection. Never raises; failures are reported as structured errors.
2. **Metadata extraction** ([parser.py](crawler/parser.py)) — title, meta
   description/keywords, canonical URL, language, author, published date,
   Open Graph and Twitter Card tags, JSON-LD `@type`s, headings (h1–h3),
   cleaned body text (scripts/nav/footer stripped), and word/link/image counts.
3. **Classification** ([classifier.py](crawler/classifier.py)) — weighted-vote
   classifier over four signal tiers, strongest first: JSON-LD structured data,
   `og:type`, URL path patterns, then content heuristics (price + cart language,
   link density, long-form text). Labels: `product`, `article`, `blog_post`,
   `news`, `video`, `recipe`, `forum_discussion`, `documentation`, `homepage`,
   `category_listing`, `other`. Output includes a confidence score and the
   exact signals that fired, so every decision is explainable.
4. **Topic extraction** ([topics.py](crawler/topics.py)) — zone-weighted n-gram
   scoring (title and meta keywords count 5x body text), with a length bonus so
   multi-word phrases outrank their fragments, stopword filtering, and
   deduplication of phrases subsumed by higher-ranked ones. No ML dependency.

## Usage

```bash
pip install -r requirements.txt

# Human-readable summary
python -m crawler "https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai"

# Multiple URLs, full JSON output
python -m crawler <url1> <url2> --json --topics 8
```

### As an HTTP service

[crawler/api.py](crawler/api.py) wraps the pipeline in a FastAPI app:

```bash
python -m uvicorn crawler.api:app --port 8000
# GET http://127.0.0.1:8000/crawl?url=<page>   -> JSON result
# GET http://127.0.0.1:8000/docs               -> interactive Swagger UI
# GET http://127.0.0.1:8000/health             -> liveness probe
```

Status codes: `200` success, `400` URL refused by the SSRF guard,
`422` invalid parameters, `502` target site unreachable.

### With Docker

```bash
docker build -t crawler-api .
docker run -d -p 8000:8000 crawler-api
```

The image (Python 3.12-slim, non-root user) is the deployment artifact for
any container platform (AWS App Runner / ECS, Cloud Run, etc.).

## Hardening (built for public deployment)

- **SSRF guard** ([safety.py](crawler/safety.py)): resolves every hostname
  and refuses private, loopback, link-local (cloud metadata), reserved, and
  multicast addresses — and non-http(s) schemes. Redirects are followed
  manually so every hop is re-validated, closing the open-redirect bypass.
  Blocked URLs return `400` with the reason.
- **Response size cap** (streaming fetcher): bodies are read in chunks and
  capped at 5 MiB — enforced on bytes received, never on the Content-Length
  claim — with a wall-clock deadline against drip-feed responses. Oversized
  pages are truncated, flagged (`"truncated": true`), and still parsed:
  metadata lives in the first megabyte in practice.

As a library:

```python
from crawler import crawl

result = crawl("https://example.com/some/page")
print(result.metadata.title)
print(result.classification.page_type, result.classification.confidence)
print([t.phrase for t in result.topics])
```

`crawler.pipeline.crawl_html(html, url)` runs the parse/classify/topics stages
on HTML you already have (useful for testing or batch processing).

## Test URL results

| URL | Result |
| --- | --- |
| CNN article | `news` (83% confidence) via JSON-LD `NewsArticle` + date-pattern URL + news domain; topics: *tech workers*, *google*, *tech industry*, … |
| Amazon toaster | Amazon serves a bot-check interstitial to non-browser clients — detected and classified `bot_challenge` (`"bot_challenged": true`), beating the `/dp/` product-URL signal: content wins over URL |
| REI blog | REI's CDN (Akamai) drops non-browser TLS fingerprints at the network level — reported as a structured `ReadTimeout` error (see limitations) |

Anti-bot walls served with a deceptive `200` (Reddit "Please wait for
verification", Cloudflare "Just a moment...") are likewise classified
`bot_challenge` rather than reported as real page metadata.

## Design decisions

- **Explainability over black-box accuracy.** The classifier returns the signals
  that fired and per-label scores, not just a label. Rules are trivially
  extensible (add a row to `JSON_LD_MAP` / `URL_PATTERNS`).
- **Structured data first.** Sites annotate their own pages via schema.org
  JSON-LD and Open Graph; trusting that beats guessing from text.
- **Graceful degradation.** Every stage works with partial input — a blocked
  page with a usable URL still gets a classification; a page with no metadata
  still gets topics from body text.
- **Stdlib + minimal deps.** Only `requests`, `beautifulsoup4`, `lxml`.

## Known limitations

- **Bot-protected sites** (Amazon, REI/Akamai) fingerprint TLS handshakes and
  either serve interstitials or drop the connection. Fixing this properly
  requires a real browser engine (e.g., Playwright with
  `playwright.sync_api` + stealth), which was left out to keep the core lean.
  The pipeline is fetcher-agnostic: swap in any fetcher that returns HTML and
  pass it to `crawl_html()`.
- **JavaScript-rendered pages** return only server-side HTML; SPA content that
  renders client-side won't appear in body text (metadata tags usually still do).
- English-oriented stopword list; other languages degrade to frequency-only ranking.

## Scaling design (Parts 2 & 3)

- **[docs/Part2_Design.pdf](docs/Part2_Design.pdf)** — operationalizing collection of
  billions of URLs/month: architecture, storage + unified schema, SLOs/SLAs,
  monitoring, cost model, and the measured bot-wall problem.
- **[docs/Part3_POC.pdf](docs/Part3_POC.pdf)** — engineering path to proof of
  concept: 6-week schedule, blocker analysis with estimates, PoC evaluation
  criteria, and the staged release plan to GA.

## Tests

```bash
python -m unittest discover -s tests -v
```

24 offline tests cover parsing, classification, topic ranking, the
end-to-end pipeline (synthetic product/blog/news HTML fixtures), the SSRF
guard's block/allow decisions, and the streaming size cap (via a stubbed
response object — the SSRF guard itself forbids a localhost test server).
