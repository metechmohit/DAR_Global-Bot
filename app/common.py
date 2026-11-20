import csv
import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

RAW_FIELDS = ["url", "title", "content", "fetched_at", "method", "ref", "status"]
RECORD_FIELDS = [
    "id", "source", "kind", "title", "url", "country", "city", "district",
    "purpose", "property_type", "price", "price_max", "currency", "price_period",
    "price_kind", "price_raw", "bedrooms", "bathrooms", "area_sqm", "area_kind",
    "furnishing", "status", "reference", "url_identifier", "amenities",
    "description", "image_url", "fetched_at", "source_updated_raw", "collection_method",
    "quality_flags", "parent_url", "content_hash",
]
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or "")).translate(ARABIC_DIGITS).lower()
    text = re.sub(r"[\u064b-\u065f\u0670ـ]", "", text)
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))


def canonical_url(url):
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((p.scheme, p.netloc.lower().removeprefix("www."), p.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def read_csv(path):
    if not path.exists():
        return []
    csv.field_size_limit(50_000_000)
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def append_csv(path, row, fields=RAW_FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig" if not exists else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow(row)
        f.flush()


def number(value):
    text = str(value or "").translate(ARABIC_DIGITS).replace("٬", ",").replace("٫", ".")
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*([KMB](?![a-zA-Z]))?", text, re.I)
    if not m:
        return None
    return float(m[1].replace(",", "")) * {"k": 1e3, "m": 1e6, "b": 1e9}.get((m[2] or "").lower(), 1)
