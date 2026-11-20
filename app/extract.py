"""Source-specific extraction. Missing fields remain unknown; raw evidence is retained."""
import json
import re
from urllib.parse import urlsplit, unquote
from .common import RECORD_FIELDS, digest, normalize, number
from .htmltools import clean_text, parse_html

LOCATIONS = {
    "Riyadh": ["riyadh", "الرياض"], "Jeddah": ["jeddah", "جدة", "جده"],
    "Dammam": ["dammam", "aldammam", "الدمام"], "Khobar": ["khobar", "الخبر"],
    "Makkah": ["makkah", "mecca", "مكة", "مكه"], "Madinah": ["madinah", "medina", "المدينة"],
    "Dubai": ["dubai", "دبي"], "Muscat": ["muscat", "مسقط"],
    "Doha": ["doha", "الدوحة"], "Simaisma": ["simaisma", "سميسمة"],
    "London": ["london", "لندن"], "Benahavis": ["benahav", "tierra viva"],
    "Cortesin": ["cortesin", "marea"], "Ras Al Khaimah": ["ras al khaimah", "al marjan", "rak", "astera"],
    "Taif": ["taif", "الطائف"], "Abha": ["abha", "ابها"],
}
TYPES = {"apartment": ["apartment", "apartments", "شقة", "شقق", "شقه"],
         "villa": ["villa", "villas", "فيلا", "فلل"], "land": ["land", "plot", "ارض", "أرض"],
         "floor": ["floor", "دور", "ادوار"], "building": ["building", "عمارة", "عماره"],
         "chalet": ["chalet", "شاليه"], "penthouse": ["penthouse", "بنتهاوس"],
         "townhouse": ["townhouse", "تاون هاوس"], "office": ["office", "مكتب"],
         "warehouse": ["warehouse", "مستودع"], "palace": ["palace", "قصر"]}
AMENITIES = ["swimming pool", "pool", "gym", "fitness center", "fitness centre", "parking", "balcony",
             "sea view", "golf", "garden", "elevator", "security", "mosque", "school", "park",
             "beach", "jacuzzi", "cinema", "مسبح", "موقف", "مصعد", "حديقة"]


def detect_city(text):
    n = normalize(text)
    hits = [(n.find(normalize(v)), city) for city, aliases in LOCATIONS.items() for v in aliases
            if re.search(r"(?<!\w)" + re.escape(normalize(v)) + r"(?!\w)", n)]
    return min(hits)[1] if hits else ""


def classify(url):
    path = unquote(urlsplit(url).path).lower()
    if path.endswith(".pdf"):
        return "article"
    if "auction.wasalt" in url:
        return "auction" if re.search(r"/(auction-group|asset|property)/", path) else "index"
    if "wasalt" in url:
        if "/dailyrental/" in path:
            return "daily_rental"
        if "/property/" in path:
            return "listing"
        if "/project/" in path:
            return "project"
        if "blog." in url or "/s/" in path or path.endswith(("/corporate", "/wb-daily-rentals")):
            return "article"
        return "index"
    if "/product-category/" in path:
        return "inventory_page"
    if path in ("/", "/projects") or path.startswith("/projects/"):
        return "index"
    if path.startswith(("/press/", "/careers/")) or path in ("/about", "/faq", "/investor", "/press", "/get-in-touch", "/become-an-agent", "/terms-conditions"):
        return "article"
    return "community" if path.endswith("/aida") else "project"


def match_value(pattern, text, group=1):
    m = re.search(pattern, text, re.I | re.M)
    return m[group].strip() if m else ""


