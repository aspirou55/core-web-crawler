"""Offline tests for parsing, classification, and topic extraction using HTML fixtures."""

import unittest

from crawler.classifier import classify
from crawler.parser import extract_metadata
from crawler.pipeline import crawl_html
from crawler.topics import extract_topics

PRODUCT_HTML = """
<!DOCTYPE html><html lang="en"><head>
<title>Cuisinart CPT-122 Compact 2-Slice Toaster</title>
<meta name="description" content="Compact 2-slice toaster with 7 shade settings.">
<meta property="og:type" content="product">
<script type="application/ld+json">
{"@type": "Product", "name": "Cuisinart Toaster", "offers": {"@type": "Offer", "price": "29.95"}}
</script>
</head><body>
<h1>Cuisinart CPT-122 Compact 2-Slice Toaster</h1>
<p>Price: $29.95. Free shipping. In stock.</p>
<button>Add to Cart</button><p>Buy now for $29.95 or $24.99 used.</p>
</body></html>
"""

BLOG_HTML = """
<!DOCTYPE html><html lang="en"><head>
<title>How to Introduce Your Indoorsy Friend to the Outdoors</title>
<meta name="description" content="Tips for camping with beginners.">
<meta property="og:type" content="article">
<meta property="article:published_time" content="2015-05-01">
<meta name="author" content="REI Staff">
</head><body><article>
<h1>How to Introduce Your Indoorsy Friend to the Outdoors</h1>
<p>{}</p>
</article></body></html>
""".format("Camping with beginners takes patience and planning. " * 80)

NEWS_HTML = """
<!DOCTYPE html><html lang="en"><head>
<title>Google study: AI could impact 90 percent of tech jobs</title>
<meta name="description" content="A new Google study examines AI impact on tech jobs.">
<script type="application/ld+json">{"@type": "NewsArticle"}</script>
</head><body><main>
<h1>Google study says AI could impact 90 percent of tech jobs</h1>
<p>BODY</p>
</main></body></html>
""".replace("BODY", "Artificial intelligence and tech jobs are changing the workforce. " * 60)


class TestParser(unittest.TestCase):
    def test_extracts_core_metadata(self):
        meta = extract_metadata(PRODUCT_HTML, url="https://www.amazon.com/dp/B009GQ034C")
        self.assertEqual(meta.title, "Cuisinart CPT-122 Compact 2-Slice Toaster")
        self.assertIn("2-slice toaster", meta.description.lower())
        self.assertEqual(meta.domain, "amazon.com")
        self.assertEqual(meta.language, "en")
        self.assertIn("Product", meta.json_ld_types)
        self.assertEqual(meta.open_graph.get("type"), "product")

    def test_body_text_strips_scripts(self):
        meta = extract_metadata(PRODUCT_HTML)
        self.assertNotIn("@type", meta.body_text)
        self.assertIn("Add to Cart", meta.body_text)

    def test_author_and_date(self):
        meta = extract_metadata(BLOG_HTML)
        self.assertEqual(meta.author, "REI Staff")
        self.assertEqual(meta.published_date, "2015-05-01")


class TestClassifier(unittest.TestCase):
    def test_product_page(self):
        meta = extract_metadata(PRODUCT_HTML, url="https://www.amazon.com/dp/B009GQ034C")
        result = classify(meta)
        self.assertEqual(result.page_type, "product")
        self.assertGreater(result.confidence, 0.5)

    def test_blog_post(self):
        meta = extract_metadata(BLOG_HTML, url="https://blog.rei.com/camp/how-to-introduce/")
        result = classify(meta)
        self.assertIn(result.page_type, ("blog_post", "article"))

    def test_news_article(self):
        meta = extract_metadata(NEWS_HTML, url="https://www.cnn.com/2025/09/23/tech/google-study")
        result = classify(meta)
        self.assertEqual(result.page_type, "news")

    def test_empty_page_is_other(self):
        meta = extract_metadata("<html><body></body></html>")
        result = classify(meta)
        self.assertEqual(result.page_type, "other")


REDDIT_WALL_HTML = """
<!DOCTYPE html><html><head><title>Reddit - Please wait for verification</title></head>
<body><p>Verifying your request...</p></body></html>
"""

CLOUDFLARE_WALL_HTML = """
<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><h1>www.example.com</h1><p>Checking your browser before accessing the site.
Enable JavaScript and cookies to continue.</p></body></html>
"""

CAPTCHA_ARTICLE_HTML = """
<!DOCTYPE html><html><head><title>The history of the CAPTCHA and online verification</title>
<meta property="article:published_time" content="2024-01-01"></head>
<body><article><h1>The history of the CAPTCHA</h1><p>{}</p></article></body></html>
""".format("Researchers studied how captcha systems verify you are a human online. " * 80)


class TestBotChallengeDetection(unittest.TestCase):
    def test_reddit_verification_wall(self):
        meta = extract_metadata(REDDIT_WALL_HTML, url="https://www.reddit.com/r/foo/comments/bar/")
        self.assertEqual(classify(meta).page_type, "bot_challenge")

    def test_cloudflare_wall(self):
        meta = extract_metadata(CLOUDFLARE_WALL_HTML, url="https://example.com/some/page")
        self.assertEqual(classify(meta).page_type, "bot_challenge")

    def test_amazon_interstitial_beats_product_url(self):
        html = """<!DOCTYPE html><html><head><title>Amazon.com</title></head>
        <body><p>Click the button below to continue shopping.</p></body></html>"""
        meta = extract_metadata(html, url="https://www.amazon.com/dp/B009GQ034C")
        result = classify(meta)
        self.assertEqual(result.page_type, "bot_challenge")

    def test_long_article_about_captchas_not_flagged(self):
        meta = extract_metadata(CAPTCHA_ARTICLE_HTML, url="https://example.com/articles/captcha-history")
        self.assertNotEqual(classify(meta).page_type, "bot_challenge")

    def test_pipeline_exposes_flag(self):
        result = crawl_html(REDDIT_WALL_HTML, url="https://www.reddit.com/r/foo/")
        self.assertTrue(result.to_dict()["bot_challenged"])
        result = crawl_html(NEWS_HTML, url="https://www.cnn.com/2025/09/23/tech/google-study")
        self.assertFalse(result.to_dict()["bot_challenged"])


class TestTopics(unittest.TestCase):
    def test_product_topics_mention_toaster(self):
        meta = extract_metadata(PRODUCT_HTML, url="https://www.amazon.com/dp/B009GQ034C")
        topics = extract_topics(meta)
        joined = " ".join(t.phrase for t in topics)
        self.assertIn("toaster", joined)

    def test_topics_exclude_stopwords(self):
        meta = extract_metadata(NEWS_HTML)
        for topic in extract_topics(meta):
            self.assertNotIn(topic.phrase, ("the", "and", "for", "with"))

    def test_max_topics_respected(self):
        meta = extract_metadata(NEWS_HTML)
        self.assertLessEqual(len(extract_topics(meta, max_topics=5)), 5)


class TestPipeline(unittest.TestCase):
    def test_crawl_html_end_to_end(self):
        result = crawl_html(NEWS_HTML, url="https://www.cnn.com/2025/09/23/tech/google-study")
        self.assertTrue(result.success)
        self.assertEqual(result.classification.page_type, "news")
        self.assertTrue(result.topics)
        payload = result.to_dict()
        self.assertIn("metadata", payload)
        self.assertIn("classification", payload)


if __name__ == "__main__":
    unittest.main()
