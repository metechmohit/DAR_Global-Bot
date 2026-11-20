"""Recover auditable listing-card summaries from saved research snapshots.

Only uses a card when a recorded link-resolution attempt established its actual
destination URL. Does not invent slug URLs or turn unavailable details into facts.
Rich successful detail pages outrank these summaries during ingestion.
"""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.common import read_csv, write_csv, RAW_FIELDS
from app.config import RAW


def main():
    pages = [r for path in sorted(RAW.glob("*.csv")) if path.name != "index_summaries.csv" for r in read_csv(path)]
    parents = {}
    for page in pages:
        if page.get("ref") and re.search(r"^L\d+:", page.get("content", ""), re.M):
            parents[page["ref"]] = page
    summaries = {}
    for page in pages:
        url = page.get("url", "")
        if "wasalt.sa" not in url or not re.search(r"/(property|project|dailyrental)/", url):
            continue
        m = re.search(r'Source: click\((\{[^\n]+?\})\)', page.get("content", ""))
        if not m:
            continue
        try:
            request = json.loads(m[1])
        except ValueError:
            continue
        parent = parents.get(request.get("ref_id"))
        if not parent:
            continue
        marker = re.search(r"【"+str(request.get("id"))+r"†([^†】]+)(?:†[^】]*)?】", parent["content"])
        if not marker or not re.match(r"\d", marker[1]):
            continue
        label = marker[1]
        if "/project/" not in url and not re.search(r"Apartment|Villa|Floor|Land|Building|Chalet|SQM|Bedrooms|Night|شقة|دور|فيلا|أرض|ارض", label, re.I):
            continue
        end = parent["content"].find("【", marker.end())
        following = parent["content"][marker.end():end if end >= 0 else marker.end()+1200]
        content = "L0: " + label + "\n" + following
        title = re.sub(r"^[\d,.]+[KMB]?(?:\s*[-–]\s*[\d,.]+[KMB]?)?\s*(?:/Night\(Including VAT\)|yearly|monthly)?\s*", "", label, flags=re.I).strip()
        summaries[url] = {"url": url, "title": title, "content": content,
                          "fetched_at": parent["fetched_at"], "method": "web_index_summary",
                          "ref": parent["url"], "status": "ok"}
    write_csv(RAW / "index_summaries.csv", list(summaries.values()), RAW_FIELDS)
    print(f"Saved {len(summaries)} source-card summaries with resolved URLs. No inferred detail fields.")


if __name__ == "__main__":
    main()
