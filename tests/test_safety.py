"""SSRF guard tests: dangerous URLs must be rejected, public ones allowed.

Block cases use IP literals or names in the local hosts file (localhost), so
no network access is needed. The one allow case uses a well-known public IP
literal to avoid depending on DNS in tests.
"""

import unittest

from crawler.fetcher import fetch
from crawler.safety import BlockedUrlError, validate_public_url


class TestValidatePublicUrl(unittest.TestCase):
    def assert_blocked(self, url: str) -> None:
        with self.assertRaises(BlockedUrlError, msg=f"should have blocked {url}"):
            validate_public_url(url)

    def test_blocks_aws_metadata_endpoint(self):
        # THE classic SSRF target: link-local address serving IAM credentials.
        self.assert_blocked("http://169.254.169.254/latest/meta-data/")

    def test_blocks_loopback(self):
        self.assert_blocked("http://127.0.0.1:8000/")
        self.assert_blocked("http://localhost:6379/")

    def test_blocks_private_ranges(self):
        self.assert_blocked("http://10.0.0.5/admin")
        self.assert_blocked("http://172.16.0.1/")
        self.assert_blocked("http://192.168.1.1/router")

    def test_blocks_unspecified(self):
        self.assert_blocked("http://0.0.0.0/")

    def test_blocks_non_http_schemes(self):
        self.assert_blocked("file:///etc/passwd")
        self.assert_blocked("ftp://192.0.2.1/")
        self.assert_blocked("gopher://example.com/")

    def test_blocks_missing_host(self):
        self.assert_blocked("http:///no-host-here")

    def test_allows_public_ip(self):
        # 8.8.8.8 is Google's public DNS: unambiguously a public address.
        validate_public_url("http://8.8.8.8/")  # must not raise


class TestFetchIntegration(unittest.TestCase):
    def test_fetch_reports_blocked_without_raising(self):
        result = fetch("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertIn("SSRF", result.error)


if __name__ == "__main__":
    unittest.main()
