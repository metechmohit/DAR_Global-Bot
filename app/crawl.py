"""Resumable public-web collector. CSV is always written before any indexing.

No private API guesses, OTP flows, CAPTCHA bypass or authenticated requests.
Run with --browser for optional JS rendering; source restrictions remain respected.
"""
import gzip
import json
import logging
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit, urljoin, parse_qsl, urlencode, urlunsplit
from .common import canonical_url, now, append_csv, read_csv
from .config import DATA, RAW, ROOT
from .htmltools import parse_html

LOG = logging.getLogger("collector")
AGENT = "PropertyAtlasAssignment/1.0 (public real-estate research; low-rate collector)"
HOSTS = {"darglobal.co.uk", "cdn.darglobal.co.uk", "wasalt.sa", "auction.wasalt.sa", "blog.wasalt.sa"}
SKIP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".svg", ".zip", ".css", ".js", ".woff2")
SEEDS = {
    "darglobal": ["https://darglobal.co.uk/projects", "https://darglobal.co.uk/faq", "https://darglobal.co.uk/about", "https://darglobal.co.uk/press", "https://darglobal.co.uk/investor", "https://darglobal.co.uk/get-in-touch"],
    "wasalt": ["https://wasalt.sa/en", "https://wasalt.sa/en/properties-for-sale-in-saudi-arabia", "https://wasalt.sa/en/properties-for-rent-in-saudi-arabia", "https://wasalt.sa/en/properties-for-daily-rental-in-saudi-arabia", "https://wasalt.sa/en/corporate", "https://wasalt.sa/en/wb-daily-rentals", "https://auction.wasalt.sa/en", "https://blog.wasalt.sa/en/"],
}
for purpose in ("sale", "rent", "daily-rental"):
    for city in ("riyadh", "jeddah", "dammam", "makkah", "madinah", "al-khobar", "taif", "abha"):
        SEEDS["wasalt"].append(f"https://wasalt.sa/en/properties-for-{purpose}-in-{city}")


