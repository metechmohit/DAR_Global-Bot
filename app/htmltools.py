"""HTML extraction with structural line breaks, links and embedded public JSON."""
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin


class PageParser(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links, self.images, self.json_data = base, [], [], [], []
        self.hidden = 0
        self.script = None
        self.script_parts = []
        self.title_parts = []
        self.in_title = False
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "noscript", "svg"):
            self.hidden += 1
        if tag == "script":
            self.script = a
            self.script_parts = []
        if tag == "title":
            self.in_title = True
        if tag in ("p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section", "dt", "dd"):
            self.parts.append("\n")
        if tag == "a" and a.get("href"):
            self.anchor = [urljoin(self.base, a["href"]), []]
        if tag == "img":
            src = a.get("src") or a.get("data-src", "")
            if src and not src.startswith("data:"):
                self.images.append(urljoin(self.base, src))

    def handle_endtag(self, tag):
        if tag in ("style", "noscript", "svg"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "script":
            if self.script is not None and ("json" in self.script.get("type", "") or self.script.get("id") == "__NEXT_DATA__"):
                try:
                    self.json_data.append(json.loads("".join(self.script_parts)))
                except ValueError:
                    pass
            self.script = None
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.anchor:
            self.links.append((self.anchor[0], " ".join(self.anchor[1])))
            self.anchor = None
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "dt", "dd"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self.script is not None:
            self.script_parts.append(data)
        elif not self.hidden:
            self.parts.append(data)
            if self.in_title:
                self.title_parts.append(data)
            if self.anchor:
                self.anchor[1].append(data.strip())

    @property
    def text(self):
        return "\n".join(re.sub(r"\s+", " ", x).strip() for x in "".join(self.parts).splitlines() if x.strip())


def parse_html(html, url):
    parser = PageParser(url)
    parser.feed(html)
    return parser


def clean_text(content, method=""):
    if method in ("http_html", "browser_html"):
        return parse_html(content, "").text
    if method in ("pdf_text", "plain_text"):
        return content.strip()
    # Research snapshots are kept verbatim in CSV; remove tool decoration for indexing.
    lines = []
    for line in content.splitlines():
        if re.match(r"L\d+:", line):
            lines.append(re.sub(r"^L\d+:\s?", "", line))
    if not lines:
        lines = content.splitlines()[2:]
    text = "\n".join(lines)
    text = re.sub(r"【\d+†Image:[^】]*】", "", text)
    text = re.sub(r"【\d+†([^†】]+)(?:†[^】]*)?】", r"\1", text)
    text = re.sub(r"\[Button:[^\]]*\]|\[Input[^\]]*\]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return unescape(text.strip())
