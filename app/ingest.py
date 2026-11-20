"""CSV-first pipeline: raw CSV -> normalized CSV -> reproducible SQLite index."""
import json
import re
import sqlite3
from collections import Counter
from .config import RAW, PROCESSED, DB
from .common import RECORD_FIELDS, canonical_url, digest, normalize, now, read_csv, write_csv
from .extract import extract
from .htmltools import clean_text


def chunks(text, size=1700, overlap=180):
    # Preserve paragraph/FAQ boundaries where possible, cap unusually large blocks.
    lines = text.splitlines()
    buffer = ""
    for line in lines:
        if len(buffer) + len(line) > size and buffer:
            yield buffer.strip()
            buffer = buffer[-overlap:] + "\n"
        while len(line) > size:
            yield (buffer + line[:size]).strip()
            buffer, line = "", line[size-overlap:]
        buffer += line + "\n"
    if buffer.strip():
        yield buffer.strip()


def build():
    pages = {}
    attempts = []
    for path in sorted(RAW.glob("*.csv")):
        for page in read_csv(path):
            if not page.get("url") or not page.get("content"):
                continue
            attempts.append(page)
            key = canonical_url(page["url"])
            prev = pages.get(key)
            # Prefer direct successful collection, then the richest research snapshot.
            def rank(p):
                minimum = 40 if p.get("method") == "web_index_summary" else 100
                usable = p.get("status") in ("ok", "200", "success") and len(clean_text(p.get("content", ""), p.get("method", ""))) >= minimum
                quality = {"http_html": 3, "browser_html": 3, "pdf_text": 3, "web_retrieval": 2, "web_index_summary": 1}.get(p.get("method"), 0)
                return (usable, quality, len(p.get("content", "")))
            if prev is None or rank(page) > rank(prev):
                page["url"] = key
                pages[key] = page
    records = [r for p in pages.values() if (r := extract(p))]
    records.sort(key=lambda r: (r["source"], r["kind"], r["title"]))
    # These are the canonical collected exports; the search database is derived.
    write_csv(PROCESSED / "records.csv", records, RECORD_FIELDS)
    for source in ("darglobal", "wasalt"):
        write_csv(PROCESSED / f"{source}.csv", [r for r in records if r["source"] == source], RECORD_FIELDS)
    failures = [{"url": p["url"], "status": p.get("status", ""), "fetched_at": p.get("fetched_at", ""), "method": p.get("method", "")} for p in attempts if p.get("status") not in ("ok", "200", "success")]
    write_csv(PROCESSED / "failures.csv", failures, ["url", "status", "fetched_at", "method"])
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    with con:
        con.executescript("""
        DROP TABLE IF EXISTS records;
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS chunks_fts;
        CREATE TABLE records(id TEXT PRIMARY KEY, source TEXT, kind TEXT, title TEXT, city TEXT,
          purpose TEXT, property_type TEXT, price REAL, bedrooms REAL, bathrooms REAL, area_sqm REAL,
          currency TEXT, price_period TEXT, furnishing TEXT, payload TEXT);
        CREATE INDEX record_filters ON records(source, city, purpose, property_type, price);
        CREATE TABLE chunks(id TEXT PRIMARY KEY, record_id TEXT, title TEXT, text TEXT, url TEXT, source TEXT);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(id UNINDEXED, title, text, tokenize='unicode61 remove_diacritics 2');
        """)
        count = 0
        for r in records:
            con.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                r["id"], r["source"], r["kind"], r["title"], r["city"], r["purpose"], r["property_type"],
                r["price"] or None, r["bedrooms"] or None, r["bathrooms"] or None, r["area_sqm"] or None,
                r["currency"], r["price_period"], r["furnishing"], json.dumps(r, ensure_ascii=False)))
            text = re.split(r"(?:\n#{1,3} )?Register Your Interest|FOLLOW US ON|Type\n\s*Properties for Sale", r["description"], flags=re.I)[0]
            for i, content in enumerate(chunks(text)):
                cid = digest(r["id"] + str(i) + content)
                con.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (cid, r["id"], r["title"], content, r["url"], r["source"]))
                con.execute("INSERT INTO chunks_fts VALUES(?,?,?)", (cid, normalize(r["title"]), normalize(content)))
                count += 1
    con.close()
    stats = {"built_at": now(), "records": len(records), "chunks": count, "raw_pages": len(pages),
             "fetch_attempts": sum(p.get("method") != "web_index_summary" for p in attempts), "failed_attempts": len(failures),
             "by_source": dict(Counter(r["source"] for r in records)),
             "by_kind": dict(Counter(r["kind"] for r in records)),
             "by_city": dict(Counter(r["city"] for r in records if r["city"])),
             "collection_methods": dict(Counter(r["collection_method"] for r in records)),
             "coverage_note": "Partial collected corpus, not a complete or live market inventory. Research snapshots may be cached or partial. Prices and availability require source confirmation."}
    (PROCESSED / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    return stats