def extract(page):
    if page.get("method") == "sitemap_xml":
        return None
    if page.get("status") not in ("ok", "200", "success"):
        return None
    text = clean_text(page["content"], page.get("method", ""))
    minimum = 40 if page.get("method") == "web_index_summary" else 100
    if len(text) < minimum or "Failed to fetch" in text or "not accessible via this tool" in text:
        return None
    url = page["url"]
    kind = classify(url)
    record = dict.fromkeys(RECORD_FIELDS, "")
    record.update(id=digest(url), source="wasalt" if "wasalt" in url else "darglobal", kind=kind,
                  title=page.get("title", "").strip(), url=url, description=text,
                  fetched_at=page.get("fetched_at", ""), collection_method=page.get("method", ""),
                  content_hash=digest(text))
    if record["source"] == "wasalt" and kind in ("listing", "project", "daily_rental"):
        # Detail headings often start at "Property Description". The document
        # title is a better identity than the first arbitrary section heading.
        if kind == "daily_rental":
            title = match_value(r"^##\s+(.+)$", text)
            if title and title not in ("Unit Description", "Arrival guide"):
                record["title"] = title
        record["country"] = "Saudi Arabia"
        record["city"] = detect_city(text[:1800]) or detect_city(unquote(url))
        record["purpose"] = "daily_rent" if kind == "daily_rental" else ("rent" if "/rent/" in url else "sale")
        record["currency"] = "SAR"
        record["bedrooms"] = number(match_value(r"(?:^|\n)\s*(?:[-*]\s*)?(\d+)\s*\n+\s*(?:bedrooms|غرف نوم)", text)) or ""
        record["bathrooms"] = number(match_value(r"(?:^|\n)\s*(?:[-*]\s*)?(\d+)\s*\n+\s*(?:bathrooms|دورات مياه)", text)) or ""
        if not record["bedrooms"]:
            record["bedrooms"] = number(match_value(r"\b(?:with\s+)?(\d+)\s*[- ]?Bedrooms?\b", record["title"])) or ""
        record["reference"] = match_value(r"Ref\s*no\.?\s*(\d+)", text)
        record["url_identifier"] = match_value(r"-(\d+)(?:\?|$)", url)
        record["source_updated_raw"] = match_value(r"Last updated:?\s*([^\n|]+)", text)
        location = match_value(r"^#{3,6}\s*([^\n]+?)(?:Map view)?$", text[:1600])
        if not location:
            location = match_value(r"^([^\n]*,[^\n]*)Map view", text[:1400])
        if location and record["city"]:
            district = location.replace("Map view", "").split(",")[0].strip()
            if normalize(district) != normalize(record["city"]):
                record["district"] = district
        price = ""
        for candidate in re.findall(r"^\s*(?:###\s*)?((?:\d[\d,]*(?:\.\d+)?\s*[KMB]?)(?:\s*(?:/|per\s+)(?:night|month|year)[^\n]*)?)\s*$", text[:5000], re.I | re.M):
            amount = number(candidate)
            if amount and (amount >= 100 or "/night" in candidate.lower()):
                price = candidate.strip()
                break
        if page.get("method") == "web_index_summary":
            price = match_value(r"^([\d,.]+(?:\s*[KMB](?![a-z]))?)", text)
            range_max = match_value(r"^[\d,.]+\s*[KMB]?\s*[-–]\s*([\d,.]+\s*[KMB]?)", text)
            if range_max:
                record["price_max"] = number(range_max) or ""
                record["price_kind"] = "range"
        if not price:
            price = match_value(r"starts from\s*([\d,.]+\s*[KMB]?)", text)
            if price:
                record["price_kind"] = "starting_from"
        record["price_raw"] = price
        record["price"] = number(price) or ""
        record["price_period"] = "night" if kind == "daily_rental" else "total"
        if record["purpose"] == "rent":
            record["price_period"] = match_value(r"\b(yearly|monthly|weekly|daily)\b", text[:5000]).lower() or "unknown"
        record["price_kind"] = record["price_kind"] or ("exact" if price else "unknown")
        record["area_sqm"] = number(match_value(r"([\d,.]+)\s*(?:SQM|Sqm|m²|sqm|م²)", text[:2000])) or ""
        record["area_kind"] = "built_up" if "built-up area" in text[:2000].lower() else "unspecified"
        furnishing = match_value(r"\b(Semi-Furnished|Unfurnished|Furnished)\b", text[:2500])
        record["furnishing"] = furnishing.lower()
        record["status"] = match_value(r"Project Status\s+([^\n]+)", text) or "advertised_unconfirmed"
    elif record["source"] == "darglobal" and kind in ("project", "community"):
        record["city"] = detect_city(record["title"] + " " + text[:2000] + " " + url)
        record["country"] = {"Dubai": "UAE", "Ras Al Khaimah": "UAE", "Muscat": "Oman", "Doha": "Qatar", "Simaisma": "Qatar", "London": "UK", "Benahavis": "Spain", "Cortesin": "Spain", "Riyadh": "Saudi Arabia", "Jeddah": "Saudi Arabia"}.get(record["city"], "")
        record["status"] = match_value(r"(?:^|\n)\s*[-*]?\s*STATUS\s+([^\n]+)", text)
        record["price_kind"] = "on_request"
        # A project may offer multiple bedroom types. Keep those in source text,
        # rather than turning a range into one exact bedroom count.
        record["purpose"] = "sale"
        record["parent_url"] = "https://darglobal.co.uk/landing-page/aida" if "aida" in text[:1600].lower() and kind != "community" else ""
    ntitle = normalize(record["title"])
    types = [t for t, aliases in TYPES.items() if any(re.search(r"(?<!\w)" + re.escape(normalize(a)) + r"(?!\w)", ntitle) for a in aliases)]
    record["property_type"] = "|".join(types)
    # Filterable amenities come from a dedicated section, not incidental marketing
    # mentions, nearby hotels, suggestions or a negative phrase in a description.
    amenity_section = match_value(r"^\s*#{0,6}\s*(?:Amenities(?: of [^\n]+)?|What this place offers)\s*\n([\s\S]+?)(?=\n\s*#{1,3}\s|\n(?:Why invest|Location|Frequently Asked|Cancellation Policy|About Project|Register Your Interest)|\Z)", text)
    record["amenities"] = "|".join(a for a in AMENITIES if re.search(r"(?<!\w)" + re.escape(normalize(a)) + r"(?!\w)", normalize(amenity_section)))
    flags = []
    if page.get("method") in ("web_retrieval", "web_index_summary"):
        flags.append("retrieved_snapshot_not_live_inventory")
        if page.get("method") == "web_index_summary":
            flags.append("summary_only")
        total = number(match_value(r"Total lines:\s*(\d+)", page["content"]))
        observed = len(re.findall(r"^L\d+:", page["content"], re.M))
        if total and observed < total * .8:
            flags.append("partial_page")
    if record["price"] and float(record["price"]) > 200_000_000:
        flags.append("price_requires_verification")
    elif record["price"] and ((record["purpose"] == "rent" and float(record["price"]) > 10_000_000) or (record["purpose"] == "daily_rent" and float(record["price"]) > 10_000)):
        flags.append("price_requires_verification")
    if record["purpose"] == "rent" and record["price_period"] == "unknown":
        flags.append("unknown_rental_period")
    record["quality_flags"] = "|".join(flags)
    if page.get("method") in ("http_html", "browser_html"):
        parser = parse_html(page["content"], url)
        record["image_url"] = next((i for i in parser.images if not any(s in i.lower() for s in ("logo", "icon", "pixel"))), "")
        # JSON-LD supplements explicit HTML only; never execute embedded scripts.
        for obj in parser.json_data:
            candidates = obj if isinstance(obj, list) else [obj]
            for item in candidates:
                if isinstance(item, dict) and isinstance(item.get("offers"), dict):
                    offer = item["offers"]
                    if not record["price"] and offer.get("price"):
                        record.update(price=number(offer["price"]) or "", price_raw=str(offer["price"]), currency=offer.get("priceCurrency", record["currency"]), price_kind="exact")
    return record
