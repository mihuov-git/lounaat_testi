from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LunchBot/1.0; +https://github.com/)"}
DAY_NAMES = {0: "maanantai", 1: "tiistai", 2: "keskiviikko", 3: "torstai", 4: "perjantai", 5: "lauantai", 6: "sunnuntai"}

SOURCES = [
    {"key": "grillit", "name": "Grill it! Marina", "subtitle": "Raflaamo", "url": "https://www.raflaamo.fi/fi/ravintola/turku/grill-it-marina-turku/menu/lounas"},
    {"key": "viides", "name": "Viides Näyttämö", "subtitle": "Kulttuuriranta", "url": "https://www.viidesnayttamo.fi/?page_id=73"},
    {"key": "aitiopaikka", "name": "Aitiopaikka", "subtitle": "Fresco Ravintolat", "url": "https://www.frescoravintolat.fi/lounas/aitiopaikan-lounaslista/"},
]

WEEKDAY_CAP = {
    "maanantai": "Maanantai",
    "tiistai": "Tiistai",
    "keskiviikko": "Keskiviikko",
    "torstai": "Torstai",
    "perjantai": "Perjantai",
    "lauantai": "Lauantai",
    "sunnuntai": "Sunnuntai",
}

def helsinki_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Helsinki"))

def today_name() -> str:
    return DAY_NAMES[helsinki_now().weekday()]

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text

def soup_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    lines = [normalize(x) for x in soup.get_text("\n").splitlines()]
    return [x for x in lines if x]

def dedupe_keep_order(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out

def parse_grillit(html: str, day_name: str) -> tuple[list[str], str]:
    # Based on current Raflaamo text structure with duplicated day headings. citeturn459528view0
    lines = soup_lines(html)
    day_heading = WEEKDAY_CAP[day_name]
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"### {day_heading} "):
            start = i
            break
    if start is None:
        return [], "-"
    block = []
    for line in lines[start + 1:]:
        if line.startswith("### ") and not line.startswith(f"### {day_heading} "):
            break
        block.append(line)

    items = []
    price = "-"
    collect_menu = False
    for line in block:
        if line.startswith("### "):
            continue
        if line.startswith("Lounas:"):
            continue
        if line in {"L", "G", "M", "VE", "VL", "VEP", "GP", "G L", "G VL", "G VE", "L G"}:
            continue
        if line.startswith("Hinta:"):
            m = re.search(r"(\d{1,2},\d{2})\s*€", line)
            if m and price == "-":
                price = f"{m.group(1)} €"
            continue
        if line.startswith("Asiakasomistajahinta:"):
            continue
        if line == "Lounasmenu":
            collect_menu = True
            continue
        if collect_menu and "***" in line:
            parts = [normalize(x) for x in line.split("***") if normalize(x)]
            items.append("Lounasmenu: " + " + ".join(parts))
            collect_menu = False
            continue
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", line):
            continue
        if line.startswith("Lisäkkeenä tarjoilemme:"):
            line = line.replace("Lisäkkeenä tarjoilemme:", "Lisäkkeet:")
        if line and not line.startswith("Tervetuloa lounaalle!") and not line.startswith("Lounaan hintaan sisältyy"):
            items.append(line)
    return dedupe_keep_order(items)[:6], price

def parse_viides(html: str, day_name: str) -> tuple[list[str], str]:
    text = "\n".join(soup_lines(html))
    heading = WEEKDAY_CAP[day_name]
    m = re.search(r"Buffetlounas\s*(\d{1,2},\d{2})\s*€", text)
    price = f"{m.group(1)} €" if m else "-"
    pat = rf"{heading} \d{{1,2}}\.\d{{1,2}}\.(.*?)(?=(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai) \d{{1,2}}\.\d{{1,2}}\.|L=laktoositon|Kysy henkilökunnalta|$)"
    m2 = re.search(pat, text, re.S)
    if not m2:
        return [], price
    block = [normalize(x) for x in m2.group(1).split("\n") if normalize(x)]
    items = [x for x in block if not x.startswith("Kysy henkilökunnalta") and not x.startswith("Kaikki käyttämämme")]
    return dedupe_keep_order(items)[:4], price

def parse_aitiopaikka(html: str, day_name: str) -> tuple[list[str], str]:
    text = "\n".join(soup_lines(html))
    heading = WEEKDAY_CAP[day_name]
    m = re.search(r"Lämminruokalounas\s*(\d{1,2},\d{2})\s*€", text)
    price = f"{m.group(1)} €" if m else "-"
    pat = rf"{heading}(.*?)(?=(Maanantai|Tiistai|Keskiviikko|Torstai|Perjantai)|L = laktoositon|Lihojen ja broilerin|Tutustu ravintola Aitiopaikkaan|$)"
    m2 = re.search(pat, text, re.S)
    if not m2:
        return [], price
    block = [normalize(x) for x in m2.group(1).split("\n") if normalize(x)]
    items = [x for x in block if x not in {"Ravintola suljettu!", "PITKÄPERJANTAI"}]
    items = [x for x in items if not re.fullmatch(r"\d{1,2}\.\d{1,2}\.?", x)]
    return dedupe_keep_order(items)[:4], price

PARSERS = {"grillit": parse_grillit, "viides": parse_viides, "aitiopaikka": parse_aitiopaikka}

def main() -> None:
    day = today_name()
    debug = []
    restaurants = []
    for source in SOURCES:
        try:
            html = fetch_html(source["url"])
            items, price = PARSERS[source["key"]](html, day)
            status = "ok" if items else "error"
            restaurants.append({
                "key": source["key"],
                "name": source["name"],
                "subtitle": source["subtitle"],
                "url": source["url"],
                "price": price or "-",
                "items": items,
                "status": status,
            })
            debug.append(f'{source["name"]}: {status}, {len(items)} riviä, hinta {price}')
        except Exception as exc:
            restaurants.append({
                "key": source["key"],
                "name": source["name"],
                "subtitle": source["subtitle"],
                "url": source["url"],
                "price": "-",
                "items": [],
                "status": "error",
            })
            debug.append(f'{source["name"]}: virhe {type(exc).__name__}: {exc}')
    now = helsinki_now()
    payload = {
        "updated_at": now.isoformat(),
        "updated_at_fi": now.strftime("%d.%m.%Y %H:%M"),
        "today_name": day,
        "debug": debug,
        "restaurants": restaurants,
    }
    with open("data/lunches.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
