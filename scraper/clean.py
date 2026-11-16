"""Normalize raw_products.jsonl (+ manual CSVs) into ../data/*.csv.

Outputs:
  data/invertumns
  data/Invertor_24V.csv     - exactly the demo calculator's 4-column format (24 V)
  data/Invertor_48Vers.csv        - every usable offer, all normalized col.csv     - same for 48 V
  scraper/rejected.csv      - rows dropped and why (for manual review)
"""
import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent / "data"

COLUMNS = [
    "brand", "name", "power_w", "battery_v", "battery_v_source", "phases", "type",
    "price_uah", "in_stock", "warranty_months", "parallel", "peak_power_w",
    "pv_max_w", "efficiency_pct", "rating", "reviews", "store", "url", "scraped_at",
]
MVP_HEADER = ["Марка інвертора", "Потужність", "Ціна", "Джерело (сайт)"]


# ---------- small parsers ----------

def first_spec(specs, *keys):
    """Value of the first key present (exact match, then case-insensitive substring)."""
    for key in keys:
        if specs.get(key):
            return specs[key]
    lowered = {k.lower(): v for k, v in specs.items()}
    for key in keys:
        for k, v in lowered.items():
            if key.lower() in k and v:
                return v
    return None


def numbers(text):
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text or "")]


def to_watts(text, default_unit="w"):
    """'3680 Вт' -> 3680, '5 кВт' -> 5000, '10 000 Вт' -> 10000."""
    if not text:
        return None
    t = text.replace(" ", " ").lower()
    m = re.search(r"(\d+(?:[ .,]\d{3})*(?:[.,]\d+)?)\s*(квт|kw|к?ва|kva|вт|w)?", t)
    if not m:
        return None
    raw, unit = m.group(1), m.group(2) or default_unit
    value = float(re.sub(r"[ ](?=\d{3})", "", raw).replace(",", "."))
    if unit in ("квт", "kw", "ква", "kva") or (unit == "kw_default"):
        value *= 1000
    return int(round(value)) if value > 0 else None


def battery_class(text):
    """Map a battery-voltage spec to 12/24/48/HV; None if unparseable or nonsense."""
    vals = [v for v in numbers(text) if v > 0]
    if not vals:
        return None
    if any(v in (220, 230) for v in vals):  # seller typed AC voltage into the battery field
        return None
    hi = max(vals)
    if hi >= 100:
        return "HV"
    lo = min(vals)
    if 40 <= lo <= 52 or 46 <= hi <= 64:
        return "48"
    if len(set(vals)) > 1 and {12, 24} >= set(vals):
        return None  # '12/24' - ambiguous
    for v in (12, 24, 48):
        if abs(lo - v) < 1:
            return str(v)
    return None


def battery_from_name(name):
    m = re.search(r"(?<!\d)(12|24|48)\s*(?:V|В|вольт|volt)(?![a-zа-яі])", name, re.I)
    if m:
        return m.group(1)
    # known high-voltage-battery families: Fronius GEN24, EcoFlow PowerOcean, Deye *HP3
    if re.search(r"\bHV\b|1[256]0\s*[-–]\s*[6-9]\d\d\s*В|GEN24|Power ?Ocean|HP3", name, re.I):
        return "HV"
    return None


def phases_of(text, name):
    t = (text or "").lower()
    if "трифаз" in t or "3 фаз" in t or t.strip() == "3":
        return 3
    if "однофаз" in t or "1 фаз" in t or t.strip() == "1":
        return 1
    n = name.lower()
    if re.search(r"3\s*фаз|трифаз|lp3|-3p|tl3|three", n):
        return 3
    return None


def type_of(text, name, specs):
    t = f"{text or ''} {name}".lower()
    n = name.lower()
    if re.search(r"мікроінвертор|microinverter", n):
        return "micro_inverter"
    if re.search(r"модуль|mppt контролер|^контролер", t):
        return "accessory"
    if re.search(r"зарядна станція|портативн|power ?station|павербанк", n):
        return "power_station"
    if n.startswith("комплект") or "combo" in n or "bundle" in n:
        return "kit"
    if "гібрид" in t or "гибрид" in t or "hybrid" in t:
        return "hybrid"
    if "автоном" in t or "off-grid" in t:
        return "off_grid"
    if "мереж" in t or "on-grid" in t:
        return "grid_tie"
    if "резервного живлення" in t:
        return "backup_system"
    return "inverter"


