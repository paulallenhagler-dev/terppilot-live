#!/usr/bin/env python3
"""Recover independently measured cannabinoids from historical two-column COAs.

Early Confident Cannabis reports put Cannabinoids and Terpenes side by side,
so the shared main parser cannot see their combined heading. This parser
handles only that historical layout. Other missing data stay missing.
"""
import json
import re
from pathlib import Path
import requests
import fitz

from scripts.enrich_headchange_coas import normalize_canna, main as refresh_catalog

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/"data/headchange-coa-cache.json"
cache=json.loads(CACHE.read_text(encoding="utf-8"))
num=re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?|ND|NR|<LOQ)$",re.I)
recovered=0
attempted=0
for url,panel in cache.items():
    if panel.get("cannabinoids"):
        continue
    attempted+=1
    try:
        r=requests.get(url,timeout=30)
        r.raise_for_status()
        d=fitz.open(stream=r.content,filetype="pdf")
        lines=[" ".join(x.split()) for x in d[0].get_text("text",sort=True).splitlines()]
        start=next((i for i,x in enumerate(lines) if x.startswith("Cannabinoids Terpenes")),None)
        if start is None:
            continue
        cannas={}
        for line in lines[start+1:]:
            if line.startswith(("Total THC =","Instrument:","Notes:")):
                break
            words=line.split()
            j=next((i for i in range(1,len(words)) if num.fullmatch(words[i]) and not num.fullmatch(words[i-1])),None)
            if j is None:
                continue
            k=j
            while k<len(words) and num.fullmatch(words[k]):
                k+=1
            values=words[j:k]
            key=normalize_canna(" ".join(words[:j]))
            if not key or len(values)<3:
                continue
            v=values[-2]
            if v in ("ND","NR","<LOQ"):
                cannas[key]=v
            else:
                n=float(v)
                if 0 <= n <= 100:
                    cannas[key]=n
        if len(cannas)<5:
            continue
        acid=cannas.get("THCA")
        thc=cannas.get("D9THC")
        if isinstance(acid,(int,float)) or isinstance(thc,(int,float)):
            cannas["TOTAL_THC"]=round((acid*0.877 if isinstance(acid,(int,float)) else 0)
                   +(thc if isinstance(thc,(int,float)) else 0),4)
        cbd=cannas.get("CBD")
        cbda=cannas.get("CBDA")
        if isinstance(cbd,(int,float)) or isinstance(cbda,(int,float)):
            cannas["TOTAL_CBD"]=round((cbd if isinstance(cbd,(int,float)) else 0)
                   +(cbda*0.877 if isinstance(cbda,(int,float)) else 0),4)
        panel["cannabinoids"]=cannas
        recovered+=1
    except Exception as e:
        print("Legacy PDF skipped:",url,str(e)[:150])
CACHE.write_text(json.dumps(cache,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
print("Legacy PDFs examined:",attempted,"recovered:",recovered)
refresh_catalog()
