import base64
import json
import re
import requests
import streamlit as st
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

st.set_page_config(page_title="CAS Price Lookup", page_icon="🧪", layout="wide")

# Hide Streamlit default UI chrome (menu, footer, header)
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;}
        [data-testid="stDecoration"] {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

st.title("🧪 CAS Number Price Lookup")
st.caption("Live pricing & availability from **BLD Pharm** and **Hyma Synthesis**")


_BLD_BASE  = "https://www.bldpharm.com"
_HYMA_BASE = "https://hymasynthesis.com"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Headers that mimic a real browser document navigation.
# BLD Pharm's server uses these to decide whether to include the full
# stock/pricing table in the HTML (server-side rendered, not loaded via XHR).
_NAV_HEADERS = {
    **_BROWSER_HEADERS,
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def _build_bld_session():
    """Build a BLD session using curl_cffi to impersonate Chrome's TLS fingerprint.
    BLD Pharm uses TLS fingerprinting to detect non-browser clients and strips
    pricing data from the HTML for requests that don't match a real browser's
    TLS signature. curl_cffi impersonates Chrome exactly at the TLS level.
    """
    s = curl_requests.Session(impersonate="chrome124")
    try:
        # Visit homepage first so BLD sets its own cookies.
        s.get(f"{_BLD_BASE}/", timeout=15)
        xsrf = s.cookies.get("_xsrf", "")
        s.get(
            f"{_BLD_BASE}/webapi/v1/setcookiebyprivacy?params=e30%3D&_xsrf={xsrf}",
            timeout=10,
        )
    except Exception:
        pass
    # Override country/currency AFTER homepage so BLD's geo-IP detection
    # cannot overwrite our preference on subsequent API calls.
    # NOTE: curl_cffi's cookies.set(domain=...) doesn't reliably send cookies.
    # We set them without the domain kwarg so they attach to every request.
    s.cookies.set("bld_country", "India|INR")
    s.cookies.set("bld_unit",    "INR")
    return s


def get_bld_session():
    """Returns a cached BLD session."""
    if "_bld_session" not in st.session_state:
        st.session_state["_bld_session"] = _build_bld_session()
    return st.session_state["_bld_session"]


@st.cache_resource
def get_hyma_session():
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)
    return s


# keep a thin alias so non-BLD code still compiles if anything references it
def get_session():
    return get_bld_session()


# ── BLD Pharm ──────────────────────────────────────────────
# Stock table columns (0-indexed):
#   0=Size  1=Price  2=Special Offer  3=US-qty(login)
#   4=Hyderabad  5=Delhi  6=Global  7=Qty

def _strip_html(text: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _stock_icon(val: str) -> str:
    v = _strip_html(val).lower().strip()
    if "in stock" in v:   return "✅ In Stock"
    if "inquiry" in v:    return "📋 Inquiry"
    if "sign in" in v:    return "🔒 Sign In"
    return _strip_html(val) or "—"


def _scrape_bld_product(cas: str, url: str) -> dict:
    """Scrape a single BLD Pharm product page (may include ?BD= param).
    Tries the full stock table first; falls back to any stock indicators
    found anywhere on the page (status badges, availability text, etc.).
    """
    try:
        resp = get_bld_session().get(url, timeout=20)
    except Exception as e:
        return {"error": str(e)}

    if resp.status_code == 404:
        return {"found": False}
    if resp.status_code != 200:
        return {"error": f"BLD Pharm returned HTTP {resp.status_code}"}

    # ── DEBUG: log what we received from BLD ──
    _raw = resp.text
    _debug = {
        "html_len": len(_raw),
        "has_INR": "INR" in _raw,
        "has_tr_stock": "tr_stock" in _raw,
        "has_pro_table": "pro_table" in _raw,
        "has_2153": "2153" in _raw,
        "status": resp.status_code,
        "cookies_sent": dict(get_bld_session().cookies),
    }
    import sys
    print(f"[BLD DEBUG] {url}: {_debug}", file=sys.stderr, flush=True)

    soup = BeautifulSoup(_raw, "html.parser")

    # Store debug info for UI display
    _debug_info = _debug

    parts  = (soup.title.string or "").split("|")
    cas_no = _strip_html(parts[0].strip()) if parts else cas
    name   = _strip_html(parts[1].strip()) if len(parts) > 1 else "—"

    cat_no, purity = "—", "—"
    for el in soup.find_all(string=re.compile(r"Cat\.\s*No\.")):
        txt = el.parent.get_text(" ", strip=True)
        m   = re.search(r"Cat\.\s*No\.:\s*(BD\w+)", txt)
        m2  = re.search(r"(\d+%)", txt)
        if m:  cat_no = _strip_html(m.group(1))
        if m2: purity = m2.group(1)
        if cat_no != "—": break

    lt = re.search(r"\d+[-–]\d+\s*weeks?", resp.text, re.IGNORECASE)
    lead_time = lt.group(0) if lt else None

    # ── Primary: full stock table ──
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
            "Global":      _stock_icon(tds[6]),
        })

    if rows:
        return {
            "found": True, "url": url,
            "cas": cas_no, "name": name,
            "catalog_no": cat_no, "purity": purity,
            "lead_time": lead_time, "rows": rows,
            "_debug_info": _debug_info,
        }

    # ── Fallback: look for stock/availability text signals on the page ──
    # Only look for clear "in stock" / "out of stock" text near city names.
    # Do NOT try to scrape arbitrary tables — they contain unrelated data
    # (product IDs, related products, etc.) that produces false positives.
    page_text = resp.text.lower()
    stock_signals = {}

    for city_kw, city_label in [
        ("hyderabad", "Hyderabad"), ("delhi", "Delhi"),
        ("global", "Global"),
    ]:
        pattern = rf'{city_kw}\s*[:\-]?\s*(in\s*stock|out\s*of\s*stock|available|inquiry)'
        m = re.search(pattern, page_text, re.IGNORECASE)
        if m:
            stock_signals[city_label] = _stock_icon(m.group(1))

    if stock_signals:
        rows.append({
            "Size": "—",
            "Price (INR)": "See BLD →",
            "Hyderabad": stock_signals.get("Hyderabad", "—"),
            "Delhi": stock_signals.get("Delhi", "—"),
            "Global": stock_signals.get("Global", "—"),
        })

    # Always return partial data (name, cat_no, purity) even if no stock rows.
    # The caller can use this to fill in the fallback entry and try the
    # productdetail API with the extracted BD number.
    return {
        "found": bool(rows),
        "url": url,
        "cas": cas_no, "name": name,
        "catalog_no": cat_no, "purity": purity,
        "lead_time": lead_time, "rows": rows,
        "_debug_info": _debug_info,
    }