def months_of(text):
    if not text:
        return None
    vals = numbers(text)
    if not vals:
        return None
    v = vals[0]
    return int(v * 12) if re.search(r"рок|year", text, re.I) else int(v)


def parallel_of(specs):
    text = first_spec(specs, "паралельн", "параллельн")
    if not text:
        return None
    if text.lower().startswith(("так", "да", "yes")):
        n = numbers(text)
        return int(n[0]) if n else "yes"
    return "no" if text.lower().startswith(("ні", "нет", "no")) else None


KNOWN_BRANDS = [
    "Deye", "Must", "Luxpower", "PowMr", "Anern", "Anenji", "Y&H", "Victron", "Fronius", "Huawei",
    "Growatt", "Solis", "SRNE", "Felicity", "EcoFlow", "Livoltek", "Sungrow", "GoodWe", "TommaTech",
    "Orbus", "BAISON", "Afore", "Ritar", "SUMRY", "Europower", "NetPRO", "Qoltec", "Easun", "Sofar",
    "Datouboss", "Daxtromn", "Altek", "Jsdsolar", "Agent", "Hypontech", "LogicPower", "JYsupsys",
    "Voltronic", "Sigenergy", "Dyness", "Must Power",
]
JUNK_BRANDS = {"agm", "gel", "solar", "lifepo4", "інвертор", "інвертори", "brazzers", ""}
ALIASES = {"powermr": "PowMr"}  # antpower spells PowMr as PowerMR


def brand_of(name, raw):
    """Prefer a known brand found in the title; fall back to the store's brand field."""
    for alias, canonical in ALIASES.items():
        if alias in name.lower():
            return canonical
    for b in KNOWN_BRANDS:
        if re.search(rf"(?<![a-zа-я]){re.escape(b)}(?![a-zа-я])", name, re.I):
            return b
    raw = re.sub(r"^(Інвертори|Інвертор|ТМ)\s+", "", str(raw or "")).split(" Всі товари")[0].strip()
    raw = re.sub(r"\s*\(.*\)$", "", raw)
    return "" if raw.lower() in JUNK_BRANDS else raw


# ---------- per-record normalization ----------

def normalize(rec):
    s, name = rec["specs"], rec["name"].strip()
    store = rec["store"]
    if store == "220volt.com.ua":
        power = to_watts(first_spec(s, "Номінальна потужність, кВт"), "kw_default")
        peak = to_watts(first_spec(s, "Максимальна короткочасна потужність, кВт"), "kw_default")
    else:
        power = to_watts(first_spec(s, "Номінальна потужність, Вт", "Номінальна потужність Вт",
                                    "Номінальна потужність"))
        peak = to_watts(first_spec(s, "Пікова потужність", "Допустима пікова потужність",
                                   "Максимальна потужність"))
    name_power = to_watts((re.search(r"\d+(?:[.,]\d+)?\s*(?:кВт|kW|Вт|W)\b", name, re.I) or [None])[0])
    # sellers' typos ('5' meaning 5 kW, '550' meaning 5500 W): trust the title when they disagree a lot
    if not power or (name_power and not 0.5 <= power / name_power <= 2):
        power = name_power or power

    bat_spec = first_spec(s, "Вхідна напруга батареї, В", "Напруга акумулятора, В",
                          "Напруга акумулятора", "Напруга АКБ")
    battery, source = battery_class(bat_spec), "specs"
    if battery is None:
        battery, source = battery_from_name(name), "name"
    kind = type_of(first_spec(s, "Тип пристрою", "Тип архітектури", "Тип системи", "Тип"), name, s)
    if battery is None and kind == "grid_tie":
        battery, source = "none", "type"  # grid-tie: no battery input at all
    if battery is None:
        source = ""

    brand = brand_of(name, rec.get("brand") or first_spec(s, "Бренд", "Виробник"))

    price = rec.get("price")
    return {
        "brand": brand,
        "name": name,
        "power_w": power,
        "battery_v": battery,
        "battery_v_source": source,
        "phases": phases_of(first_spec(s, "Фази", "Кількість фаз / Вихідна напруга", "Кількість фаз"), name),
        "type": kind,
        "price_uah": int(float(price)) if price else None,
        "in_stock": {"InStock": "yes", "OutOfStock": "no", "PreOrder": "preorder"}.get(rec["availability"], ""),
        "warranty_months": months_of(first_spec(s, "Гарантія від виробника", "Гарантія, міс",
                                                "Гарантійний термін")),
        "parallel": parallel_of(s),
        "peak_power_w": peak,
        "pv_max_w": to_watts(first_spec(s, "Максимальная потужність панелей, Вт",
                                        "Максимальна потужність панелей")),
        "efficiency_pct": (max(numbers(first_spec(s, "Ефективність перетворення", "ККД"))) or None)
        if numbers(first_spec(s, "Ефективність перетворення", "ККД")) else None,
        "rating": rec.get("rating"),
        "reviews": rec.get("reviews"),
        "store": store,
        "url": rec["url"],
        "scraped_at": rec["scraped_at"],
        "_used": first_spec(s, "Стан") not in (None, "Новий"),
    }


