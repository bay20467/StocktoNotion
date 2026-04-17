#!/usr/bin/env python3
"""
Update 'ราคาปัจจุบัน (ต่อหน่วย)' in the Notion portfolio database.

Price sources:
  - US stocks / ETFs  -> yfinance (ticker as-is, e.g. SPY, MSFT)
  - SET stocks        -> yfinance with .BK suffix (e.g. SCB.BK)
  - Thai mutual funds -> pythainav (e.g. MEGA10-A)

Environment variables required:
  NOTION_TOKEN         Internal integration token (starts with 'secret_' or 'ntn_')
  NOTION_DATABASE_ID   ID of the '📒 ประวัติการซื้อขายทั้งหมด' database
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

import requests

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

try:
    import pythainav
except ImportError:  # pragma: no cover
    pythainav = None


# ---------- Configuration ----------
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")
NOTION_VERSION = os.environ.get("NOTION_VERSION", "2022-06-28")
NOTION_API = "https://api.notion.com/v1"

# Property names in the database (must match exactly)
PROP_TITLE = "ชื่อ / Ticker"
PROP_MARKET = "ตลาด"
PROP_ASSET_TYPE = "ประเภทสินทรัพย์"
PROP_CURRENT_PRICE = "ราคาปัจจุบัน (ต่อหน่วย)"

# Throttle between Notion PATCH calls to stay under 3 req/s
THROTTLE_SECONDS = 0.35


def _headers() -> dict:
    if not NOTION_TOKEN:
        print("❌ NOTION_TOKEN env var is missing", file=sys.stderr)
        sys.exit(2)
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


# ---------- Ticker parsing ----------
def extract_ticker(title: str) -> str:
    """Extract ticker from titles like 'SCB — ธนาคารไทยพาณิชย์'."""
    if not title:
        return ""
    # em dash, en dash, and plain hyphen with spaces
    for sep in (" — ", " – ", " - "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    # fallback: split on the first em/en dash
    for ch in ("—", "–"):
        if ch in title:
            return title.split(ch, 1)[0].strip()
    return title.strip()


# ---------- Price fetchers ----------
def _yf_last_price(ticker: str) -> Optional[float]:
    if yf is None:
        print("  ❌ yfinance not installed", file=sys.stderr)
        return None
    try:
        t = yf.Ticker(ticker)
        # fast_info is quicker and avoids full info scrape
        try:
            fi = t.fast_info
            for key in ("last_price", "lastPrice", "regularMarketPrice"):
                val = getattr(fi, key, None) if hasattr(fi, key) else fi.get(key) if isinstance(fi, dict) else None
                if val:
                    return float(val)
        except Exception:
            pass
        hist = t.history(period="1d", auto_adjust=False)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:
        print(f"  ❌ yfinance error for {ticker}: {exc}", file=sys.stderr)
    return None


def get_us_price(ticker: str) -> Optional[float]:
    return _yf_last_price(ticker)


def get_set_price(ticker: str) -> Optional[float]:
    return _yf_last_price(f"{ticker}.BK")


def get_thai_fund_nav(fund_code: str) -> Optional[float]:
    """Get Thai mutual fund NAV via the pythainav library."""
    if pythainav is None:
        print("  ❌ pythainav not installed", file=sys.stderr)
        return None
    try:
        nav = pythainav.get(fund_code)
        if nav is None:
            return None
        # pythainav returns a Nav dataclass with .value
        return float(nav.value)
    except Exception as exc:
        print(f"  ❌ pythainav error for {fund_code}: {exc}", file=sys.stderr)
        return None


def fetch_price(ticker: str, market: Optional[str], asset_type: Optional[str]) -> Optional[float]:
    """Dispatch to the right source based on market / asset type."""
    if asset_type == "กองทุนรวม":
        return get_thai_fund_nav(ticker)
    if market == "SET":
        return get_set_price(ticker)
    # US markets (NASDAQ, NYSE, NYSE Arca, AMEX, ...)
    return get_us_price(ticker)


# ---------- Notion helpers ----------
def query_database() -> list[dict]:
    """Return all pages in the database, following pagination."""
    pages: list[dict] = []
    url = f"{NOTION_API}/databases/{DATABASE_ID}/query"
    payload: dict = {"page_size": 100}
    headers = _headers()
    while True:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code >= 400:
            print(f"❌ Notion query failed: {resp.status_code} {resp.text}", file=sys.stderr)
            resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return pages


def get_prop_value(page: dict, name: str):
    prop = page.get("properties", {}).get(name)
    if not prop:
        return None
    t = prop.get("type")
    if t == "title":
        parts = prop.get("title", [])
        return "".join(p.get("plain_text", "") for p in parts) if parts else None
    if t == "rich_text":
        parts = prop.get("rich_text", [])
        return "".join(p.get("plain_text", "") for p in parts) if parts else None
    if t == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    if t == "number":
        return prop.get("number")
    return None


def update_price(page_id: str, price: float) -> None:
    url = f"{NOTION_API}/pages/{page_id}"
    payload = {"properties": {PROP_CURRENT_PRICE: {"number": price}}}
    resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    if resp.status_code >= 400:
        raise requests.HTTPError(f"{resp.status_code}: {resp.text}")


# ---------- Main ----------
def main() -> int:
    if not DATABASE_ID:
        print("❌ NOTION_DATABASE_ID env var is missing", file=sys.stderr)
        return 2

    print(f"🔎 Querying Notion database {DATABASE_ID}...")
    pages = query_database()
    print(f"   Found {len(pages)} rows\n")

    # Cache prices per ticker so duplicated rows only hit the API once
    cache: dict[str, Optional[float]] = {}
    updated = 0
    skipped = 0
    failed = 0

    for page in pages:
        title = get_prop_value(page, PROP_TITLE) or ""
        market = get_prop_value(page, PROP_MARKET)
        asset_type = get_prop_value(page, PROP_ASSET_TYPE)
        ticker = extract_ticker(title)
        if not ticker:
            print(f"  ⏭  skip (no ticker): {title!r}")
            skipped += 1
            continue

        key = f"{ticker}|{market}|{asset_type}"
        if key in cache:
            price = cache[key]
        else:
            price = fetch_price(ticker, market, asset_type)
            cache[key] = price

        label = f"{ticker:<12} [{market or '-':<9}][{asset_type or '-'}]"
        if price is None:
            print(f"  ❌ {label} → no price")
            failed += 1
            continue
        try:
            update_price(page["id"], price)
            print(f"  ✅ {label} → {price:.4f}")
            updated += 1
        except requests.HTTPError as exc:
            print(f"  ❌ {label} → update error: {exc}")
            failed += 1
        time.sleep(THROTTLE_SECONDS)

    print(f"\n✨ Done. updated={updated}  skipped={skipped}  failed={failed}")
    # Exit 0 unless nothing updated AND something failed
    return 0 if updated or not failed else 1


if __name__ == "__main__":
    sys.exit(main())