def allowed(url):
    p = urlsplit(url)
    host = (p.hostname or "").removeprefix("www.")
    return p.scheme in ("https", "http") and host in HOSTS and not p.username and not p.password and p.port in (None, 80, 443)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise urllib.error.URLError("Redirect left the public source allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def useful(url, include_arabic=False):
    if not allowed(url):
        return False
    p = urlsplit(url)
    path = p.path.lower()
    if path.endswith(SKIP_EXTENSIONS):
        return False
    if re.search(r"/(login|signup|sign-in|register|checkout|wallet|account|profile|favorites|post-property)(/|$)", path):
        return False
    if not include_arabic and re.search(r"^/ar(?:/|$)", path):
        return False
    # Prevent combinatorial parameter explosions. Explicit seeds/files may still
    # introduce a specific supported search partition.
    return len(parse_qsl(p.query)) <= 7


class Collector:
    def __init__(self, source="all", max_pages=250, delay=2, browser=False, include_arabic=False, refresh=False):
        self.source, self.max_pages, self.delay = source, max_pages, max(1, delay)
        self.include_arabic, self.browser, self.refresh = include_arabic, browser, refresh
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.robot_cache, self.last_request = {}, {}
        self.output = RAW / ("crawl_" + now().replace(":", "-").replace(".", "-") + ".csv")
        self.state_path = DATA / ("crawl-state-" + source + ".json")
        self.seen, self.pending, self.queued = set(), deque(), set()
        self.pw = self.browser_instance = self.browser_context = None

    def request(self, url, timeout=25):
        if not allowed(url):
            raise ValueError("URL outside source allowlist")
        host = urlsplit(url).netloc
        wait = self.delay - (time.monotonic() - self.last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self.last_request[host] = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/xml,application/pdf;q=0.8,*/*;q=0.5", "Accept-Encoding": "gzip"})
        for attempt in range(3):
            try:
                with self.opener.open(req, timeout=timeout) as response:
                    content = response.read(15_000_001)
                    if len(content) > 15_000_000:
                        raise ValueError("Response exceeded 15 MB limit")
                    if response.headers.get("Content-Encoding") == "gzip":
                        content = gzip.decompress(content)
                    return response.geturl(), response.headers.get("Content-Type", ""), content
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 502, 503, 504) or attempt == 2:
                    raise
                retry = exc.headers.get("Retry-After", "")
                if retry.isdigit() and int(retry) > 30:
                    # Leave long provider backoff for a later resumable run.
                    raise
                time.sleep(max(self.delay, int(retry) if retry.isdigit() else 2 ** (attempt+1)))
            except urllib.error.URLError:
                if attempt == 2:
                    raise
                time.sleep(max(self.delay, 2 ** (attempt+1)))

    def permitted(self, url):
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robot_cache:
            robot = urllib.robotparser.RobotFileParser()
            try:
                _, _, body = self.request(origin + "/robots.txt")
                robot.parse(body.decode("utf-8", "replace").splitlines())
                for sitemap in robot.site_maps() or []:
                    self.enqueue(sitemap)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    robot.parse([])
                else:
                    LOG.warning("robots.txt unavailable for %s (HTTP %s); skipping this host", origin, e.code)
                    robot.disallow_all = True
            except (OSError, ValueError) as e:
                LOG.warning("Cannot establish crawl policy for %s: %s", origin, e)
                robot.disallow_all = True
            self.robot_cache[origin] = robot
        robot = self.robot_cache[origin]
        delay = robot.crawl_delay(AGENT) or robot.crawl_delay("*")
        if delay:
            self.delay = max(self.delay, float(delay))
        return robot.can_fetch(AGENT, url)

    def enqueue(self, url):
        url = canonical_url(url)
        if useful(url, self.include_arabic) and url not in self.seen and url not in self.queued:
            self.pending.append(url)
            self.queued.add(url)

    def browser_html(self, url):
        if self.browser_instance is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise RuntimeError("Install requirements-collector.txt and run: python3 -m playwright install chromium") from None
            self.pw = sync_playwright().start()
            self.browser_instance = self.pw.chromium.launch(headless=True)
            self.browser_context = self.browser_instance.new_context(user_agent=AGENT)
            def route_request(route):
                request = route.request
                if request.resource_type in ("image", "media", "font"):
                    return route.abort()
                # Do not let browser rendering make state-changing requests.
                if request.method not in ("GET", "HEAD"):
                    return route.abort()
                host = (urlsplit(request.url).hostname or "").removeprefix("www.")
                if not (host in HOSTS or host.endswith(".wasalt.sa") or host.endswith(".darglobal.co.uk")):
                    return route.abort()
                return route.continue_()
            self.browser_context.route("**/*", route_request)
        page = self.browser_context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            if not allowed(page.url):
                raise ValueError("Browser navigation left allowed sources")
            # Materialize lazily inserted cards without clicking transactions.
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(700)
            return page.url, page.content()
        finally:
            page.close()

    def checkpoint(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix(".tmp")
        temp.write_text(json.dumps({"seen": sorted(self.seen), "pending": list(self.pending), "updated_at": now()}, indent=2))
        temp.replace(self.state_path)

    def run(self, extra_urls=None):
        if self.state_path.exists() and not self.refresh:
            previous = json.loads(self.state_path.read_text())
            self.seen = set(previous.get("seen", []))
            for url in previous.get("pending", []):
                self.enqueue(url)
        sources = SEEDS if self.source == "all" else {self.source: SEEDS[self.source]}
        for urls in sources.values():
            for url in urls:
                self.enqueue(url)
        # Previously inspected public detail pages seed a real HTTP refresh too.
        for file in RAW.glob("*.csv"):
            for row in read_csv(file):
                url = row.get("url", "")
                if url and (self.source == "all" or self.source in url):
                    self.enqueue(url)
        for url in extra_urls or []:
            self.enqueue(url)
        for host in ("https://darglobal.co.uk", "https://wasalt.sa", "https://auction.wasalt.sa", "https://blog.wasalt.sa"):
            if self.source == "all" or self.source in host:
                self.enqueue(host + "/sitemap.xml")
        processed, failures, failure_streak = 0, 0, 0
        try:
            while self.pending and (self.max_pages == 0 or processed < self.max_pages):
                url = self.pending.popleft()
                self.queued.discard(url)
                row = {"url": url, "title": "", "content": "", "fetched_at": now(), "method": "http_html", "ref": "", "status": "ok"}
                try:
                    if not self.permitted(url):
                        row.update(status="robots_disallowed_or_unavailable", content="Not fetched: crawl policy disallows this URL or could not be established.")
                        append_csv(self.output, row)
                        self.seen.add(url)
                        failures += 1
                        processed += 1
                        failure_streak += 1
                        if failure_streak >= 8:
                            LOG.error("Stopping after 8 consecutive policy/network failures. Re-run with --refresh after resolving access.")
                            break
                        continue
                    final, content_type, body = self.request(url)
                    row["url"] = canonical_url(final)
                    if "xml" in content_type or urlsplit(url).path.endswith(".xml"):
                        xml = ET.fromstring(body)
                        locs = [e.text for e in xml.iter() if e.tag.rsplit("}", 1)[-1] == "loc" and e.text]
                        for loc in locs:
                            self.enqueue(loc)
                        row.update(title="Sitemap", content=body.decode("utf-8", "replace"), method="sitemap_xml")
                    elif "pdf" in content_type or urlsplit(url).path.endswith(".pdf"):
                        from io import BytesIO
                        try:
                            from pypdf import PdfReader
                        except ImportError:
                            row.update(status="pdf_parser_missing", content="Install pypdf to extract publicly linked PDF documents.", method="pdf_text")
                        else:
                            pdf = PdfReader(BytesIO(body))
                            row.update(title=Path(urlsplit(url).path).name, method="pdf_text", content="\n\n".join(f"PDF PAGE {i+1}\n"+(p.extract_text() or "") for i, p in enumerate(pdf.pages)))
                    else:
                        html = body.decode("utf-8", "replace")
                        parser = parse_html(html, final)
                        if self.browser and (len(parser.text) < 900 or "/search" in url or "product-category" in url):
                            final, html = self.browser_html(final)
                            parser = parse_html(html, final)
                            row["method"] = "browser_html"
                        row.update(content=html, title=" ".join(parser.title_parts), url=canonical_url(final))
                        # CSV checkpoint precedes discovery and every downstream transform.
                        append_csv(self.output, row)
                        for href, _ in parser.links:
                            self.enqueue(href)
                        # SEO listings expose page counts even when pagination links are buttons.
                        # Probe only page 2 initially. Each subsequent page must add new content.
                        if "properties-for-" in url and "page=" not in url and re.search(r"\d[\d,]*\s+results", parser.text, re.I):
                            p = urlsplit(final)
                            q = dict(parse_qsl(p.query)); q["page"] = "2"
                            self.enqueue(urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), "")))
                        elif "page=" in url and "properties-for-" in url:
                            p = urlsplit(url); q = dict(parse_qsl(p.query))
                            current = int(q.get("page", "1"))
                            # Do not follow duplicate pages indefinitely.
                            fingerprint = hash(tuple(sorted(h for h, _ in parser.links if "/property/" in h or "/dailyrental/" in h)))
                            key = p.netloc+p.path
                            previous = getattr(self, "page_fingerprints", {})
                            if previous.get(key) != fingerprint and any("/property/" in h or "/dailyrental/" in h for h, _ in parser.links):
                                q["page"] = str(current+1)
                                self.enqueue(urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), "")))
                            previous[key] = fingerprint
                            self.page_fingerprints = previous
                        self.seen.update((url, canonical_url(final)))
                        processed += 1
                        failure_streak = 0
                        LOG.info("[%s] %s (%s links)", processed, url, len(parser.links))
                        self.checkpoint()
                        continue
                    append_csv(self.output, row)
                    self.seen.add(url)
                    failure_streak = 0
                except (OSError, ValueError, ET.ParseError, RuntimeError) as exc:
                    row.update(status="error", content=f"{type(exc).__name__}: {exc}")
                    append_csv(self.output, row)
                    self.seen.add(url)
                    failures += 1
                    failure_streak += 1
                    LOG.warning("%s: %s", url, exc)
                processed += 1
                self.checkpoint()
                if failure_streak >= 8:
                    LOG.error("Stopping after 8 consecutive failures; progress is saved.")
                    break
        finally:
            self.checkpoint()
            if self.browser_instance:
                self.browser_instance.close()
                self.pw.stop()
        return {"processed": processed, "failures": failures, "remaining": len(self.pending), "csv": str(self.output)}