_BLD_API = "https://www.bldpharm.com/webapi/v1/productlistbykeyword"


def scrape_bld(cas: str) -> dict:
    """
    1. Query BLD's JSON API to discover all catalog entries for a CAS number.
       (The search results page is JS-rendered and cannot be parsed server-side;
        the JSON API is the canonical way to enumerate BD catalog numbers.)
    2. For each catalog entry, scrape the HTML product page for
       city-level stock (Hyderabad / Delhi / Global).
    3. Fall back to API price data if the HTML page yields no table.
    """
    session = get_bld_session()
    xsrf = session.cookies.get("_xsrf", "")

    # Try both country="" (global) and country="India" — some products
    # only appear in one or the other.
    results = []
    for country in ("", "India"):
        params_b64 = base64.b64encode(
            json.dumps({"keyword": cas, "pageindex": 1, "country": country}).encode()
        ).decode()
        try:
            r = session.get(
                f"{_BLD_API}?params={params_b64}&_xsrf={xsrf}", timeout=20
            )
            r.raise_for_status()
            api_data = r.json()
        except Exception as e:
            return {"error": str(e)}

        for item in api_data.get("value", {}).get("result", []):
            bd = item.get("p_bd", "")
            # deduplicate by BD number (or by s_url for BD-less entries)
            if not any(
                (bd and bd == e.get("p_bd")) or
                (not bd and item.get("s_url") == e.get("s_url"))
                for e in results
            ):
                results.append(item)
        if results:
            break                            # good enough — skip next country

    if not results:
        return {"found": False, "message": f"CAS **{cas}** not found on BLD Pharm."}

    entries = []
    _first_debug = {}
    for product in results:
        bd    = _strip_html(product.get("p_bd", ""))
        s_url = _strip_html(product.get("s_url", f"{cas}.html"))
        # Only append ?BD= when a catalog number is actually present;
        # some CAS entries have a direct page with no BD parameter.
        url = (
            f"https://www.bldpharm.com/products/{s_url}?BD={bd}"
            if bd else
            f"https://www.bldpharm.com/products/{s_url}"
        )

        # Try to get city-level stock from HTML product page.
        # _scrape_bld_product always returns partial data (name, cat_no, purity)
        # even if the stock table isn't available (geo-IP restriction).
        html_data = _scrape_bld_product(cas, url)
        if not _first_debug:
            _first_debug = html_data.get("_debug_info", {})
        if html_data.get("found") and html_data.get("rows"):
            entries.append(html_data)
            continue

        # Use the HTML-extracted BD number if the API didn't provide one
        html_bd = html_data.get("catalog_no", "—")
        effective_bd = bd or (html_bd if html_bd != "—" else "")

        # Fallback: build table from API price_list (no city breakdown)
        price_list = product.get("price_list", [])
        if not price_list and effective_bd:
            # Try the productdetail API with the BD number
            try:
                detail_b64 = base64.b64encode(
                    json.dumps({"bd": effective_bd}).encode()
                ).decode()
                dr = session.get(
                    f"{_BLD_BASE}/webapi/v1/productdetail?params={detail_b64}&_xsrf={xsrf}",
                    timeout=15,
                )
                if dr.status_code == 200:
                    det = dr.json().get("value", {})
                    price_list = det.get("price_list", [])
            except Exception:
                pass

        if not price_list:
            # Use partial HTML data for display (name, cat_no, purity)
            p_name = html_data.get("name", "—")
            if p_name == "—":
                p_name = _strip_html(product.get("p_name", product.get("p_name_cn", "—")))
            p_purity = html_data.get("purity", "—")
            if p_purity == "—":
                p_purity = _strip_html(product.get("p_purity", "—"))
            stock_n = product.get("stock_number", 0) or 0
            stock_status = "✅ In Stock" if stock_n > 0 else "—"
            entries.append({
                "found": True, "url": url,
                "cas": cas,
                "name": p_name,
                "catalog_no": effective_bd or "—",
                "purity": p_purity if p_purity else "—",
                "lead_time": html_data.get("lead_time"),
                "rows": [{"Size": "—", "Price (INR)": "Visit BLD →",
                          "Hyderabad": stock_status, "Delhi": "—", "Global": "—"}],
                "_link_only": True,
            })
            continue

        rows = []
        for p in price_list:
            stock_n = p.get("stock_number", 0) or 0
            rows.append({
                "Size":        p.get("pr_size", "—"),
                "Price (INR)": f"INR {p['newprice']}" if p.get("newprice") else "Inquiry",
                "Hyderabad":   "✅ In Stock" if stock_n > 0 else "❌ Out of Stock",
                "Delhi":       "—",
                "Global":      "—",
            })
        p_name = html_data.get("name", "—")
        if p_name == "—":
            p_name = _strip_html(product.get("p_name", product.get("p_name_cn", "—")))
        entries.append({
            "found": True, "url": url,
            "cas": cas,
            "name": p_name,
            "catalog_no": effective_bd or bd,
            "purity": html_data.get("purity", _strip_html(product.get("p_purity", "—"))),
            "lead_time": html_data.get("lead_time"), "rows": rows,
        })

    if not entries:
        return {"found": False, "message": f"CAS **{cas}** found but no pricing data available on BLD Pharm.", "_debug": _first_debug}
    return {"found": True, "cas": cas, "entries": entries, "_debug": _first_debug}


