import base64
import json
import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="CAS Price Lookup", page_icon="🧪", layout="wide")

st.title("🧪 CAS Number Price Lookup")
st.caption("Live pricing & availability from **BLD Pharm** and **Hyma Synthesis**")

# ── Sidebar: BLD Authentication ───────────────────────────
with st.sidebar:
    st.header("🔑 BLD Pharm Login")
    st.caption(
        "Paste your BLD session cookies to get full stock & pricing data. "
        "Without cookies, some products show limited info."
    )
    bld_cookies_raw = st.text_area(
        "BLD Cookies",
        placeholder='Paste cookie string from browser DevTools\ne.g. _xsrf=abc123; session_id=xyz789; ...',
        height=100,
        key="_bld_cookies",
        help=(
            "How to get your cookies:\n"
            "1. Log in to bldpharm.com in Chrome\n"
            "2. Press F12 → Application tab → Cookies → bldpharm.com\n"
            "3. Copy the cookie values, or:\n"
            "   - Go to Network tab, click any request\n"
            "   - Find 'Cookie:' in Request Headers\n"
            "   - Copy the full value after 'Cookie: '"
        ),
    )
    if bld_cookies_raw.strip():
        st.success("🔓 Cookies provided — will use authenticated session.")
    else:
        st.info("🔒 No cookies — BLD stock data may be limited from cloud servers.")
    st.divider()
    st.caption("Cookies are **not stored** — they only live in your current browser session.")


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


def _parse_cookie_string(raw: str) -> dict:
    """Parse a 'key=value; key2=value2' cookie header into a dict."""
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _build_bld_session(cookie_str: str = ""):
    """
    Build a requests Session for BLD Pharm.
    Uses user-supplied cookies if provided, otherwise anonymous session.
    """
    s = requests.Session()
    s.headers.update(_BROWSER_HEADERS)

    # 1) Try user-supplied cookies
    if cookie_str.strip():
        for k, v in _parse_cookie_string(cookie_str).items():
            s.cookies.set(k, v, domain="www.bldpharm.com")
        try:
            s.get(f"{_BLD_BASE}/", timeout=15)
        except Exception:
            pass
        return s

    # 2) Anonymous session (default)
    try:
        s.get(f"{_BLD_BASE}/", timeout=15)
        xsrf = s.cookies.get("_xsrf", "")
        s.get(
            f"{_BLD_BASE}/webapi/v1/setcookiebyprivacy?params=e30%3D&_xsrf={xsrf}",
            timeout=10,
        )
    except Exception:
        pass
    return s


def get_bld_session():
    """
    Returns a BLD session. Uses sidebar cookies if provided,
    otherwise falls back to an anonymous session.
    """
    cookie_str = st.session_state.get("_bld_cookies", "")
    cache_key = cookie_str
    if (
        "_bld_session" not in st.session_state
        or st.session_state.get("_bld_cache_key") != cache_key
    ):
        st.session_state["_bld_session"] = _build_bld_session(cookie_str)
        st.session_state["_bld_cache_key"] = cache_key
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
#   4=Hyderabad  5=Delhi  6=Germany  7=Global(login)

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

    soup = BeautifulSoup(resp.text, "html.parser")

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
            "Germany":     _stock_icon(tds[6]),
        })

    if rows:
        return {
            "found": True, "url": url,
            "cas": cas_no, "name": name,
            "catalog_no": cat_no, "purity": purity,
            "lead_time": lead_time, "rows": rows,
        }

    # ── Fallback: look for stock/availability text signals on the page ──
    # Only look for clear "in stock" / "out of stock" text near city names.
    # Do NOT try to scrape arbitrary tables — they contain unrelated data
    # (product IDs, related products, etc.) that produces false positives.
    page_text = resp.text.lower()
    stock_signals = {}

    for city_kw, city_label in [
        ("hyderabad", "Hyderabad"), ("delhi", "Delhi"),
        ("germany", "Germany"),
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
            "Germany": stock_signals.get("Germany", "—"),
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
    }


_BLD_API = "https://www.bldpharm.com/webapi/v1/productlistbykeyword"


def scrape_bld(cas: str) -> dict:
    """
    1. Query BLD's JSON API to discover all catalog entries for a CAS number.
       (The search results page is JS-rendered and cannot be parsed server-side;
        the JSON API is the canonical way to enumerate BD catalog numbers.)
    2. For each catalog entry, scrape the HTML product page for
       city-level stock (Hyderabad / Delhi / Germany).
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
                          "Hyderabad": stock_status, "Delhi": "—", "Germany": "—"}],
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
                "Germany":     "—",
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
        return {"found": False, "message": f"CAS **{cas}** found but no pricing data available on BLD Pharm."}
    return {"found": True, "cas": cas, "entries": entries}


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
        auth_mode = "🔓 authenticated" if st.session_state.get("_bld_cookies", "").strip() else "🔒 anonymous"
        with st.spinner(f"Fetching from bldpharm.com ({auth_mode}) …"):
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
                        "Hyd. Total Stock":     r["Hyd. Total Stock"],
                        "Hyderabad Status":     r["Hyderabad Status"],
                        "GST":                  r["GST"],
                    }
                    for r in cat_rows
                ]
                st.dataframe(display_rows, use_container_width=True, hide_index=True)
                # Hyma's Angular SPA ignores URL query params — we can't
                # deep-link to a specific product. Provide copyable catalog
                # number + CAS so the user can paste into Hyma's search box.
                link_col, copy_col = st.columns([1, 1])
                with link_col:
                    st.link_button(
                        f"🔗 Open Hyma Products →",
                        f"{_HYMA_BASE}/Products",
                    )
                with copy_col:
                    st.code(cat, language=None)
                st.caption(f"💡 Copy **{cat}** or **{cas}** and paste into the search box on Hyma's site.")

elif search:
    st.warning("Please enter a CAS number.")

st.divider()
st.caption("Data fetched live · BLD prices in INR · Hyma prices in INR excl. GST · Hyma stock = Hyderabad warehouse")
