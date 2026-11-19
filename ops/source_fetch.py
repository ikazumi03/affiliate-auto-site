"""Bounded, stdlib-only source retrieval; retrieval is NOT fact verification.

All redirects (including robots redirects) are refused in this preparation version.
A robots.txt 404 allows retrieval; all other robots failures fail closed. DNS is a
best-effort preflight, NOT DNS pinning. Environment proxies are disabled. Only
robots.txt and the configured source are requested: at most two requests. Caller
allowed_hosts is ignored; only ALLOWED_SOURCE_HOSTS controls host authorization.
Visibility extraction cannot evaluate external CSS or execute JavaScript.
"""

import hashlib
import ipaddress
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
from urllib import error, parse, request, robotparser

ALLOWED_SOURCE_HOSTS = frozenset({"onsuku.jp", "faq.onsuku.jp"})
USER_AGENT = "KurashiSourcePreparation/1.0 (+https://affiliate-auto-site-1tk.pages.dev)"
MAX_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 200 * 1024
TIMEOUT = 10
CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
TRACKING_KEYS = frozenset({
    "af", "af_id", "afbetc", "clickid", "click_id", "gclid", "fbclid", "msclkid",
    "ref", "refid", "ref_id", "referrer", "referral", "tracking", "tracking_id",
})


class SourceError(Exception):
    """Safe retrieval failure; messages never include response bodies."""


class SafeRedirect(request.HTTPRedirectHandler):
    """No redirect is followed; the nominal bound is also limited to three."""

    max_redirections = 3
    max_repeats = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError("Redirects are refused in this preparation version")

    def http_error_302(self, req, fp, code, msg, headers):
        # Do not drain an unbounded redirect body or leak its connection.
        fp.close()
        raise SourceError("Redirects are refused in this preparation version")

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _validate_url(url):
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise SourceError("A nonempty, whitespace-free HTTPS URL is required")
    if "\\" in url or "\x7f" in url:
        raise SourceError("Invalid URL characters")
    try:
        parts = parse.urlsplit(url)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise SourceError("Invalid URL") from None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        raise SourceError("Only HTTPS URLs without userinfo are permitted")
    if host not in ALLOWED_SOURCE_HOSTS or port not in (None, 443):
        raise SourceError("URL host or port is not approved")
    if parts.fragment:
        raise SourceError("URL fragments are not permitted")
    for key, _ in parse.parse_qsl(parts.query, keep_blank_values=True):
        key = key.lower()
        if key in TRACKING_KEYS or key.startswith(("utm_", "a8", "aff", "afb")):
            raise SourceError("Affiliate or tracking query parameters are not permitted")
    return parts


def _check_dns(host):
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        if not answers:
            raise SourceError("DNS returned no addresses")
        for answer in answers:
            address = ipaddress.ip_address(answer[4][0])
            if not address.is_global or address.is_multicast or address.is_reserved:
                raise SourceError("DNS returned a non-public address")
    except (OSError, ValueError):
        raise SourceError("Public DNS preflight failed") from None


def _check_final(final_url, requested_url):
    _validate_url(final_url)
    if final_url != requested_url:
        raise SourceError("Redirects are refused in this preparation version")


def _read(opener, url, limit, robots=False):
    parts = _validate_url(url)
    _check_dns(parts.hostname)
    req = request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Accept": "text/plain" if robots else ", ".join(sorted(CONTENT_TYPES)),
    })
    try:
        with opener.open(req, timeout=TIMEOUT) as response:
            final_url = response.geturl()
            _check_final(final_url, url)
            status = response.getcode()
            if robots and status == 404:
                return b"", final_url, status, "text/plain", "utf-8"
            if 300 <= status < 400:
                raise SourceError("Redirects are refused in this preparation version")
            if status != 200:
                raise SourceError("HTTP response was not successful")
            encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
            if encoding != "identity":
                raise SourceError("Compressed responses are not permitted")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            permitted = {"text/plain"} if robots else CONTENT_TYPES
            if content_type not in permitted:
                raise SourceError("Response content type is not permitted")
            body = response.read(limit + 1)
            if len(body) > limit:
                raise SourceError("Response exceeded the byte limit")
            charset = response.headers.get_content_charset() or "utf-8"
            return body, final_url, status, content_type, charset
    except error.HTTPError as exc:
        try:
            _check_final(exc.geturl(), url)
            if robots and exc.code == 404:
                return b"", url, 404, "text/plain", "utf-8"
            if 300 <= exc.code < 400:
                raise SourceError("Redirects are refused in this preparation version") from None
            raise SourceError("HTTP response was not successful") from None
        finally:
            exc.close()
    except (error.URLError, OSError, HTTPException):
        raise SourceError("Source transport failed") from None


class _VisibleText(HTMLParser):
    VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
    OMIT = frozenset({"script", "style", "noscript", "head", "template"})
    BLOCK = frozenset("p div br hr li ul ol section article h1 h2 h3 h4 h5 h6 tr td th".split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        style = re.sub(r"/\*.*?\*/", "", attrs.get("style") or "", flags=re.S)
        style = re.sub(r"\s+", "", style).lower()
        hidden = (bool(self.stack and self.stack[-1][1]) or tag in self.OMIT
                  or "hidden" in attrs or (attrs.get("aria-hidden") or "").lower() == "true"
                  or bool(re.search(r"(?:^|;)display:none(?:!important)?(?:;|$)", style)))
        if not hidden and tag in self.BLOCK:
            self.parts.append(" ")
        if tag not in self.VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not (self.stack and self.stack[-1][1]) and tag in self.BLOCK:
            self.parts.append(" ")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]):
            self.parts.append(data)


def fetch_source(source: dict) -> dict:
    """Fetch a configured official source without treating its text as instructions."""
    if not isinstance(source, dict) or not isinstance(source.get("id"), str) or not source["id"].strip():
        raise SourceError("Source id must be a nonempty string")
    url = source.get("url")
    parts = _validate_url(url)
    # Disable ambient proxies: DNS preflight must concern the actual destination.
    opener = request.build_opener(request.ProxyHandler({}), SafeRedirect())
    robots_url = parse.urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    robots_body, _, robots_status, _, _ = _read(opener, robots_url, MAX_ROBOTS_BYTES, robots=True)
    if robots_status == 200:
        policy = robotparser.RobotFileParser(robots_url)
        try:
            policy.parse(robots_body.decode("utf-8-sig").splitlines())
        except (UnicodeError, ValueError):
            raise SourceError("robots.txt could not be parsed safely") from None
        if not policy.can_fetch(USER_AGENT, url):
            raise SourceError("robots.txt disallows source retrieval")
    body, final_url, status, content_type, charset = _read(opener, url, MAX_BYTES)
    try:
        decoded = body.decode(charset, errors="strict")
    except (LookupError, UnicodeError):
        raise SourceError("Unsupported charset or invalid response encoding") from None
    if content_type == "text/plain":
        text = " ".join(decoded.split())
    else:
        parser = _VisibleText()
        try:
            parser.feed(decoded)
            parser.close()
        except (AssertionError, ValueError):
            raise SourceError("HTML could not be parsed safely") from None
        text = " ".join("".join(parser.parts).split())
    if not text:
        raise SourceError("Source body contains no usable visible text")
    return {
        "id": source["id"], "requested_url": url, "final_url": final_url,
        "http_status": status, "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "text": text,
        "robots_checked": True, "fact_verification": "not_performed", "trusted_for_instructions": False,
    }
