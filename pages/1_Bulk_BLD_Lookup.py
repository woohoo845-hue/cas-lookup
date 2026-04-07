import streamlit as st
import base64
import json
import re
import concurrent.futures
from curl_cffi import requests as cffi_requests

st.set_page_config(page_title="BLD Bulk Lookup", page_icon="🧪", layout="wide")
st.title("🧪 BLD Pharm — Bulk Price & Stock Lookup")
st.caption("Paste CAS numbers below (one per line) to fetch live prices and stock from BLDpharm.com")

@st.cache_resource
def get_bld_session():
    session = cffi_requests.Session(impersonate="chrome124")
    session.get("https://www.bldpharm.com/", timeout=15)
    session.cookies.set("bld_country", "India|INR", domain="www.bldpharm.com")
    session.cookies.set("bld_unit",    "INR",       domain="www.bldpharm.com")
    return session

def lookup_cas(session, cas: str) -> dict:
    cas = cas.strip()
    if not cas:
        return None
    params_dict = {"keyword": cas, "pageindex": 1, "country": "India"}
    params_b64  = base64.b64encode(json.dumps(params_dict).encode()).decode()
    xsrf_token  = session.cookies.get("_xsrf", "")
    try:
        resp = session.get(
            "https://www.bldpharm.com/webapi/v1/productlistbykeyword",
            params={"params": params_b64, "_xsrf": xsrf_token},
            timeout=20,
        )
        data = resp.json()
    except Exception as e:
        return {"CAS No.": cas, "Product Name": f"Error: {e}", "Cat. No.": "", "Purity": "", "Stock": "", "Prices": ""}

    results = data.get("result") or data.get("value", {}).get("result", [])
    if not results:
        return {"CAS No.": cas, "Product Name": "Not found on BLD", "Cat. No.": "", "Purity": "", "Stock": "", "Prices": ""}

    item = results[0]
    returned_cas = re.sub(r"<[^>]+>", "", (item.get("p_cas") or "")).strip()
    name = re.sub(r"<[^>]+>", "", item.get("p_name_en") or item.get("p_name") or "").strip()

    # If BLD returned a result but stripped all product data (anti-bot), show as found-but-limited
    if not name and not item.get("p_bd"):
        return {"CAS No.": cas, "Product Name": "Found on BLD (details blocked)", "Cat. No.": "", "Purity": "", "Stock": "Check BLD", "Prices": "—"}

    mismatch_flag = "  ⚠️ Possible mismatch" if returned_cas and returned_cas.lower() != cas.lower() else ""
    in_stock = bool(item.get("p_ishasstock"))
    stock_label = "In Stock" if in_stock else "Inquiry"

    price_list = item.get("price_list") or []
price_parts = []
    for p in price_list:
        size = p.get("pr_size", "")
        newprice = p.get("newprice")
        currency = p.get("pr_currency", "USD")
        symbol = "₹" if currency == "INR" else "$"
        if newprice and str(newprice).strip() not in ("", "undefined", "null", "None"):
            try:
                formatted = f"{symbol}{int(float(newprice)):,}"
            except (ValueError, TypeError):
                formatted = str(newprice)
        else:
            formatted = "Inquiry"
        price_parts.append(f"{size}: {formatted}")
    prices_str = " | ".join(price_parts) if price_parts else "—"

    return {
        "CAS No.": returned_cas or cas,
        "Product Name": name + mismatch_flag,
        "Cat. No.": item.get("p_bd", ""),
        "Purity": item.get("p_purity", ""),
        "Stock": stock_label,
        "Prices": prices_str,
        "_in_stock": in_stock,
    }

cas_input = st.text_area("CAS Numbers (one per line)", placeholder="100-10-7\n123-08-0\n86-51-1", height=180)
run_btn = st.button("🔍 Look Up Prices", type="primary")

if run_btn:
    cas_list = [c.strip() for c in cas_input.splitlines() if c.strip()]
    if not cas_list:
        st.warning("Please paste at least one CAS number.")
    else:
        session = get_bld_session()
        rows = []
        progress = st.progress(0, text="Starting lookups…")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(lookup_cas, session, cas): cas for cas in cas_list}
            done_count = 0
            for future in concurrent.futures.as_completed(futures):
                done_count += 1
                cas_key = futures[future]
                progress.progress(int(done_count / len(cas_list) * 100), text=f"Fetched {done_count}/{len(cas_list)} — {cas_key}")
                result = future.result()
                if result:
                    rows.append(result)
        progress.empty()

        if not rows:
            st.error("No results returned. BLD may be blocking the server IP.")
        else:
            rows.sort(key=lambda r: (0 if r.get("_in_stock") else 1))
            import pandas as pd
            display_cols = ["CAS No.", "Product Name", "Cat. No.", "Purity", "Stock", "Prices"]
            df = pd.DataFrame(rows)[display_cols]
            st.success(f"Found data for {len(df)} product(s).")

            def style_stock(val):
                if "In Stock" in str(val):
                    return "color: green; font-weight: bold;"
                if "Inquiry" in str(val):
                    return "color: red; font-weight: bold;"
                return ""

            st.dataframe(
                df.style.map(style_stock, subset=["Stock"]),
                use_container_width=True,
                hide_index=True,
            )
            csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ Export CSV", data=csv_bytes, file_name="bld_prices.csv", mime="text/csv")


st.divider()
st.caption("Prices in USD (BLD API default) · Sourced live from bldpharm.com")
