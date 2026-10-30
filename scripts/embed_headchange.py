#!/usr/bin/env python3
"""Update the inline Head Change catalog inside Render's single-file TerpPilot site.

Render's static-site build copies index.html but not headchange.js. This
keeps the published file current whenever the scheduled import runs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/headchange-catalog.json"
TARGET = ROOT / "index.html"
BASE = "https://headchange710.com/pharmacopeia/"
BEGIN = "<script>/* Full Head Change Pharmacopeia catalog, sourced from headchange.js */"
PATTERN = re.compile(
    re.escape(BEGIN) + r".*?</script>",
    re.DOTALL,
)


def generate(records: list[dict]) -> str:
    formats = list(dict.fromkeys(item["format"] for item in records))
    packed = [
        [
            p["name"].removesuffix(" · " + p["format"]),
            formats.index(p["format"]),
            "" if p["batch"] == "Unlisted" else p["batch"],
            p["genetics"], p["notes"], p["description"],
            p["thc"], p["tac"], p["total"], p["terps"],
            p["coa_url"], p["landing_url"].removeprefix(BASE),
            1 if p["coverage"] == "full" else 0,
            p.get("date",""),p.get("cannabinoids"),
            1 if p.get("terp_verified") else 0,
            1 if p.get("cannabinoid_verified") else 0,
            p.get("data_quality","pharmacopeia-unverified"),
        ]
        for p in records
    ]
    json_data = json.dumps(packed, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (
        BEGIN + "\n"
        + "const HEADCHANGE_FORMATS="
        + json.dumps(formats, ensure_ascii=False, separators=(",", ":"))
        + ";\nconst HEADCHANGE_PACKED=" + json_data + ";\n"
        + "window.HEADCHANGE_RECORDS=HEADCHANGE_PACKED.map((d,i)=>{"
        + "const format=HEADCHANGE_FORMATS[d[1]],"
        + "url='https://headchange710.com/pharmacopeia/'+d[11],pdf=d[10];"
        + "return {id:100001+i,brand:'Head Change',name:d[0]+' · '+format,"
        + "batch:d[2]||'Unlisted',date:d[13]||'',"
        + "category:/Cart|AIO/.test(format)?'Vape':format==='Mini Hash Hole'?'Infused Flower':'Concentrate',"
        + "format,dominance:'',genetics:d[3],notes:d[4],description:d[5],"
        + "thc:d[6],tac:d[7],total:d[8],terps:d[9],source:pdf||url,"
        + "coa_url:pdf,landing_url:url,coverage:d[12]?'full':'partial',"
        + "data_quality:d[17],terp_verified:!!d[15],cannabinoid_verified:!!d[16],"
        + "cannabinoids:d[14]||null}});\n</script>"
    )


def main() -> None:
    catalog = json.loads(SOURCE.read_text(encoding="utf-8"))
    records = catalog["records"]
    if len(records) < 500:
        raise RuntimeError("Fewer than 500 records; refusing website update.")
    src = TARGET.read_text(encoding="utf-8")
    if len(PATTERN.findall(src)) != 1:
        raise RuntimeError("Inline Head Change catalog marker not found exactly once.")
    new_src = PATTERN.sub(lambda m: generate(records), src)
    # Keep homepage totals synchronized with the validated records.
    calculated_stats = {
        "statRecords": 688 + len(records),
        "statFull": 671 + sum(p.get("coverage") == "full" for p in records),
        "statCanna": 688 + sum(bool(p.get("cannabinoid_verified")) for p in records),
    }
    for element_id, value in calculated_stats.items():
        pattern = r'(<strong id="' + re.escape(element_id) + r'">)\d+(</strong>)'
        new_src, count = re.subn(
            pattern, lambda match: match.group(1) + str(value) + match.group(2),
            new_src,
        )
        if count != 1:
            raise RuntimeError("Could not update homepage statistic " + element_id)
    new_src = new_src.replace(
        "<span>Reconciled terpene profiles</span>",
        "<span>Detailed terpene profiles</span>",
    )
    if "PRODUCTS.push(...(window.HEADCHANGE_RECORDS || []))" not in new_src:
        raise RuntimeError("TerpPilot catalog merge not found.")
    TARGET.write_text(new_src, encoding="utf-8")
    print(f"Embedded {len(records)} Head Change profiles into {TARGET}")


if __name__ == "__main__":
    main()
