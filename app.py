import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="CAS Price Lookup", page_icon="🧪", layout="wide")

st.title("🧪 CAS Number Price Lookup")
st.caption("Live pricing & availability from **BLD Pharm** and **Hyma Synthesis**")


@st.cache_resource
def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


# ── BLD Pharm ──────────────────────────────────────────────
# Stock table columns (0-indexed):
#   0=Size  1=Price  2=Special Offer  3=US-qty(login)
#   4=Hyderabad  5=Delhi  6=Germany  7=Global(login)

def _stock_icon(val: str) -> str:
    v = val.lower().strip()
    if "in stock" in v:   return "✅ In Stock"
    if "inquiry" in v:    return "📋 Inquiry"
    if "sign in" in v:    return "🔒 Sign In"
    return val or "—"


def _scrape_bld_product(cas: str, url: str) -> dict:
    """Scrape a single BLD Pharm product page (may include ?BD= param)."""
    try:
        resp = get_session().get(url, timeout=20)
    except Exception as e:
        return {"error": str(e)}

    if resp.status_code == 404:
        return {"found": False}
    if resp.status_code != 200:
        return {"error": f"BLD Pharm returned HTTP {resp.status_code}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    parts  = (soup.title.string or "").split("|")
    cas_no = parts[0].strip() if parts else cas
    name   = parts[1].strip() if len(parts) > 1 else "—"

    cat_no, purity = "—", "—"
    for el in soup.find_all(string=re.compile(r"Cat\.\s*No\.")):
        txt = el.parent.get_text(" ", strip=True)
        m   = re.search(r"Cat\.\s*No\.:\s*(\S+)", txt)
        m2  = re.search(r"(\d+%)", txt)
        if m:  cat_no = m.group(1)
        if m2: purity = m2.group(1)
        if cat_no != "—": break

    lt = re.search(r"\d+[-–]\d+\s*weeks?", resp.text, re.IGNORECASE)
    lead_time = lt.group(0) if lt else None

    rows = []
    for tr in soup.select("table.pro_table tr.tr_stock"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 7:
            continue
        rows.append({
            "Size":        tds[0],
            "Price (INR)": tds[1],
            "Hyderabad":   _stock_icon(tds[4]),
            "Delhi":       _stock_icon(tds[5]),
            "Germany":     _stock_icon(tds[6]),
        })

    if not rows:
        return {"found": False}

    return {
        "found": True, "url": url,
        "cas": cas_no, "name": name,
        "catalog_no": cat_no, "purity": purity,
        "lead_time": lead_time, "rows": rows,
    }


def scrape_bld(cas: str) -> dict:
    """
    1. Fetch search page to enumerate all BD catalog numbers for this CAS.
    2. Scrape each catalog's product page individually.
    3. Fallback to direct URL if search yields no BD numbers.
    """
    session = get_session()

    # Step 1 — search page
    search_url = f"https://www.bldpharm.com/search/Search.html?keyword={cas}"
    try:
        r = session.get(search_url, timeout=20)
    except Exception as e:
        return {"error": str(e)}

    if r.status_code != 200:
        return {"error": f"BLD Pharm search returned HTTP {r.status_code}"}

    soup = BeautifulSoup(r.text, "html.parser")

    # Extract unique BD catalog numbers from href attributes
    bd_numbers = []
    pattern = re.compile(
        r"/products/" + re.escape(cas) + r"\.html\?BD=([\w]+)", re.IGNORECASE
    )
    for a in soup.find_all("a", href=True):
        m = pattern.search(a["href"])
        if m:
            bd = m.group(1)
            if bd not in bd_numbers:
                bd_numbers.append(bd)

    # Step 2 — scrape each catalog entry
    if bd_numbers:
        entries = []
        for bd in bd_numbers:
            url   = f"https://www.bldpharm.com/products/{cas}.html?BD={bd}"
            entry = _scrape_bld_product(cas, url)
            if entry.get("found"):
                entries.append(entry)
        if entries:
            return {"found": True, "cas": cas, "entries": entries}
        return {"found": False, "message": f"CAS **{cas}** found in search but no pricing data available."}

    # Fallback — try direct product page (single-entry CAS)
    direct_url = f"https://www.bldpharm.com/products/{cas}.html"
    entry = _scrape_bld_product(cas, direct_url)
    if "error" in entry:
        return entry
    if not entry["found"]:
        return {"found": False, "message": f"CAS **{cas}** not found on BLD Pharm."}
    return {"found": True, "cas": cas, "entries": [entry]}


# ── Hyma Synthesis ─────────────────────────────────────────
# QtyA = quantity available to order (ships from Hyderabad warehouse)
# Qty  = total physical stock in Hyderabad warehouse

def scrape_hyma(cas: str) -> dict:
    try:
        r1 = get_session().get(
            "https://hymasynthesis.com/webservices/api/Values/GetChemicalNames",
            params={"Query": cas}, timeout=15,
        )
        r1.raise_for_status()
        chemicals = r1.json()
    except Exception as e:
        return {"error": str(e)}

    if not chemicals:
        return {"found": False, "message": f"CAS **{cas}** not found on Hyma Synthesis."}

    all_rows = []
    for chem in chemicals:
        parts      = [p.strip() for p in chem.get("ChemicalName", "").split("|")]
        if len(parts) < 2: continue
        item_name  = parts[0]
        catalog_no = parts[1]
        group      = parts[3] if len(parts) > 3 else ""

        try:
            r2 = get_session().get(
                "https://hymasynthesis.com/webservices//api/Values/GetWebStockItemMstBasedOnId",
                params={"ItemCode": catalog_no}, timeout=15,
            )
            r2.raise_for_status()
            prod_det = r2.json().get("ProdDet", [])
        except Exception:
            continue

        for item in prod_det:
            pack_size  = item.get("PackSize", "").strip()
            if not pack_size: continue

            price      = item.get("Price", "").strip() or "Inquiry"
            qty_avail  = item.get("QtyA", "0")   # available to dispatch (Hyderabad)
            qty_total  = item.get("Qty",  "0")   # total Hyderabad warehouse stock
            gst        = item.get("GSTTAX", 0)

            try:   avail_f = float(qty_avail)
            except: avail_f = 0.0
            try:   total_f = float(qty_total)
            except: total_f = 0.0

            if avail_f > 0:
                hyd_status = "✅ In Stock"
            elif total_f > 0:
                hyd_status = "📦 Stock Exists"
            else:
                hyd_status = "❌ Out of Stock"

            all_rows.append({
                "Catalog No":              catalog_no,
                "Name":                    item_name,
                "Group":                   group,
                "Pack Size":               pack_size,
                "Price (INR)":             price,
                "Hyd. Avail. to Order":    str(int(avail_f)) if avail_f > 0 else "0",
                "Hyd. Total Stock":        str(total_f).rstrip("0").rstrip(".") if total_f else "0",
                "Hyderabad Status":        hyd_status,
                "GST":                     f"{gst}%",
            })

    if not all_rows:
        return {"found": False, "message": f"CAS **{cas}** found but no pack/price data on Hyma Synthesis."}

    return {"found": True, "cas": cas, "rows": all_rows}


# ── UI ─────────────────────────────────────────────────────
col_input, col_btn = st.columns([4, 1])
with col_input:
    cas_input = st.text_input("CAS Number", placeholder="e.g. 1122-91-4",
                               label_visibility="collapsed")
with col_btn:
    search = st.button("🔍 Search", use_container_width=True, type="primary")

if search and cas_input.strip():
    cas = cas_input.strip()
    col_bld, col_hyma = st.columns(2)

    # ── BLD Pharm ──────────────────────────────────────────
    with col_bld:
        st.subheader("🔵 BLD Pharm")
        with st.spinner("Fetching from bldpharm.com …"):
            bld = scrape_bld(cas)

        if "error" in bld:
            st.error(f"Error: {bld['error']}")
        elif not bld["found"]:
            st.warning(bld["message"])
        else:
            for idx, entry in enumerate(bld["entries"]):
                if idx > 0:
                    st.divider()
                st.markdown(f"**{entry['name']}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("CAS",      entry["cas"])
                c2.metric("Cat. No.", entry["catalog_no"])
                c3.metric("Purity",   entry["purity"])
                if entry.get("lead_time"):
                    st.caption(f"⏱ Lead time for custom/large sizes: **{entry['lead_time']}**")

                st.markdown("**Stock by location (Hyderabad · Delhi · Germany):**")
                st.dataframe(entry["rows"], use_container_width=True, hide_index=True)
                st.caption("🔒 US & Global stock quantities require sign-in on BLD Pharm.")
                st.link_button(
                    f"🔗 View {entry['catalog_no']} on BLD Pharm →",
                    entry["url"],
                )

    # ── Hyma Synthesis ─────────────────────────────────────
    with col_hyma:
        st.subheader("🟣 Hyma Synthesis")
        with st.spinner("Fetching from hymasynthesis.com …"):
            hyma = scrape_hyma(cas)

        if "error" in hyma:
            st.error(f"Error: {hyma['error']}")
        elif not hyma["found"]:
            st.warning(hyma["message"])
        else:
            st.markdown(f"**CAS: {hyma['cas']}**")
            st.caption("Ships from Hyderabad, India · Prices in INR · Stock figures are Hyderabad warehouse")

            # Group by catalog number
            seen_cats = []
            for row in hyma["rows"]:
                cat = row["Catalog No"]
                if cat not in seen_cats:
                    seen_cats.append(cat)

            for idx, cat in enumerate(seen_cats):
                if idx > 0:
                    st.divider()
                cat_rows = [r for r in hyma["rows"] if r["Catalog No"] == cat]
                label = f"**[{cat}]** {cat_rows[0]['Name']}  ·  {cat_rows[0]['Group']}"
                st.markdown(label)
                display_rows = [
                    {
                        "Pack Size":            r["Pack Size"],
                        "Price (INR)":          r["Price (INR)"],
                        "Hyd. Avail. to Order": r["Hyd. Avail. to Order"],
                        "Hyd. Total Stock":     r["Hyd. Total Stock"],
                        "Hyderabad Status":     r["Hyderabad Status"],
                        "GST":                  r["GST"],
                    }
                    for r in cat_rows
                ]
                st.dataframe(display_rows, use_container_width=True, hide_index=True)
                st.link_button(
                    f"🔗 Search {cat} on Hyma →",
                    f"https://hymasynthesis.com/Products?ItemCode={cat}",
                )

elif search:
    st.warning("Please enter a CAS number.")

st.divider()
st.caption("Data fetched live · BLD prices in INR · Hyma prices in INR excl. GST · Hyma stock = Hyderabad warehouse")
