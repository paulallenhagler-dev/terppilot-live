#!/usr/bin/env python3
"""Import Head Change Pharmacopeia into TerpPilot without altering existing Vivid/Robust records.

Source: https://headchange710.com/pharmacopeia/a-z
Output: headchange.js, data/headchange-catalog.json, data/headchange-import-report.json

The Pharmacopeia is a release/product catalog, not a guarantee of a complete
batch-specific COA. We preserve original links and never invent absent analytes.
"""
from __future__ import annotations
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://headchange710.com"
INDEX = BASE + "/pharmacopeia/a-z"
ROOT = Path(__file__).resolve().parents[1]
FORMATS = (
    "Live Rosin Cart", "Live Resin AIO", "Live Rosin AIO", "Mini Hash Hole",
    "Sauce Cart", "Live Badder", "Live Sugar", "Live Rosin", "Live Slush",
)
ALIASES = {
    "Beta-Myrcene": "β-Myrcene", "Beta-Caryophyllene": "β-Caryophyllene",
    "Alpha-Humulene": "α-Humulene", "Alpha-Pinene": "α-Pinene",
    "Beta-Pinene": "β-Pinene", "Alpha-Bisabolol": "α-Bisabolol",
    "Delta-Limonene": "Limonene", "Trans-Caryophyllene": "β-Caryophyllene",
    "Alpha-Terpinene": "α-Terpinene", "Gamma-Terpinene": "γ-Terpinene",
}
HEADING = re.compile(r"^\s*(.*?)\s+([0-9]+(?:\.[0-9]+)?)\s*%\s*$")
PERCENT = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")


def make_session():
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=0.7,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "TerpPilotResearch/1.0 (+public profile archival; respectful rate limit)",
        "Accept": "text/html,application/xhtml+xml",
    })
    return session


def fetch(session, url):
    r = session.get(url, timeout=25)
    r.raise_for_status()
    if "html" not in r.headers.get("Content-Type", "").lower():
        raise ValueError("Unexpected non-HTML content for " + url)
    return BeautifulSoup(r.text, "html.parser")


def catalog_urls(session):
    doc = fetch(session, INDEX)
    urls = []
    seen = set()
    for a in doc.select("a[href]"):
        absolute = urljoin(BASE, a.get("href", ""))
        parts = urlsplit(absolute)
        path = parts.path.rstrip("/")
        if parts.netloc != "headchange710.com":
            continue
        if not path.startswith("/pharmacopeia/") or path == "/pharmacopeia/a-z":
            continue
        if path.count("/") != 2:
            continue
        url = urlunsplit(("https", parts.netloc, path, "", ""))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    if len(urls) < 500:
        raise RuntimeError(
            "Only found %d detail URLs; expected >=500. "
            "Stopping to avoid publishing an incomplete catalog." % len(urls)
        )
    return urls


def heading_text(parent, title, next_tag=None):
    for h in parent.find_all(["h2", "h3", "h4"]):
        if h.get_text(" ", strip=True).lower() == title.lower():
            p = h.find_next(next_tag or "p")
            if p:
                return p.get_text(" ", strip=True)
    return ""


def as_pct(text):
    m = PERCENT.search(text or "")
    return float(m.group(1)) if m else None


def extract_spec(lines, key):
    try:
        i = next(i for i, value in enumerate(lines) if value.casefold() == key.casefold())
    except StopIteration:
        return None
    if i + 1 >= len(lines):
        return None
    return lines[i + 1]


