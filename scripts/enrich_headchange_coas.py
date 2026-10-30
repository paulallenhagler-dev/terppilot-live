#!/usr/bin/env python3
"""Extract original cannabinoid and terpene panels from Head Change COA PDFs.

Fail closed on ambiguous measurements: preserve existing website values,
keep missing analytes missing, and record mismatches for review. The COA
cache prevents re-fetching unchanged reports during weekly updates.
"""
from __future__ import annotations
import concurrent.futures as cf
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz
import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/headchange-catalog.json"
CACHE = ROOT / "data/headchange-coa-cache.json"
REPORT = ROOT / "data/headchange-enrichment-report.json"
WHITELIST = {
    "THCA": "THCA", "THC": "D9THC", "D9THC": "D9THC",
    "D8THC": "D8THC", "THCV": "THCV", "THCVA": "THCVA",
    "CBDA": "CBDA", "CBD": "CBD", "CBDVA": "CBDVA", "CBDV": "CBDV",
    "CBGA": "CBGA", "CBG": "CBG", "CBNA": "CBNA", "CBN": "CBN",
    "CBCA": "CBCA", "CBC": "CBC", "CBLA": "CBLA", "CBL": "CBL",
}
STATUSES = {"ND", "NR", "<LOQ", "NT", "<LOD"}
ROWS = re.compile(r"^(.+?)\s+((?:(?:<?LOQ|<?LOD|ND|NR|NT|-|[0-9]+(?:\.[0-9]+)?)\s*)+)$", re.I)
DNUM = re.compile(r"^(?:-|\d+(?:\.\d+)?|ND|NR|NT|<LOQ|<LOD)$", re.I)
ALIASES = {
    "trans-Caryophyllene": "β-Caryophyllene",
    "beta-Caryophyllene": "β-Caryophyllene",
    "beta-Myrcene": "β-Myrcene",
    "alpha-Humulene": "α-Humulene",
    "alpha-Pinene": "α-Pinene",
    "beta-Pinene": "β-Pinene",
    "alpha-Bisabolol": "α-Bisabolol",
    "delta-Limonene": "Limonene",
    "δ-Limonene": "Limonene",
    "Δ-Limonene": "Limonene",
    "D-Limonene": "Limonene",
}
BAD_HEADERS = ("Analyte", "Date Tested", "SOP/", "T otal", "Total ",
               "Primary Aromas", "Notes:", "Result", "Con\x00dent",
               "Results pertain", "Laboratory", "Sample", "Method",
               "Cannabinoids", "Terpenes")


def normalize_line(line: str) -> str:
    line = re.sub(r"(?<=\b[A-Za-z])\s+(?=[a-z]{3,})", " ", line) if False else line
    line = line.replace("\x00", "fi").replace("\ufb01", "fi")
    line = re.sub(r"\bT\s+erpenes\b", "Terpenes", line, flags=re.I)
    line = re.sub(r"\bT\s+otal\b", "Total", line, flags=re.I)
    line = re.sub(r"\bT\s+ested\b", "Tested", line, flags=re.I)
    line = re.sub(r"\bT\s+HC\b", "THC", line, flags=re.I)
    line = re.sub(r"([αβγΔ])-\s*([A-Za-z])\s+([a-z]{3,})", r"\1-\2\3", line)
    line = re.sub(r"\bT\s+erpin", "Terpin", line, flags=re.I)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def normalize_canna(word: str) -> str | None:
    word = word.upper().replace("Δ9", "D9").replace("Δ8", "D8")
    word = word.replace("-", "").replace(" ", "")
    if word == "THC":
        word = "D9THC"
    return WHITELIST.get(word)


def normalize_terp(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"(?i)\bT\s+erpin", "Terpin", name)
    name = name.replace("alpha-", "α-").replace("beta-", "β-")
    if name.startswith("trans-"):
        name = "Trans-" + name[6:]
    if name.startswith("cis-"):
        name = "Cis-" + name[4:]
    name = ALIASES.get(name, name)
    if name == "Trans-Caryophyllene":
        name = "β-Caryophyllene"
    if name == "3-Carene":
        name = "Δ3-Carene"
    return name


def parse_row(line: str) -> tuple[str, list[str]] | None:
    # PyMuPDF sorted text can place a right-hand "Primary Aromas" label
    # after a valid left-hand table row; capture the FIRST numeric run.
    tokens = line.strip().split()
    start = next((i for i in range(1,len(tokens)) if DNUM.fullmatch(tokens[i])
                  and not DNUM.fullmatch(tokens[i-1])),None)
    if start is None:
        return None
    end = start
    while end < len(tokens) and DNUM.fullmatch(tokens[end]):
        end += 1
    if end-start < 2:
        return None
    return " ".join(tokens[:start]), tokens[start:end]


