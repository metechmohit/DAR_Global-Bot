"""Validated structured search and multilingual lexical retrieval over real evidence."""
import json
import re
import sqlite3
from .config import DB
from .common import normalize, number
from .extract import LOCATIONS, TYPES

FILTER_KEYS = {"source", "city", "country", "district", "purpose", "property_type", "price_min", "price_max", "bedrooms", "bedrooms_min", "bathrooms_min", "area_min", "area_max", "currency", "price_period", "furnishing", "kind", "sort", "amenities"}
STOP = set("a an the is are of in on at to and or i me my with for what which how can do does show find tell about please properties property available want need under below above than less more budget bedrooms bedroom price sale rent projects project compare between it this those them make also only best have has be from all".split())
STOP |= {"في", "من", "على", "عن", "ما", "هي", "هو", "مع", "اريد", "ابحث", "اقل", "اكثر", "عرض", "كم"}
COUNTRIES = {"Oman": ["oman", "عمان"], "UAE": ["uae", "united arab emirates", "الامارات"], "Saudi Arabia": ["saudi", "ksa", "السعودية"], "Qatar": ["qatar", "قطر"], "Spain": ["spain", "اسبانيا"], "UK": ["uk", "united kingdom", "بريطانيا"]}


def connect():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    return con


def validate_filters(raw):
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key in FILTER_KEYS:
        value = raw.get(key)
        if value is None or value == "":
            continue
        if key in {"price_min", "price_max", "bedrooms", "bedrooms_min", "bathrooms_min", "area_min", "area_max"}:
            try:
                value = float(value)
                if not 0 <= value <= 1e14 or value != value:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
        elif not isinstance(value, str) or len(value) > 100:
            continue
        result[key] = value
    allowed = {"source": {"wasalt", "darglobal"}, "purpose": {"sale", "rent", "daily_rent"}, "kind": {"listing", "project", "community", "daily_rental", "auction"}, "sort": {"relevance", "price_asc", "price_desc", "area_desc"}, "price_period": {"total", "yearly", "monthly", "weekly", "night"}, "furnishing": {"furnished", "semi-furnished", "unfurnished"}}
    return {k: v for k, v in result.items() if k not in allowed or v in allowed[k]}


def contains(text, alias):
    return bool(re.search(r"(?<!\w)" + re.escape(normalize(alias)) + r"(?!\w)", text))


