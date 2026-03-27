# 🧪 CAS Price Lookup

Live pricing & availability checker for **BLD Pharm** and **Hyma Synthesis**.
Enter any CAS number → get pack sizes, INR prices, stock status, and lead time side by side.

---

## 🚀 Deploy to Streamlit (free, no install needed)

1. **Fork or push this repo to your GitHub account**

2. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub

3. Click **"New app"** → select your repo → set:
   - **Main file path:** `app.py`
   - **Branch:** `main`

4. Click **Deploy** — you'll get a shareable link like:
   `https://your-app-name.streamlit.app`

5. **Share that link with your team** — anyone can use it from a browser, no login required.

---

## 💻 Run locally (optional)

```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## What it does

| Field | BLD Pharm | Hyma Synthesis |
|-------|-----------|----------------|
| Prices | ✅ INR | ✅ INR |
| Pack sizes | ✅ | ✅ |
| Stock status | ✅ | ✅ |
| Lead time | ✅ (if listed) | — |
| Catalog No. | ✅ | ✅ |

Data is fetched live each time you search — no cache, always current.
