#!/usr/bin/env python3
"""
CAS Number Price Lookup Tool
Scrapes BLDPharm.com and HymaSynthesis.com for price, quantity,
stock by location, and lead time.

Requirements:
    pip install requests beautifulsoup4

Usage:
    python cas_lookup.py 1122-91-4
    python cas_lookup.py              # interactive mode
"""

import sys
import re
import requests
from bs4 import BeautifulSoup

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


def _fmt(val: str) -> str:
    v = val.lower().strip()
    if "in stock" in v: return "In Stock"
    if "inquiry" in v:  return "Inquiry"
    if "sign in" in v:  return "(login)"
    return val or "—"

def scrape_bld(cas: str) -> dict:
    url = f"https://www.bldpharm.com/products/{cas}.html"
    try:
        resp = _session.get(url, timeout=20)
    except Exception as e:
        return {"error": str(e)}
    if resp.status_code == 404:
        return {"found": False, "message": f"CAS {cas} not found on BLD Pharm (404)."}
    if resp.status_code != 200:
        return {"error": f"BLD Pharm returned HTTP {resp.status_code}"}
    soup = BeautifulSoup(resp.text, "html.parser")
    parts  = (soup.title.string or "").split("|")
    cas_no = parts[0].strip() if parts else cas
    name   = parts[1].strip() if len(parts) > 1 else "—"
    cat_no, purity = "—", "—"
    for el in soup.find_all(string=re.compile(r"Cat\.\s*No\.")):
        txt = el.parent.get_text(" ", strip=True)
        m  = re.search(r"Cat\.\s*No\.:\s*(\S+)", txt)
        m2 = re.search(r"(\d+%)", txt)
        if m:  cat_no = m.group(1)
        if m2: purity = m2.group(1)
        if cat_no != "—": break
    lt = re.search(r"\d+[-–]\d+\s*weeks?", resp.text, re.IGNORECASE)
    lead_time = lt.group(0) if lt else None
    rows = []
    for tr in soup.select("table.pro_table tr.tr_stock"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 7: continue
        rows.append({"size": tds[0], "price": tds[1], "hyderabad": _fmt(tds[4]), "delhi": _fmt(tds[5]), "germany": _fmt(tds[6])})
    if not rows:
        return {"found": False, "message": f"CAS {cas} page loaded but no pricing table found."}
    return {"found": True, "url": url, "cas": cas_no, "name": name, "catalog_no": cat_no, "purity": purity, "lead_time": lead_time, "rows": rows}


def scrape_hyma(cas: str) -> dict:
    try:
        r1 = _session.get(
            "https://hymasynthesis.com/webservices/api/Values/GetChemicalNames",
            params={"Query": cas}, timeout=15,
        )
        r1.raise_for_status()
        chemicals = r1.json()
    except Exception as e:
        return {"error": str(e)}
    if not chemicals:
        return {"found": False, "message": f"CAS {cas} not found on Hyma Synthesis."}
    all_rows = []
    for chem in chemicals:
        parts = [p.strip() for p in chem.get("ChemicalName", "").split("|")]
        if len(parts) < 2: continue
        item_name  = parts[0]
        catalog_no = parts[1]
        group      = parts[3] if len(parts) > 3 else ""
        try:
            r2 = _session.get(
                "https://hymasynthesis.com/webservices//api/Values/GetWebStockItemMstBasedOnId",
                params={"ItemCode": catalog_no}, timeout=15,
            )
            r2.raise_for_status()
            prod_det = r2.json().get("ProdDet", [])
        except Exception:
            continue
        for item in prod_det:
            pack_size = item.get("PackSize", "").strip()
            if not pack_size: continue
            price = item.get("Price", "").strip() or "Inquiry"
            qty_avail = item.get("QtyA", "0")
            qty_total = item.get("Qty", "0")
            gst = item.get("GSTTAX", 0)
            try:   avail_f = float(qty_avail)
            except: avail_f = 0.0
            try:   total_f = float(qty_total)
            except: total_f = 0.0
            all_rows.append({"catalog_no": catalog_no, "name": item_name, "group": group, "pack_size": pack_size, "price_inr": price, "qty_avail": int(avail_f), "qty_total": total_f, "gst": gst})
    if not all_rows:
        return {"found": False, "message": f"CAS {cas} found but no pack/price data on Hyma Synthesis."}
    return {"found": True, "cas": cas, "rows": all_rows}


W = 72

def print_bld(d: dict):
    print("\n" + "═" * W)
    print("  BLD PHARM  |  bldpharm.com")
    print("═" * W)
    if "error" in d:
        print(f"  ERROR: {d['error']}")
    elif not d["found"]:
        print(f"  Not found: {d['message']}")
    else:
        print(f"  Name      : {d['name']}")
        print(f"  CAS       : {d['cas']}")
        print(f"  Cat. No.  : {d['catalog_no']}   Purity: {d['purity']}")
        if d.get("lead_time"):
            print(f"  Lead Time : {d['lead_time']}  (custom / large sizes)")
        print(f"  URL       : {d['url']}")
        print()
        print(f"  {'Size':<9}  {'Price (INR)':<16}  {'Hyderabad':<14}  {'Delhi':<14}  {'Germany'}")
        print("  " + "─" * (W - 2))
        for r in d["rows"]:
            print(f"  {r['size']:<9}  {r['price']:<16}  {r['hyderabad']:<14}  {r['delhi']:<14}  {r['germany']}")
        print()
        print("  Note: US & Global stock quantities require sign-in on BLD Pharm.")
    print("═" * W)


def print_hyma(d: dict):
    print("\n" + "═" * W)
    print("  HYMA SYNTHESIS  |  hymasynthesis.com  (ships from Hyderabad)")
    print("═" * W)
    if "error" in d:
        print(f"  ERROR: {d['error']}")
    elif not d["found"]:
        print(f"  Not found: {d['message']}")
    else:
        print(f"  CAS: {d['cas']}")
        prev_cat = None
        for r in d["rows"]:
            if r["catalog_no"] != prev_cat:
                prev_cat = r["catalog_no"]
                print(f"\n  [{r['catalog_no']}]  {r['name']}  ({r['group']})")
                print(f"  {'Pack Size':<22}  {'Price (INR)':<14}  {'Avail.Qty':<12}  {'Total Stock':<14}  GST")
                print("  " + "─" * (W - 2))
            avail = str(r["qty_avail"]) if r["qty_avail"] > 0 else "0"
            total = str(r["qty_total"]).rstrip("0").rstrip(".") if r["qty_total"] else "0"
            stock = "✓" if r["qty_avail"] > 0 else ("~" if r["qty_total"] > 0 else "✗")
            print(f"  {r['pack_size']:<22}  {r['price_inr']:<14}  {stock} {avail:<10}  {total:<14}  {r['gst']}%")
        print()
        print("  Avail.Qty = quantity available to order now")
        print("  Total Stock = physical stock in warehouse   ✓=available  ~=stock exists  ✗=out of stock")
    print("═" * W)


def lookup(cas: str):
    cas = cas.strip()
    print(f"\nLooking up CAS: {cas}  ...")
    print_bld(scrape_bld(cas))
    print_hyma(scrape_hyma(cas))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        lookup(" ".join(sys.argv[1:]))
    else:
        print("\n" + "═" * W)
        print("  CAS Lookup  —  BLDPharm + HymaSynthesis")
        print("  Usage:  python cas_lookup.py <CAS_NUMBER>")
        print("═" * W)
        while True:
            try:
                cas = input("\nEnter CAS number (or 'q' to quit): ").strip()
            except (KeyboardInterrupt, EOFError):
                print(); break
            if cas.lower() in ("q", "quit", "exit"): break
            if cas: lookup(cas)
