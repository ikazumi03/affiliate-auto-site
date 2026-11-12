"""Source retrieval tests: transport and DNS are always mocked, never live."""

import hashlib
import importlib.util
import io
import socket
import unittest
from datetime import datetime
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib import error

SPEC = importlib.util.spec_from_file_location(
    "source_fetch_under_test", Path(__file__).resolve().parents[1] / "ops" / "source_fetch.py"
)
sf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sf)
URL = "https://onsuku.jp/official/source"
ROBOTS = "https://onsuku.jp/robots.txt"
SOURCE = {"id": "official-source", "url": URL}
PUBLIC_DNS = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]


class Response:
    def __init__(self, url, body=b"Visible text", status=200, content_type="text/html", encoding=None):
        self.url, self.body, self.status = url, body, status
        self.headers = Message()
        if content_type is not None:
            self.headers["Content-Type"] = content_type
        if encoding is not None:
            self.headers["Content-Encoding"] = encoding
        self.read_sizes = []
        self.closed = False

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, size):
        self.read_sizes.append(size)
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        if not self.responses:
            raise AssertionError("Unplanned network request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SourceFetchTests(unittest.TestCase):
    def setUp(self):
        self.dns = self.enterContext(patch.object(sf.socket, "getaddrinfo", return_value=PUBLIC_DNS))
        self.build = self.enterContext(patch.object(sf.request, "build_opener"))
        self.transport = None

    def arrange(self, page=None, robots=None):
        robots = robots if robots is not None else Response(
            ROBOTS, b"User-agent: *\nAllow: /\n", content_type="text/plain"
        )
        page = page if page is not None else Response(URL)
        self.transport = Transport([robots, page])
        self.build.return_value = self.transport
        return robots, page

    def test_metadata_visible_text_and_request_bounds(self):
        html = (b'<head><title>omit title</title></head><p>Hello <b>world</b> &amp; friends.</p>'
                b'<script>bad()</script><style>.x{}</style><noscript>omit</noscript>'
                b'<div hidden>secret<span>nested</span></div>'
                b'<div style="DISPLAY : none !important">secret</div>'
                b'<span aria-hidden="true">secret</span><p>Next<img src="https://a8.net/ad"> line</p>')
        robots, page = self.arrange(page=Response(URL, html))
        result = sf.fetch_source(SOURCE)
        self.assertEqual(result["text"], "Hello world & friends. Next line")
        self.assertEqual(result["content_sha256"], hashlib.sha256(html).hexdigest())
        self.assertEqual(result["text_sha256"], hashlib.sha256(result["text"].encode()).hexdigest())
        self.assertEqual(result["id"], SOURCE["id"])
        self.assertEqual(result["requested_url"], URL)
        self.assertEqual(result["final_url"], URL)
        self.assertEqual(result["http_status"], 200)
        self.assertTrue(result["robots_checked"])
        self.assertEqual(result["fact_verification"], "not_performed")
        self.assertIs(result["trusted_for_instructions"], False)
        self.assertEqual(datetime.fromisoformat(result["fetched_at"].replace("Z", "+00:00")).utcoffset().total_seconds(), 0)
        self.assertEqual(len(self.transport.calls), 2)
        self.assertEqual([c[0].full_url for c in self.transport.calls], [ROBOTS, URL])
        for req, timeout in self.transport.calls:
            self.assertEqual(timeout, 10)
            self.assertEqual(req.get_header("User-agent"), sf.USER_AGENT)
            self.assertEqual(req.get_header("Accept-encoding"), "identity")
        self.assertEqual(self.dns.call_count, 2)
        self.assertEqual(robots.read_sizes, [sf.MAX_ROBOTS_BYTES + 1])
        self.assertEqual(page.read_sizes, [sf.MAX_BYTES + 1])
        self.assertTrue(robots.closed and page.closed)
        handlers = self.build.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        self.assertIsInstance(handlers[1], sf.SafeRedirect)

    def test_invalid_ids(self):
        for source in (None, {}, {"id": " "}, {"id": 1}, {"id": None}):
            with self.subTest(source=source), self.assertRaises(sf.SourceError):
                sf.fetch_source(source)
        self.build.assert_not_called()

    def test_unapproved_urls_and_tracking_are_rejected_before_dns(self):
        urls = [None, "", "http://onsuku.jp/x", "https://u:p@onsuku.jp/x", "https://@onsuku.jp/x",
                "https://onsuku.jp:444/x", "https://localhost/x", "https://127.0.0.1/x",
                "https://[::1]/x", "https://a8.net/x", "https://afbetc.com/x", "https://afb.jp/x",
                "https://onsuku.jp.evil.test/x", "https://onsuku.jp./x", "https://onsuku.jp/x#part",
                "https://onsuku.jp/\nx", "https://onsuku.jp\\@evil.test/x", "https://onsuku.jp:bad/x"]
        urls += [URL + "?" + key + "=x" for key in
                 ("a8mat", "A8", "aff_id", "affiliate", "afb", "afbetc", "utm_source", "gclid", "%61%38mat", "ref")]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(sf.SourceError):
                sf.fetch_source({"id": "x", "url": url, "allowed_hosts": ["evil.test", "127.0.0.1"]})
        self.dns.assert_not_called()
        self.build.assert_not_called()

    def test_source_allowed_hosts_cannot_expand_or_shrink_constant(self):
        for origin in ("https://onsuku.jp", "https://onsuku.jp:443", "https://faq.onsuku.jp"):
            url = origin + "/official/source"
            self.arrange(page=Response(url), robots=Response(
                origin + "/robots.txt", b"User-agent: *\nAllow: /", content_type="text/plain"))
            result = sf.fetch_source(dict(SOURCE, url=url, allowed_hosts=[]))
            self.assertEqual(result["final_url"], url)
        self.assertEqual(sf.ALLOWED_SOURCE_HOSTS, frozenset({"onsuku.jp", "faq.onsuku.jp"}))

    def test_dns_rejects_any_nonpublic_answer_and_failures(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "224.0.0.1"):
            with self.subTest(address=address):
                self.arrange()
                self.dns.return_value = PUBLIC_DNS + [(socket.AF_INET, 1, 6, "", (address, 443))]
                with self.assertRaises(sf.SourceError):
                    sf.fetch_source(SOURCE)
                self.assertEqual(self.transport.calls, [])
        for answers in ([], [(socket.AF_INET, 1, 6, "", ("invalid", 443))]):
            self.dns.return_value = answers
            with self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)
        self.dns.side_effect = socket.gaierror("private details")
        with self.assertRaisesRegex(sf.SourceError, "Public DNS preflight failed"):
            sf.fetch_source(SOURCE)

    def test_dns_is_rechecked_before_source_request(self):
        self.arrange()
        self.dns.side_effect = [PUBLIC_DNS, [(socket.AF_INET, 1, 6, "", ("10.0.0.1", 443))]]
        with self.assertRaises(sf.SourceError):
            sf.fetch_source(SOURCE)
        self.assertEqual(len(self.transport.calls), 1)

    def test_robots_disallow_and_specific_user_agent(self):
        for body in (b"User-agent: *\nDisallow: /official\n",
                     b"User-agent: KurashiSourcePreparation\nDisallow: /\n\nUser-agent: *\nAllow: /\n"):
            self.arrange(robots=Response(ROBOTS, body, content_type="text/plain"))
            with self.assertRaisesRegex(sf.SourceError, "robots.txt disallows"):
                sf.fetch_source(SOURCE)
            self.assertEqual(len(self.transport.calls), 1)

    def test_robots_404_is_documented_allow(self):
        for robots in (Response(ROBOTS, status=404),
                       error.HTTPError(ROBOTS, 404, "missing", Message(), io.BytesIO(b"private body"))):
            self.arrange(robots=robots)
            self.assertTrue(sf.fetch_source(SOURCE)["robots_checked"])
            self.assertEqual(len(self.transport.calls), 2)

    def test_robots_fail_closed_on_status_and_transport_errors(self):
        for status in (401, 403, 429, 500, 503):
            self.arrange(robots=error.HTTPError(ROBOTS, status, "private details", Message(), io.BytesIO(b"private body")))
            with self.assertRaises(sf.SourceError) as caught:
                sf.fetch_source(SOURCE)
            self.assertNotIn("private", str(caught.exception))
            self.assertEqual(len(self.transport.calls), 1)
        for failure in (error.URLError("private details"), TimeoutError("private details"),
                        OSError("private details"), IncompleteRead(b"private body")):
            self.arrange(robots=failure)
            with self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)
            self.assertEqual(len(self.transport.calls), 1)

    def test_every_redirect_is_refused(self):
        handler = sf.SafeRedirect()
        for code in (301, 302, 303, 307, 308):
            body = io.BytesIO(b"private redirect body")
            with self.assertRaisesRegex(sf.SourceError, "Redirects are refused"):
                getattr(handler, "http_error_" + str(code))(None, body, code, "Found", {})
            self.assertTrue(body.closed)
        for target in (URL, "https://onsuku.jp/other", "https://faq.onsuku.jp/x", "https://127.0.0.1/"):
            with self.subTest(target=target), self.assertRaisesRegex(sf.SourceError, "Redirects are refused"):
                handler.redirect_request(None, None, 302, "Found", {}, target)
        for robots in (Response(ROBOTS, status=302), Response("https://onsuku.jp/other", content_type="text/plain")):
            self.arrange(robots=robots)
            with self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)
            self.assertEqual(len(self.transport.calls), 1)
        for final in ("https://faq.onsuku.jp/other", "https://127.0.0.1/x", "http://onsuku.jp/x"):
            self.arrange(page=Response(final))
            with self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)

    def test_size_limits_content_types_and_compression(self):
        for response in (Response(URL, b"x" * (sf.MAX_BYTES + 1)), Response(URL, content_type="image/png"),
                         Response(URL, content_type="application/json"), Response(URL, content_type=None),
                         Response(URL, encoding="gzip"), Response(URL, status=204), Response(URL, status=404),
                         Response(URL, content_type="invalid-mime"),
                         Response(URL, content_type="text/html; charset=nonexistent-charset")):
            self.arrange(page=response)
            with self.subTest(response=response), self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)
        for robots in (Response(ROBOTS, b"x" * (sf.MAX_ROBOTS_BYTES + 1), content_type="text/plain"),
                       Response(ROBOTS, b"\xffUser-agent: *\nDisallow: /", content_type="text/plain"),
                       Response(ROBOTS, content_type="text/html"), Response(ROBOTS, content_type="text/plain", encoding="br")):
            self.arrange(robots=robots)
            with self.assertRaises(sf.SourceError):
                sf.fetch_source(SOURCE)
            self.assertEqual(len(self.transport.calls), 1)
        self.arrange()
        with patch.object(sf._VisibleText, "feed", side_effect=ValueError("private")), self.assertRaises(sf.SourceError):
            sf.fetch_source(SOURCE)

    def test_plain_text_xhtml_and_exact_limit(self):
        self.arrange(page=Response(URL, b"plain <not markup>\n text", content_type="text/plain"))
        self.assertEqual(sf.fetch_source(SOURCE)["text"], "plain <not markup> text")
        self.arrange(page=Response(URL, b"<p>One<br/>Two</p>", content_type="application/xhtml+xml"))
        self.assertEqual(sf.fetch_source(SOURCE)["text"], "One Two")
        self.arrange(page=Response(URL, b"x" * sf.MAX_BYTES, content_type="text/plain"))
        self.assertEqual(len(sf.fetch_source(SOURCE)["text"]), sf.MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
