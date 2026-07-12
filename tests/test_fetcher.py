"""Size-cap tests for the streaming body reader.

We can't test via a local HTTP server: the SSRF guard (correctly) blocks
localhost. Instead we exploit the seam that _read_body only needs an object
with .iter_content() — a stub stands in for a real response.
"""

import time
import unittest

import requests

from crawler.fetcher import _read_body


class FakeResponse:
    """Stands in for requests.Response: yields the given chunks."""

    def __init__(self, chunks, delay_per_chunk: float = 0.0):
        self._chunks = chunks
        self._delay = delay_per_chunk

    def iter_content(self, chunk_size):
        for chunk in self._chunks:
            if self._delay:
                time.sleep(self._delay)
            yield chunk


FAR_FUTURE = time.monotonic() + 3600


class TestReadBody(unittest.TestCase):
    def test_small_body_untouched(self):
        body, truncated = _read_body(FakeResponse([b"hello ", b"world"]), max_bytes=100, deadline=FAR_FUTURE)
        self.assertEqual(body, b"hello world")
        self.assertFalse(truncated)

    def test_body_at_exact_cap_not_truncated(self):
        body, truncated = _read_body(FakeResponse([b"x" * 100]), max_bytes=100, deadline=FAR_FUTURE)
        self.assertEqual(len(body), 100)
        self.assertFalse(truncated)

    def test_oversized_body_truncated_to_exact_cap(self):
        chunks = [b"a" * 40, b"b" * 40, b"c" * 40]  # 120 bytes total
        body, truncated = _read_body(FakeResponse(chunks), max_bytes=100, deadline=FAR_FUTURE)
        self.assertTrue(truncated)
        self.assertEqual(len(body), 100)  # cap is exact, mid-chunk
        self.assertEqual(body, b"a" * 40 + b"b" * 40 + b"c" * 20)

    def test_endless_stream_stops_at_cap(self):
        def endless():
            while True:
                yield b"z" * 1024

        class EndlessResponse:
            def iter_content(self, chunk_size):
                return endless()

        body, truncated = _read_body(EndlessResponse(), max_bytes=10 * 1024, deadline=FAR_FUTURE)
        self.assertTrue(truncated)
        self.assertEqual(len(body), 10 * 1024)

    def test_deadline_exceeded_raises_timeout(self):
        slow = FakeResponse([b"x"] * 50, delay_per_chunk=0.02)
        with self.assertRaises(requests.Timeout):
            _read_body(slow, max_bytes=10_000, deadline=time.monotonic() + 0.05)


if __name__ == "__main__":
    unittest.main()