# ── Hyma Synthesis ─────────────────────────────────────────
# QtyA = quantity available to order (ships from Hyderabad warehouse)
# Qty  = total physical stock in Hyderabad warehouse

def scrape_hyma(cas: str) -> dict:
    try:
        r1 = get_hyma_session().get(
            f"{_HYMA_BASE}/webservices/api/Values/GetChemicalNames",
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
            r2 = get_hyma_session().get(
                f"{_HYMA_BASE}/webservices/api/Values/GetWebStockItemMstBasedOnId",
                params={"ItemCode": catalog_no}, timeout=15,
            )
            r2.raise_for_status()
            prod_det = r2.json().get("ProdDet", [])
        except Exception:
            continue

        for item in prod_det:
            pack_size  = item.get("PackSize", "").strip()
            if not pack_size: continue
            if "bulk" in pack_size.lower(): continue

            price    = item.get("Price", "").strip() or "Inquiry"
            qty_hyd  = item.get("Qty", "0")   # Qty = HYD(Q) — Hyderabad stock

            try:   hyd_f = float(qty_hyd)
            except: hyd_f = 0.0

            stock_num = int(hyd_f)
            hyd_stock = f"{stock_num} ✅" if stock_num > 0 else "0 ❌"

            all_rows.append({
                "Catalog No":   catalog_no,
                "Name":         item_name,
                "Group":        group,
                "Pack Size":    pack_size,
                "Price (INR)":  price,
                "Hyd. Stock":   hyd_stock,
            })

    if not all_rows:
        return {"found": False, "message": f"CAS **{cas}** found but no pack/price data on Hyma Synthesis."}

    return {"found": True, "cas": cas, "rows": all_rows}


# ── UI ─────────────────────────────────────────────────────
with st.form("search_form"):
    col_input, col_btn = st.columns([4, 1])
    with col_input:
        cas_input = st.text_input("CAS Number", placeholder="e.g. 1122-91-4",
                                   label_visibility="collapsed")
    with col_btn:
        search = st.form_submit_button("🔍 Search", use_container_width=True, type="primary")

if search and cas_input.strip():
    cas = cas_input.strip()
    col_bld, col_hyma = st.columns(2)

    # ── BLD Pharm ──────────────────────────────────────────
    with col_bld:
        st.subheader("🔵 BLD Pharm")
        with st.spinner("Fetching from bldpharm.com …"):
            bld = scrape_bld(cas)

        # ── Temporary debug info ──
        with st.expander("🔧 BLD Debug"):
            st.json(bld.get("_debug", {}))

        if "error" in bld:
            st.error(f"Error: {bld['error']}")
        elif not bld["found"]:
            st.warning(bld["message"])
        else:
            for idx, entry in enumerate(bld["entries"]):
                if idx > 0:
                    st.divider()
                # Build header — only include non-dash fields
                hdr_parts = [f"**{entry['name']}**"]
                if entry.get("catalog_no") and entry["catalog_no"] != "—":
                    hdr_parts.append(f"`{entry['catalog_no']}`")
                if entry.get("purity") and entry["purity"] != "—":
                    hdr_parts.append(entry["purity"])
                st.markdown(" &nbsp;·&nbsp; ".join(hdr_parts), unsafe_allow_html=True)

                if entry.get("lead_time"):
                    st.caption(f"⏱ Lead time: **{entry['lead_time']}**")

                if entry.get("_link_only"):
                    # Pricing not accessible via API — don't show an all-dashes table
                    st.caption("_Detailed pricing not available via API. Check BLD website for current prices._")
                elif entry.get("rows"):
                    display_rows = [
                        {
                            "Size":        r["Size"],
                            "Price (INR)": r["Price (INR)"],
                            "Hyderabad":   r["Hyderabad"],
                            "Delhi":       r.get("Delhi", "—"),
                            "Global":      r.get("Global", "—"),
                        }
                        for r in entry["rows"]
                    ]
                    st.dataframe(display_rows, use_container_width=True, hide_index=True)
                st.link_button("🔗 View on BLD Pharm →", entry["url"], use_container_width=True)

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
            # Group by catalog number, sort so Speciality Chemicals comes first
            seen_cats = []
            for row in hyma["rows"]:
                cat = row["Catalog No"]
                if cat not in seen_cats:
                    seen_cats.append(cat)

            def _group_priority(cat):
                grp = next((r["Group"] for r in hyma["rows"] if r["Catalog No"] == cat), "")
                grp_l = grp.lower()
                if "speciality" in grp_l or "specialty" in grp_l:
                    return 0
                if "biologic" in grp_l:
                    return 2
                return 1

            seen_cats.sort(key=_group_priority)

            for idx, cat in enumerate(seen_cats):
                if idx > 0:
                    st.divider()
                cat_rows = [r for r in hyma["rows"] if r["Catalog No"] == cat]
                grp = cat_rows[0]["Group"]
                is_bio = "biologic" in grp.lower()
                txt_color = "#cc0000" if is_bio else "inherit"
                hdr_col, btn_col = st.columns([3, 2])
                with hdr_col:
                    st.markdown(
                        f'<span style="color:{txt_color}; font-weight:600;">'
                        f'<span style="background:{txt_color if is_bio else "#e8e8e8"}; color:{"white" if is_bio else "#333"}; '
                        f'border-radius:4px; padding:1px 6px; font-size:12px; font-weight:700; margin-right:6px;">{cat}</span>'
                        f'{cat_rows[0]["Name"]}</span>'
                        f'<br><span style="color:#888; font-size:12px; font-style:italic;">{grp}</span>',
                        unsafe_allow_html=True,
                    )
                with btn_col:
                    st.components.v1.html(f"""
                        <button onclick="
                            navigator.clipboard.writeText('{cat}');
                            window.open('https://hymasynthesis.com/Products', '_blank');
                        " style="
                            background:#7B2FBE; color:white; border:none; border-radius:6px;
                            padding:7px 14px; font-size:13px; font-weight:bold;
                            cursor:pointer; white-space:nowrap; width:100%;
                        ">🔗 View {cat} on Hyma</button>
                    """, height=40)
                display_rows = [
                    {
                        "Pack Size":    r["Pack Size"],
                        "Price (INR)":  r["Price (INR)"],
                        "Hyd. Stock":   r["Hyd. Stock"],
                    }
                    for r in cat_rows
                ]
                if is_bio:
                    rows_html = "".join(
                        f"<tr><td>{r['Pack Size']}</td><td>{r['Price (INR)']}</td><td>{r['Hyd. Stock']}</td></tr>"
                        for r in display_rows
                    )
                    st.markdown(f"""
                        <table style="width:100%; border-collapse:collapse; color:#cc0000; font-size:14px; margin-top:4px;">
                          <thead><tr style="border-bottom:2px solid #cc0000;">
                            <th style="text-align:left; padding:4px 8px;">Pack Size</th>
                            <th style="text-align:left; padding:4px 8px;">Price (INR)</th>
                            <th style="text-align:left; padding:4px 8px;">Hyd. Stock</th>
                          </tr></thead>
                          <tbody>{rows_html}</tbody>
                        </table>
                    """, unsafe_allow_html=True)
                else:
                    st.dataframe(display_rows, use_container_width=True, hide_index=True)

elif search:
    st.warning("Please enter a CAS number.")

st.caption("Data fetched live · BLD & Hyma prices in INR · Hyma stock = Hyderabad warehouse · POR = Price on Request")