def parse_question(question, previous=None):
    q = normalize(question)
    reset = any(contains(q, t) for t in ("reset", "start over", "clear filters", "new search", "ابدأ من جديد"))
    followup = bool(re.search(r"\b(instead|also|make (?:it|them)|those|these|same|increase|decrease|cheaper|now|only|change|what about)\b", q))
    filters = validate_filters(previous) if followup and not reset else {}
    if reset:
        return {"intent": "search", "filters": {}, "clarification": "", "reset": True}
    for source, aliases in {"darglobal": ["darglobal", "dar global", "دار جلوبال"], "wasalt": ["wasalt", "وصلت"]}.items():
        if any(contains(q, a) for a in aliases):
            filters["source"] = source
    for city, aliases in LOCATIONS.items():
        if any(contains(q, a) for a in aliases):
            filters["city"] = city
            break
    for country, aliases in COUNTRIES.items():
        if any(contains(q, a) for a in aliases):
            filters["country"] = country
            break
    for typ, aliases in TYPES.items():
        if any(contains(q, a) for a in aliases):
            filters["property_type"] = typ
            break
    if any(contains(q, a) for a in ("daily", "nightly", "per night", "short term", "يومي", "ليلة")):
        filters.update(purpose="daily_rent", price_period="night")
    elif any(contains(q, a) for a in ("rent", "rental", "rentals", "monthly", "yearly", "ايجار", "للايجار")):
        filters["purpose"] = "rent"
    elif any(contains(q, a) for a in ("buy", "sale", "purchase", "للبيع", "شراء")):
        filters.update(purpose="sale", price_period="total")
    for period, aliases in {"monthly": ["monthly", "per month", "/month", "شهري"], "yearly": ["yearly", "annually", "annual", "per year", "سنوي"], "weekly": ["weekly", "per week", "اسبوعي"]}.items():
        if any(a in q for a in aliases):
            filters["price_period"] = period
    for currency in ("SAR", "AED", "USD", "GBP", "EUR", "OMR", "QAR"):
        if contains(q, currency):
            filters["currency"] = currency
    if "$" in q:
        filters["currency"] = "USD"
    if "ريال" in q:
        filters["currency"] = "SAR"
    if "unfurnished" in q or "غير مفروش" in q:
        filters["furnishing"] = "unfurnished"
    elif "semi-furnished" in q:
        filters["furnishing"] = "semi-furnished"
    elif "furnished" in q or "مفروش" in q:
        filters["furnishing"] = "furnished"
    requested = []
    for amenity, aliases in {"pool": ["pool", "swimming pool", "مسبح"], "parking": ["parking", "موقف"], "gym": ["gym", "fitness centre", "fitness center"], "golf": ["golf", "جولف"], "beach": ["beach", "شاطئ"], "jacuzzi": ["jacuzzi", "جاكوزي"]}.items():
        if any(contains(q, a) for a in aliases):
            requested.append(amenity)
    if requested:
        filters["amenities"] = "|".join(requested)
    bed = re.search(r"(\d+)\s*(\+|or more|at least)?\s*[- ]?(?:bed(?:room)?s?|br|bhk|غرف)", q)
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    if not bed:
        for word, val in words.items():
            if re.search(r"\b" + word + r"[- ]bed", q):
                filters["bedrooms"] = val
    else:
        filters.pop("bedrooms", None)
        filters.pop("bedrooms_min", None)
        filters["bedrooms_min" if bed[2] or "at least" in q[:bed.start()+1] else "bedrooms"] = int(bed[1])
    if "studio" in q:
        # Do not assume every site encodes studios as zero bedrooms.
        filters["property_type"] = "apartment"
    amount = r"(?:sar|aed|usd|gbp|eur|omr|qar|[$])?\s*([\d,]+(?:\.\d+)?)\s*((?:million|thousand|lakh|crore|[kmb])(?![a-z])|مليون|الف)?"
    def money(m):
        return float(m[1].replace(",", "")) * {"million": 1e6, "thousand": 1e3, "lakh": 1e5, "crore": 1e7, "k": 1e3, "m": 1e6, "b": 1e9, "مليون": 1e6, "الف": 1e3}.get(m[2] or "", 1)
    for key, prefix in [("price_max", r"(?:under|below|less than|up to|max(?:imum)?(?: budget)?|budget(?: of)?|اقل من|حتى)\s*"), ("price_min", r"(?:above|over|more than|min(?:imum)?(?: budget)?|اكثر من)\s*")]:
        m = re.search(prefix + amount, q)
        if m:
            # Area and bedroom phrases are not budgets.
            suffix = q[m.end():m.end()+14].strip()
            if not re.match(r"(?:sq|sqm|m2|bed|غرف|متر)", suffix):
                filters[key] = money(m)
    area = re.search(r"(?:at least|minimum|over|above)\s*(\d[\d,.]*)\s*(?:sqm|sq m|m²|متر)", q)
    if area:
        filters["area_min"] = number(area[1])
    if "cheapest" in q or "lowest price" in q or "cheaper" in q:
        filters["sort"] = "price_asc"
    if "most expensive" in q:
        filters["sort"] = "price_desc"
    if "largest" in q:
        filters["sort"] = "area_desc"
    if "project" in q or "مشروع" in q or "مشاريع" in q:
        filters["kind"] = "project"
    if "auction" in q or "مزاد" in q:
        filters["kind"] = "auction"
    is_search = bool(re.search(r"\b(show|find|list|search|looking|recommend|options|cheapest|apartments|villas|projects)\b|ابحث|اعرض|اريد|شقق|فلل", q))
    intent = "compare" if "compare" in q or "قارن" in q else ("search" if is_search or followup else "knowledge")
    if re.search(r"\b(what is|tell me about|how|why|when|where|does|can i)\b", q) and not re.search(r"\b(show|find|list)\b", q):
        intent = "knowledge"
    clarification = ""
    if any(k in filters for k in ("price_min", "price_max")):
        if filters.get("purpose") == "rent" and not filters.get("price_period"):
            clarification = "Is that rental budget per month or per year? Please include the period, for example ‘under SAR 5,000 monthly’."
        if not filters.get("currency"):
            if filters.get("source") == "wasalt" or filters.get("city") in ("Riyadh", "Jeddah", "Dammam", "Khobar", "Makkah", "Madinah") or filters.get("country") == "Saudi Arabia":
                filters["currency"] = "SAR"
            else:
                clarification = clarification or "Which currency is your budget in? Please include SAR, AED, USD, GBP, EUR, OMR or QAR."
        if filters.get("purpose") not in ("rent", "daily_rent"):
            filters.setdefault("price_period", "total")
    if filters.get("sort") in ("price_asc", "price_desc"):
        if not filters.get("currency"):
            clarification = clarification or "Which currency should I use to compare prices? Please include the purpose and price period too."
        if not filters.get("price_period"):
            clarification = clarification or "Should I compare sale totals, monthly rent, yearly rent, or nightly rates?"
    return {"intent": intent, "filters": validate_filters(filters), "clarification": clarification, "reset": False}