def manual_rows():
    """Alexa's hand-collected CSVs (stores we don't scrape: antpower, solar-markets, rozetka)."""
    out = []
    for volts in ("24", "48"):
        with open(HERE / "manual" / f"Invertor_{volts}V.csv", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if not r.get("Марка інвертора"):
                    continue
                store = r["Джерело (сайт)"].strip()
                if store in ("ecodrive.in.ua", "220volt.com.ua", "use.com.ua"):
                    continue  # scraped fresher
                name = r["Марка інвертора"].strip()
                out.append({
                    "brand": brand_of(name, name.split()[0]), "name": name,
                    "power_w": int(numbers(r["Потужність"])[0]),
                    "battery_v": volts, "battery_v_source": "manual",
                    "phases": phases_of(None, name), "type": "inverter",
                    "price_uah": int(re.sub(r"\D", "", r["Ціна"])),
                    "in_stock": "", "warranty_months": None, "parallel": None,
                    "peak_power_w": None, "pv_max_w": None, "efficiency_pct": None,
                    "rating": None, "reviews": None, "store": store, "url": "",
                    "scraped_at": "2026-11-13", "_used": False,
                })
    return out


def reject_reason(row):
    if row["_used"]:
        return "used"
    if not row["price_uah"]:
        return "no price"
    if row["type"] in ("power_station", "accessory", "kit"):
        return row["type"]
    if not row["power_w"]:
        return "no power"
    return None


def mvp_name(row):
    """Drop the generic 'Гібридний інвертор' prefix and make sure the brand is visible."""
    # strip leading descriptor words: "Гібридний інвертор", "Інвертор гібридний мережевий", "Сонячний гібридний інвертор"
    name = re.sub(r"^((гібридн|автономн|мережев|сонячн|інвертор)\w*\s+)+", "", row["name"], flags=re.I)
    name = re.sub(r"\s*\(безперебійник[^)]*\)?$", "", name)  # ecodrive's SEO tail
    name = re.split(r",\s", name)[0]  # use.com.ua titles are comma-separated keywords; "2,7KW" stays
    name = name.replace(";", " ").replace('"', "").strip()
    brand = row["brand"] or "Без бренду"
    known = [brand.lower()] + [a for a, c in ALIASES.items() if c == brand]
    if not any(k in name.lower() for k in known):
        name = f"{brand} — {name}"
    if row["phases"] == 3 and "фаз" not in name.lower():
        name += " (3 фази)"  # same marking as the hand-made reference files
    return name


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def main():
    raw = [json.loads(line) for line in open(HERE / "raw_products.jsonl", encoding="utf-8")]
    rows = [normalize(r) for r in raw] + manual_rows()

    kept, rejected = [], []
    for row in rows:
        reason = reject_reason(row)
        (rejected if reason else kept).append((reason, row))
    kept = [r for _, r in kept]
    kept.sort(key=lambda r: (str(r["battery_v"]), r["power_w"], r["price_uah"]))

    write_csv(DATA / "inverters.csv", COLUMNS, [[r[c] if r[c] is not None else "" for c in COLUMNS] for r in kept])
    write_csv(HERE / "rejected.csv", ["reason", "name", "store", "url"],
              [[why, r["name"], r["store"], r["url"]] for why, r in rejected])

    for volts in ("24", "48"):
        mvp = [r for r in kept if r["battery_v"] == volts
               and r["type"] in ("hybrid", "off_grid", "inverter")]
        write_csv(DATA / f"Invertor_{volts}V.csv", MVP_HEADER,
                  [[mvp_name(r), f"{r['power_w']} Вт ({r['power_w'] / 1000:g} кВт)",
                    f"{r['price_uah']:,} грн".replace(",", " "), r["store"]] for r in mvp])
        print(f"Invertor_{volts}V.csv: {len(mvp)} rows")
    print(f"inverters.csv: {len(kept)} rows, rejected: {len(rejected)}")


if __name__ == "__main__":
    main()
