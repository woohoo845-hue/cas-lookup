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


def _stock_icon(val: str) -> str:
    v = val.lower().strip()
    if "in stock" in v:   return "✅ In Stock"
    if "inquiry" in v:    return "📋 Inquiry"
    if "sign in" in v:    return "🔒 Sign In"
    return val or "—"

def scrape_bld(cas: str) -> dict:
    url = f"https://www.bldpharm.com/products/{cas}.html"
    try:
        resp = get_session().get(url, timeout=20)
    except Exception as e:
        return {"error": str(e)}

    if resp.status_code == 404:
        return {"found": False, "message": f"CAS **{cas}** not found on BLD Pharm."}
    if resp.status_code != 200:
        return {"error": f"BLD Pharm returned HTTP {resp.status_code}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    parts   = (soup.title.string or "").split("|")
    cas_no  = parts[0].strip() if parts else cas
    name    = parts[1].strip() if len(parts) > 1 else "—"

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
        return {"found": False, "message": f"CAS **{cas}** page loaded but no pricing table found."}

    return {
        "found": True, "url": url,
        "cas": cas_no, "name": name,
        "catalog_no": cat_no, "purity": purity,
        "lead_time": lead_time, "rows": rows,
    }


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
            qty_avail  = item.get("QtyA", "0")
            qty_total  = item.get("Qty",  "0")
            gst        = item.get("GSTTAX", 0)
            try:   avail_f = float(qty_avail)
            except: avail_f = 0.0
            try:   total_f = float(qty_total)
            except: total_f = 0.0
            stock_status = "✅ In Stock" if avail_f > 0 else ("📦 Stock Exists" if total_f > 0 else "❌ Out of Stock")
            all_rows.append({
                "Catalog No":      catalog_no,
                "Name":            item_name,
                "Group":           group,
                "Pack Size":       pack_size,
                "Price (INR)":     price,
                "Avail. to Order": str(int(avail_f)) if avail_f > 0 else "0",
                "Total Stock":     str(total_f).rstrip("0").rstrip(".") if total_f else "0",
                "Status":          stock_status,
                "GST":             f"{gst}%",
            })

    if not all_rows:
        return {"found": False, "message": f"CAS **{cas}** found but no pack/price data on Hyma Synthesis."}
    return {"found": True, "cas": cas, "rows": all_rows}


col_input, col_btn = st.columns([4, 1])
with col_input:
    cas_input = st.text_input("CAS Number", placeholder="e.g. 1122-91-4",
                               label_visibility="collapsed")
with col_btn:
    search = st.button("🔍 Search", use_container_width=True, type="primary")

if search and cas_input.strip():
    cas = cas_input.strip()
    col_bld, col_hyma = st.columns(2)
    with col_bld:
        st.subheader("🔵 BLD Pharm")
        with st.spinner("Fetching from bldpharm.com …"):
            bld = scrape_bld(cas)
        if "error" in bld:
            st.error(f"Error: {bld['error']}")
        elif not bld["found"]:
            st.warning(bld["message"])
        else:
            st.markdown(f"**{bld['name']}**")
            c1, c2, c3 = st.columns(3)
            c1.metric("CAS",      bld["cas"])
            c2.metric("Cat. No.", bld["catalog_no"])
            c3.metric("Purity",   bld["purity"])
            if bld.get("lead_time"):
                st.caption(f"⏱ Lead time for custom/large sizes: **{bld['lead_time']}**")
            st.markdown("**Stock by location (Hyderabad · Delhi · Germany):**")
            st.dataframe(bld["rows"], use_container_width=True, hide_index=True)
            st.caption("🔒 US & Global stock quantities require sign-in on BLD Pharm.")
            st.link_button("Open product page →", bld["url"])
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
            st.caption("Ships from Hyderabad, India · Prices in INR + GST")
            seen_cats = []
            for row in hyma["rows"]:
                cat = row["Catalog No"]
                if cat not in seen_cats:
                    seen_cats.append(cat)
            for cat in seen_cats:
                cat_rows = [r for r in hyma["rows"] if r["Catalog No"] == cat]
                label = f"**[{cat}]** {cat_rows[0]['Name']}  ·  {cat_rows[0]['Group']}"
                st.markdown(label)
                display_rows = [{"Pack Size": r["Pack Size"], "Price (INR)": r["Price (INR)"], "Avail. to Order": r["Avail. to Order"], "Total Stock": r["Total Stock"], "Status": r["Status"], "GST": r["GST"]} for r in cat_rows]
                st.dataframe(display_rows, use_container_width=True, hide_index=True)
            st.link_button("Search on Hyma →", "https://hymasynthesis.com/Products")
elif search:
    st.warning("Please enter a CAS number.")

st.divider()
st.caption("Data fetched live · BLD prices in INR · Hyma prices in INR excl. GST")