def parse_product(session, url, idx):
    doc = fetch(session, url)
    main = doc.find("main") or doc
    h1 = main.find("h1")
    if not h1:
        raise ValueError("No title heading: " + url)
    name = h1.get_text(" ", strip=True)
    hero = h1.find_parent("section") or main
    hero_text = hero.get_text(" ", strip=True)
    hero_paragraphs = [p.get_text(" ", strip=True) for p in hero.find_all("p")]
    fmt = next((f for f in FORMATS if any(f in p for p in hero_paragraphs[:2])), None)
    if fmt is None:
        # Not every historical entry has the same banner markup.
        fmt = next((f for f in FORMATS if f in hero_text[:160]), "Unknown")
    dominance = next(
        (p.replace(fmt, "").strip(" ·–") for p in hero_paragraphs[:2] if fmt in p), ""
    )
    thc = as_pct(re.search(r"Total THC\s*([0-9.]+\s*%)", hero_text, re.I).group(1)) if re.search(r"Total THC\s*([0-9.]+\s*%)", hero_text, re.I) else None
    tac = as_pct(re.search(r"\bTAC\s*([0-9.]+\s*%)", hero_text, re.I).group(1)) if re.search(r"\bTAC\s*([0-9.]+\s*%)", hero_text, re.I) else None
    total = as_pct(re.search(r"Total Terps\s*([0-9.]+\s*%)", hero_text, re.I).group(1)) if re.search(r"Total Terps\s*([0-9.]+\s*%)", hero_text, re.I) else None

    geno_node = h1.find_next("p")
    genetics = geno_node.get_text(" ", strip=True) if geno_node else ""
    if genetics.startswith(("Total THC", "TAC", "Total Terps")):
        genetics = ""

    terps = {}
    for h in main.find_all(["h2", "h3"]):
        if h.get_text(" ", strip=True).lower() == "terpene profile":
            panel = h.find_next("ul")
            if panel:
                for li in panel.find_all("li"):
                    label = li.get_text(" ", strip=True)
                    m = HEADING.match(label)
                    if m:
                        key = ALIASES.get(m.group(1).strip(), m.group(1).strip())
                        terps[key] = float(m.group(2))
            break

    links = [urljoin(url, a.get("href", "")) for a in main.select("a[href]")]
    pdf = next((u for u in links if ".pdf" in urlsplit(u).path.lower()), None)
    if not pdf:
        pdf = next(
            (urljoin(url, a.get("href", "")) for a in doc.select("a[href]")
             if ".pdf" in urlsplit(urljoin(url, a.get("href", ""))).path.lower()),
            None,
        )

    # These are the website's listed specs, not an independent PDF transcription.
    lines = list(main.stripped_strings)
    batch = extract_spec(lines, "Batch") or "Unlisted"
    if not re.match(r"^[A-Za-z0-9#][A-Za-z0-9# ._\-/]{0,100}$", batch):
        batch = "Unlisted"
    cannabinoids = {}
    for field, target in [("Total THC", "TOTAL_THC"), ("CBD", "CBD"),
                          ("CBG", "CBG"), ("CBN", "CBN")]:
        # Prefer the Specs/Cannabinoids section, avoiding banner figures.
        try:
            start = next(i for i, t in enumerate(lines) if t == "Cannabinoids")
            stop = next((i for i in range(start + 1, len(lines)) if lines[i] == "Genotype"), len(lines))
            spec = extract_spec(lines[start:stop], field)
            value = as_pct(spec)
            if value is not None:
                cannabinoids[target] = value
        except StopIteration:
            pass

    terp_sum = sum(terps.values())
    full = (
        total is not None and total > 0 and len(terps) >= 7
        and abs(terp_sum - total) <= max(0.40, total * 0.07)
    )
    category = "Vape" if ("Cart" in fmt or "AIO" in fmt) else (
        "Infused Flower" if fmt == "Mini Hash Hole" else "Concentrate"
    )
    result = {
        "id": 100001 + idx,
        "brand": "Head Change",
        "name": name + " · " + fmt,
        "batch": batch,
        "date": "",  # no test date asserted until confirmed from report
        "category": category,
        "format": fmt,
        "dominance": dominance,
        "genetics": genetics,
        "notes": heading_text(main, "Hash Notes"),
        "description": heading_text(main, "About this blend"),
        "thc": thc, "tac": tac, "total": total, "terps": terps,
        "source": pdf or url,
        "coa_url": pdf, "landing_url": url,
        "coverage": "full" if full else "partial",
        "data_quality": "pharmacopeia-listed-coa" if pdf else "pharmacopeia-no-pdf",
        "cannabinoids": cannabinoids or None,
    }
    return result


def main():
    start = time.monotonic()
    sess = make_session()
    urls = catalog_urls(sess)
    products, errors = [], []
    for i, url in enumerate(urls):
        try:
            p = parse_product(sess, url, i)
            if p["name"].startswith(" · "):
                raise ValueError("Empty name")
            products.append(p)
        except Exception as exc:
            errors.append({"url": url, "error": str(exc)[:350]})
        if (i + 1) % 50 == 0:
            print("Head Change: %d/%d pages, %d parsed, %d errors" %
                  (i + 1, len(urls), len(products), len(errors)), flush=True)
        time.sleep(0.18)

    # Fail closed: never erase a good existing catalog with a partial crawl.
    if len(products) < max(500, len(urls) - 8):
        raise RuntimeError("Extracted %d/%d; %d failures. Publication aborted: %s" %
                           (len(products), len(urls), len(errors), errors[:5]))
    if len({x["landing_url"] for x in products}) != len(products):
        raise RuntimeError("Duplicate landing URLs; aborting.")

    products.sort(key=lambda p: p["id"])
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    catalog = {
        "source": INDEX,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(products),
        "records": products,
    }
    (data / "headchange-catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "headchange.js").write_text(
        "/* Head Change Pharmacopeia: public historical product data; "
        "not live stock. Generated by scripts/import_headchange.py. */\n"
        + "window.HEADCHANGE_RECORDS="
        + json.dumps(products, ensure_ascii=False, separators=(",", ":"))
        + ";\n", encoding="utf-8",
    )
    report = {
        "retrieved_at": catalog["retrieved_at"],
        "discovered": len(urls),
        "imported": len(products),
        "with_original_pdf": sum(bool(p["coa_url"]) for p in products),
        "with_measured_terpenes": sum(bool(p["terps"]) for p in products),
        "reconciled_profiles": sum(p["coverage"] == "full" for p in products),
        "missing_or_partial": sum(p["coverage"] != "full" for p in products),
        "errors": errors,
        "elapsed_seconds": round(time.monotonic() - start, 2),
    }
    (data / "headchange-import-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("HEAD CHANGE IMPORT FAILED:", error, file=sys.stderr)
        raise
