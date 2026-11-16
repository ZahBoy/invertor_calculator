"""Scrape inverter listings + product specs from Ukrainian stores.

Output: raw_products.jsonl (one JSON object per product page).
HTML is cached in ./cache so re-runs don't hit the sites again.
Usage: python scrape.py [store ...]
"""
import hashlib
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).parent
CACHE = HERE / "cache"
OUT = HERE / "raw_products.jsonl"
DELAY = 1.0
MAX_PAGES = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

session = requests.Session()
session.headers["User-Agent"] = UA


def fetch(url):
    """GET with on-disk cache and a polite delay. Returns HTML or None."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if path.exists():
        return path.read_text(encoding="utf-8")
    time.sleep(DELAY)
    resp = session.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"  ! {resp.status_code} {url}")
        return None
    resp.encoding = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else "utf-8"
    path.write_text(resp.text, encoding="utf-8")
    return resp.text


# ---------- spec-table extractors (store specific) ----------

def specs_ecodrive(soup):
    out = {}
    for f in soup.select(".ty-product-feature"):
        label = f.select_one(".ty-product-feature__label")
        value = f.select_one(".ty-product-feature__value")
        if label and value:
            # label may contain a tooltip after the name: keep only the first text chunk
            key = next((t.strip() for t in label.strings if t.strip()), "")
            out[key.rstrip(":")] = value.get_text(" ", strip=True)
    return out


def specs_220volt(soup):
    out = {}
    for a in soup.select(".attribute"):
        title, value = a.select_one(".title"), a.select_one(".value")
        if title and value:
            out[title.get_text(" ", strip=True).rstrip(":")] = value.get_text(" ", strip=True)
    return out


def specs_table(soup):
    out = {}
    for row in soup.select("table tr"):
        cells = row.select("th,td")
        if len(cells) == 2:
            key = cells[0].get_text(" ", strip=True)
            if key and key not in out:
                out[key] = cells[1].get_text(" ", strip=True)
    return out


STORES = {
    "ecodrive.in.ua": {
        "categories": ["https://ecodrive.in.ua/eko-energiya/gibridni-invertori/"],
        "page": lambda base, n: base if n == 1 else f"{base}page-{n}/",
        "links": "a.product-title",
        "specs": specs_ecodrive,
    },
    "220volt.com.ua": {
        "categories": ["https://220volt.com.ua/ua/inverter/op_reshenie_solnecnye-invertory/"],
        "page": lambda base, n: base if n == 1 else f"{base}?page={n}",
        "links": ".catalog-item a.product-title",
        "specs": specs_220volt,
    },
    "use.com.ua": {
        "categories": [
            "https://use.com.ua/ua/g125678477-gibridni-invertori",
            "https://use.com.ua/ua/g125678519-avtonomni-invertori-dlya",
            "https://use.com.ua/ua/g146953842-gibridni-invertori-dlya",
            "https://use.com.ua/ua/g146982390-gibridni-invertori-dlya",
        ],
        "page": lambda base, n: base if n == 1 else f"{base}/page_{n}",
        "links": "a.b-product-gallery__title",
        "specs": specs_table,
    },
}


def product_urls(store, cfg):
    urls = []
    for base in cfg["categories"]:
        for n in range(1, MAX_PAGES + 1):
            html = fetch(cfg["page"](base, n))
            if not html:
                break
            soup = BeautifulSoup(html, "html.parser")
            found = [urljoin(base, a["href"]).split("#")[0] for a in soup.select(cfg["links"])]
            new = [u for u in dict.fromkeys(found) if u not in urls]
            print(f"  {store} page {n}: {len(found)} links, {len(new)} new")
            if not new:
                break
            urls.extend(new)
    return urls


def json_ld_product(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and str(item.get("@type", "")).endswith("Product"):
                return item
    return {}


def parse_product(store, cfg, url, html):
    soup = BeautifulSoup(html, "html.parser")
    ld = json_ld_product(soup)
    offers = ld.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    rating = ld.get("aggregateRating") or {}
    brand = ld.get("brand")
    h1 = soup.select_one("h1")
    return {
        "store": store,
        "url": url,
        "scraped_at": date.today().isoformat(),
        "name": ld.get("name") or (h1.get_text(" ", strip=True) if h1 else ""),
        "sku": ld.get("sku"),
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "price": offers.get("price") or offers.get("lowPrice"),
        "currency": offers.get("priceCurrency"),
        "availability": str(offers.get("availability", "")).rsplit("/", 1)[-1],
        "rating": rating.get("ratingValue"),
        "reviews": rating.get("reviewCount") or rating.get("ratingCount"),
        "specs": cfg["specs"](soup),
    }


def main(selected):
    done = set()
    if OUT.exists():
        done = {json.loads(line)["url"] for line in OUT.open(encoding="utf-8")}
    with OUT.open("a", encoding="utf-8") as out:
        for store, cfg in STORES.items():
            if selected and store not in selected:
                continue
            print(f"== {store}")
            urls = product_urls(store, cfg)
            print(f"  {len(urls)} products")
            for i, url in enumerate(urls, 1):
                if url in done:
                    continue
                html = fetch(url)
                if not html:
                    continue
                rec = parse_product(store, cfg, url, html)
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                done.add(url)
                if i % 20 == 0:
                    print(f"  {i}/{len(urls)}")


if __name__ == "__main__":
    main(sys.argv[1:])