def percent_from_row(values: list[str], table: str, header: str):
    if not values:
        return None
    # The last data column varies by lab (mg/g versus percent).
    # CloudTen LOQ Mass Mass (mg/serving mg/serving %) => last.
    # Confident LOQ Mass Mass (% % mg/g) => penultimate.
    # Fleur-de-Lis LOD LOQ Result Result (% % % mg/g) => penultimate.
    if table == "terp":
        idx = -1 if "mg/g mg/g %" in header else -2 if "mg/g" in header else -1
    else:
        idx = -1 if "mg/serving mg/serving %" in header else -2 if len(values) >= 3 else -1
    if len(values) < abs(idx):
        idx = -1
    v = values[idx].upper()
    if v in STATUSES:
        return v
    if v == "-":
        return None
    try:
        n = float(v)
        return n if 0 <= n <= 100 else None
    except ValueError:
        return None


def extract_panels(pdf_bytes: bytes) -> dict:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) < 1 or len(doc) > 50:
        raise ValueError("Unexpected PDF page count")
    text = "\n".join(page.get_text("text", sort=True) for page in doc)
    lines = [normalize_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    front = " ".join(lines[:140])
    original = text
    date_match = re.search(r"Report Created:\s*(\d{2}/\d{2}/\d{4})", original)
    if not date_match:
        date_match = re.search(r"\bCompleted:\s*(\d{2}/\d{2}/\d{4})", original)
    report_date = ""
    if date_match:
        try:
            report_date = datetime.strptime(date_match.group(1), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    batch_match = re.search(r"Batch#:\s*([^;\n]+)", original)
    batch = (batch_match.group(1).strip() if batch_match else "")[:100]
    if batch.lower().startswith(("batch size", "units")):
        batch = ""

    cannas: dict[str, float | str] = {}
    terps: dict[str, float] = {}
    terp_total = None
    mode = ""
    header = ""
    found_canna = False
    found_terp = False
    for i, line in enumerate(lines):
        lower = line.lower()
        if lower == "cannabinoids" or lower.startswith("cannabinoids complete") or lower.startswith("cannabinoids pass"):
            mode = "canna"
            found_canna = True
            header = " ".join(lines[i:i+5])
            continue
        if lower == "terpenes" or lower.startswith("terpenes complete") or lower.startswith("terpenes primary aromas"):
            mode = "terp"
            found_terp = True
            header = " ".join(lines[i:i+6])
            continue
        if mode == "canna":
            if line.startswith(("SOP/", "Instrument:", "Safety", "Moisture", "Microbials",
                                "Pesticides", "Total THC =", "Total CBD =", "Foreign Matter",
                                "Residual Solvents", "Heavy Metals", "Mycotoxins",
                                "Confi", "Confident", "Date Tested:")):
                mode = ""
                continue
            parsed = parse_row(line)
            if parsed:
                name, vals = parsed
                key = normalize_canna(name)
                if key:
                    val = percent_from_row(vals, "canna", header)
                    if val is not None and key not in cannas:
                        cannas[key] = val
        elif mode == "terp":
            if line.startswith(("Primary Aromas", "SOP/", "Notes:", "Results pertain",
                                "Confident", "Confi", "Date Tested:")):
                mode = ""
                continue
            parsed = parse_row(line)
            if parsed:
                name, vals = parsed
                if name.lower() == "total":
                    val = percent_from_row(vals, "terp", header)
                    if isinstance(val, float):
                        terp_total = val
                    mode = ""
                else:
                    key = normalize_terp(name)
                    if not re.match(r"^[A-Za-zαβγδΔ][A-Za-zαβγδΔ0-9\- ]{1,40}$", key):
                        continue
                    val = percent_from_row(vals, "terp", header)
                    if isinstance(val, float):
                        if key in terps: continue
                        # FDL includes aggregate alias rows after named isomers.
                        if key in ("Nerolidol", "Ocimene", "Terpineol"):
                            prefix = {"Nerolidol":"Nerolidol","Ocimene":"Ocimene",
                                      "Terpineol":"Terpineol"}[key]
                            if any(prefix in k and abs(n-val) < 0.003 for k,n in terps.items()):
                                continue
                        terps[key] = val
    # ContiCorp (2026) prints two cannabinoid analyte columns side by side.
    # PyMuPDF sort=True merges the columns into one row, so the general
    # parser cannot reliably identify them. Its native text order is:
    # [analyte name, % by mass, mg/serving] for each analyte, first column
    # then second. Read ONLY this validated format, and use the % column.
    first_page_text = doc[0].get_text("text", sort=False)
    if "ConcentrationConcentration" in first_page_text and "Cannabinoids" in first_page_text:
        raw = [normalize_line(z) for z in first_page_text.splitlines()]
        try:
            section_start = raw.index("Cannabinoids")
        except ValueError:
            section_start = -1
        if section_start >= 0:
            first_pass = {}
            status_tokens = STATUSES | {"NR", "ND"}
            for k in range(section_start+1, len(raw)-2):
                if raw[k].startswith(("Total Δ9-THC =", "Total THC =", "Instrument:", "Mycotoxins")):
                    break
                key = normalize_canna(raw[k])
                if not key:
                    continue
                a, b = raw[k+1].upper(), raw[k+2].upper()
                if not (DNUM.fullmatch(a) and DNUM.fullmatch(b)):
                    continue
                if a in status_tokens:
                    first_pass[key] = a
                    continue
                try:
                    percent, mass = float(a), float(b)
                except ValueError:
                    continue
                # The mass column is mg per serving, usually 10x the
                # percentage number for these COAs. Guard against shifted
                # columns and reject nonsensical values.
                if not 0 <= percent <= 100:
                    continue
                # Depending on package/serving size, the second column
                # is typically 0.05x, 0.1x or 10x the concentration.
                # Only reject impossible mass scaling, not a cart size.
                if percent > 0 and not 0.01 <= mass/percent <= 20:
                    continue
                first_pass[key] = percent
            if len(first_pass) >= 5 and (
                isinstance(first_pass.get("THCA"),float) or
                isinstance(first_pass.get("D9THC"),float)
            ):
                cannas = first_pass
                found_canna = True
    # GCA Labs January 2023 reports include CAS numbers between
    # cannabinoid name and concentration. Extract the percent column,
    # not the later mg/g mass column.
    if not cannas and "GCA Labs" in first_page_text:
        gca_rows = {}
        gca_pattern = re.compile(
            r"^\s*(THCa|Δ9-THC|Δ8-THC|THCVa|THCV|CBDa|CBD|CBDVa|CBDV|CBN|CBGa|CBG|CBC)\s+"
            r"[0-9-]+\s+[0-9.]+\s+(ND|NR|<LOQ|[0-9]+(?:\.[0-9]+)?)\s+(?:ND|NR|<LOQ|[0-9.]+)\b",
            re.IGNORECASE,
        )
        for original_row in doc[0].get_text("text",sort=True).splitlines():
            row = normalize_line(original_row)
            match = gca_pattern.match(row)
            if not match:
                continue
            key = normalize_canna(match.group(1))
            val = match.group(2).upper()
            if key and (val in STATUSES or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",val)):
                gca_rows[key] = val if val in STATUSES else float(val)
        if len(gca_rows)>=5 and (
            isinstance(gca_rows.get("THCA"),float) or
            isinstance(gca_rows.get("D9THC"),float)
        ):
            cannas = gca_rows
            found_canna = True
    # Reported THC from analytes, never from an unlabeled serving mass.
    thc = None
    if isinstance(cannas.get("THCA"), float) or isinstance(cannas.get("D9THC"), float):
        thc = round((cannas["THCA"] * 0.877 if isinstance(cannas.get("THCA"), float) else 0)
                    + (cannas["D9THC"] if isinstance(cannas.get("D9THC"), float) else 0), 4)
    if cannas:
        if thc is not None: cannas["TOTAL_THC"] = thc
        cbd = cannas.get("CBD")
        cbda = cannas.get("CBDA")
        if isinstance(cbd,float) or isinstance(cbda,float):
            cannas["TOTAL_CBD"] = round((cbd if isinstance(cbd,float) else 0)
                    +(cbda*0.877 if isinstance(cbda,float) else 0),4)
        elif cbd=="ND" and cbda=="ND":
            cannas["TOTAL_CBD"] = "ND"
    if terp_total is not None and not 0 <= terp_total <= 40:
        terp_total = None
    summed = round(sum(terps.values()),4)
    reconciled = bool(terps and terp_total is not None and
                      abs(summed-terp_total) <= max(0.12,terp_total*0.025))
    return {
        "date": report_date,"batch":batch,"cannabinoids":cannas,
        "terps":terps,"terp_total":terp_total,"terp_sum":summed,
        "terp_reconciled":reconciled,"has_cannabinoid_section":found_canna,
        "has_terp_section":found_terp,"pdf_pages":len(doc),
    }


def download_and_parse(args):
    url, retries = args
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=45, headers={
                "User-Agent":"TerpPilotHistoricalChemistryResearch/1.0",
                "Accept":"application/pdf",
            })
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError("Source did not return a PDF")
            if len(response.content) > 16_000_000:
                raise ValueError("Oversized PDF")
            return url, extract_panels(response.content), None
        except Exception as exc:
            if attempt + 1 == retries:
                return url, None, str(exc)[:220]
            time.sleep(attempt + 1)


def enrich(products: list[dict], cache: dict):
    audit = []
    for p in products:
        pdf = p.get("coa_url")
        panel = cache.get(pdf) if pdf else None
        if not panel:
            audit.append({"product":p["name"],"reason":"no_original_pdf" if not pdf else "pdf_unavailable"})
            continue
        p["coa_extraction"] = "original_pdf_parsed"
        p["coa_pages"] = panel.get("pdf_pages")
        if panel.get("date"):
            p["date"] = panel["date"]
        if p.get("batch") in ("", "Unlisted") and panel.get("batch"):
            p["batch"] = panel["batch"]
        p["cannabinoids"] = panel["cannabinoids"] or None
        p["cannabinoid_verified"] = len(panel.get("cannabinoids") or {}) >= 5
        if p["cannabinoids"] and isinstance(p["cannabinoids"].get("TOTAL_THC"),float):
            verified = p["cannabinoids"]["TOTAL_THC"]
            earlier = p.get("thc")
            if earlier is not None and abs(verified-earlier)>2:
                audit.append({"product":p["name"],"reason":"thc_discrepancy",
                              "website_thc":earlier,"coa_thc":verified})
            p["thc"] = verified
        if panel.get("terp_reconciled") and len(panel.get("terps") or {})>=3:
            p["terps"] = panel["terps"]
            p["total"] = panel["terp_total"]
            p["coverage"] = "full"
            p["terp_verified"] = True
            p["data_quality"] = "original-coa-quantitative"
        else:
            p["terp_verified"] = False
            if panel.get("terps"):
                audit.append({"product":p["name"],"reason":"terp_panel_not_reconciled",
                              "coa_total":panel.get("terp_total"),"coa_sum":panel.get("terp_sum")})
            if p["coverage"] != "full":
                audit.append({"product":p["name"],"reason":"terp_profile_incomplete"})
            p["data_quality"] = "pharmacopeia-indexed-with-coa"
    return audit


def main():
    doc = json.loads(CATALOG.read_text(encoding="utf-8"))
    products = doc["records"]
    if len(products) < 500:
        raise RuntimeError("Refusing to enrich incomplete catalog")
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    urls = list(dict.fromkeys(p["coa_url"] for p in products if p.get("coa_url")))
    todo = [u for u in urls if
            u not in cache
            or (cache[u].get("has_cannabinoid_section") and not cache[u].get("cannabinoids") and not cache[u].get("terps"))
            or (cache[u].get("has_terp_section") and cache[u].get("terps") and not cache[u].get("terp_reconciled"))
            or (not cache[u].get("has_cannabinoid_section") and not cache[u].get("cannabinoids"))]
    errors = {}
    if todo:
        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            for index,(url,data,err) in enumerate(pool.map(download_and_parse,
                    [(u,3) for u in todo]),1):
                if data: cache[url] = data
                else: errors[url] = err
                if index % 50 == 0: print(f"COAs checked {index}/{len(todo)}",flush=True)
    # Cache only successfully parsed results and write atomically on success.
    CACHE.write_text(json.dumps(cache,ensure_ascii=False,separators=(",",":"))+"\n",
                     encoding="utf-8")
    audit = enrich(products,cache)
    report = {
        "retrieved_at":datetime.now(timezone.utc).isoformat(),
        "catalog_entries":len(products),"pdfs_linked":len(urls),
        "pdfs_parsed":sum(url in cache for url in urls),
        "pdf_download_or_parse_errors":errors,
        "cannabinoid_panels_verified":sum(bool(p.get("cannabinoid_verified")) for p in products),
        "terp_panels_verified_from_pdf":sum(bool(p.get("terp_verified")) for p in products),
        "terp_panels_full_or_reconciled":sum(p["coverage"]=="full" for p in products),
        "terp_panels_partial":sum(p["coverage"]!="full" for p in products),
        "audit_flags":audit,
    }
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    CATALOG.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (ROOT/"headchange.js").write_text(
        "/* Head Change historical product profiles: lab provenance attached. */\n"
        "window.HEADCHANGE_RECORDS="+json.dumps(products,ensure_ascii=False,separators=(",",":"))+";\n",
        encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("audit_flags","pdf_download_or_parse_errors")}
                     |{"audit_flags_count":len(audit),"pdf_errors_count":len(errors)},indent=2),flush=True)
    if len(cache) < 200 or report["cannabinoid_panels_verified"] < 250 or report["terp_panels_verified_from_pdf"] < 150:
        raise RuntimeError("Insufficient independently extracted panels; refusing publication")


if __name__=="__main__":
    main()