def search_records(filters=None, limit=12, offset=0):
    f = validate_filters(filters or {})
    numeric_price = any(k in f for k in ("price_min", "price_max")) or f.get("sort") in ("price_asc", "price_desc")
    if numeric_price:
        if not f.get("currency"):
            raise ValueError("A currency is required for price filtering or sorting")
        if f.get("purpose") == "rent" and f.get("price_period") not in ("monthly", "yearly", "weekly"):
            raise ValueError("A rental period is required for a rent budget")
        f.setdefault("price_period", "night" if f.get("purpose") == "daily_rent" else "total")
    clauses = ["kind IN ('listing','project','community','daily_rental','auction')"]
    args = []
    for key in ("source", "city", "purpose", "currency", "price_period", "furnishing", "kind"):
        if key in f:
            clauses.append(f"lower({key})=lower(?)")
            args.append(f[key])
    for key in ("country", "district"):
        if key in f:
            clauses.append("lower(json_extract(payload, ?))=lower(?)")
            args.extend(["$."+key, f[key]])
    if f.get("property_type"):
        clauses.append("instr('|'||property_type||'|', '|'||?||'|') > 0")
        args.append(f["property_type"])
    for amenity in str(f.get("amenities", "")).split("|"):
        if amenity:
            clauses.append("instr(lower(json_extract(payload,'$.amenities')), lower(?))>0")
            args.append(amenity)
    for key, column, op in [("price_min", "price", ">="), ("price_max", "price", "<="), ("bedrooms", "bedrooms", "="), ("bedrooms_min", "bedrooms", ">="), ("bathrooms_min", "bathrooms", ">="), ("area_min", "area_sqm", ">="), ("area_max", "area_sqm", "<=")]:
        if key in f:
            clauses.append(f"{column} {op} ?")
            args.append(f[key])
    # Budget searches must not compare nightly/monthly/total costs together.
    if any(k in f for k in ("price_min", "price_max")) and not f.get("price_period"):
        clauses.append("price_period='total'")
    sort = {"price_asc": "price IS NULL, price ASC", "price_desc": "price IS NULL, price DESC", "area_desc": "area_sqm IS NULL, area_sqm DESC"}.get(f.get("sort"), "source, title")
    if f.get("sort") in ("price_asc", "price_desc"):
        clauses.append("price IS NOT NULL")
    where = " AND ".join(clauses)
    with connect() as con:
        total = con.execute("SELECT count(*) FROM records WHERE " + where, args).fetchone()[0]
        rows = con.execute("SELECT payload FROM records WHERE " + where + " ORDER BY " + sort + " LIMIT ? OFFSET ?", args + [max(1, min(int(limit), 50)), max(0, int(offset))]).fetchall()
    return {"total": total, "records": [json.loads(r[0]) for r in rows], "filters": f}


def tokens(query):
    return [t for t in re.findall(r"[\w]+", normalize(query)) if len(t) > 1 and t not in STOP][:40]


def retrieve(query, source=None, limit=8, record_ids=None):
    expanded = query
    for city, aliases in LOCATIONS.items():
        if any(contains(normalize(query), a) for a in aliases):
            expanded += " " + city
    for arabic, english in {"مشاريع": "projects developments", "مرافق": "amenities", "مسبح": "pool swimming", "جولف": "golf", "ايدا": "AIDA", "استيرا": "Astera", "اطلالة": "view", "شقق": "apartments", "فلل": "villas", "موعد": "completion handover", "تسليم": "handover completion"}.items():
        if arabic in normalize(query):
            expanded += " " + english
    terms = tokens(expanded)
    if not terms and not record_ids:
        return []
    with connect() as con:
        if record_ids:
            ids = record_ids[:12]
            rows = con.execute("SELECT *,0 AS score FROM chunks WHERE record_id IN (" + ",".join("?" for _ in ids) + ") LIMIT 180", ids).fetchall()
        else:
            expr = " OR ".join('"'+t.replace('"', '')+'"' for t in terms)
            sql = "SELECT c.*,bm25(chunks_fts,0,4,1) AS score FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.id WHERE chunks_fts MATCH ?"
            args = [expr]
            if source in ("darglobal", "wasalt"):
                sql += " AND c.source=?"
                args.append(source)
            rows = con.execute(sql + " ORDER BY score LIMIT 100", args).fetchall()
        ranked = []
        for row in rows:
            title, body = normalize(row["title"]), normalize(row["text"])
            matched = set(t for t in terms if t in title or t in body)
            # Retrieval score is used internally, not presented as factual confidence.
            score = sum(5 if t in title else 1 for t in matched) + min(3, -float(row["score"]))
            ranked.append((score, dict(row)))
    ranked.sort(key=lambda x: x[0], reverse=True)
    results, per_record = [], {}
    for score, row in ranked:
        if score <= 0 and not record_ids:
            continue
        rid = row["record_id"]
        if per_record.get(rid, 0) >= 2:
            continue
        per_record[rid] = per_record.get(rid, 0)+1
        row["retrieval_score"] = round(score, 3)
        results.append(row)
        if len(results) == limit:
            break
    return results


def get_records(ids):
    if not ids:
        return []
    with connect() as con:
        rows = con.execute("SELECT payload FROM records WHERE id IN (" + ",".join("?" for _ in ids[:20]) + ")", ids[:20]).fetchall()
    by_id = {r["id"]: r for row in rows if (r := json.loads(row[0]))}
    return [by_id[i] for i in ids if i in by_id]
