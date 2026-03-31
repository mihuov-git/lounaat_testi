from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LunchBot/1.0; +https://github.com/)"}
DAY_NAMES = {0: "maanantai", 1: "tiistai", 2: "keskiviikko", 3: "torstai", 4: "perjantai", 5: "lauantai", 6: "sunnuntai"}
WEEKDAYS = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]

SOURCES = [
    {"key": "grillit", "name": "Grill it! Marina", "subtitle": "Raflaamo", "url": "https://www.raflaamo.fi/fi/ravintola/turku/grill-it-marina-turku/menu/lounas"},
    {"key": "viides", "name": "Viides Näyttämö", "subtitle": "Kulttuuriranta", "url": "https://www.viidesnayttamo.fi/?page_id=73"},
    {"key": "aitiopaikka", "name": "Aitiopaikka", "subtitle": "Fresco Ravintolat", "url": "https://www.frescoravintolat.fi/lounas/aitiopaikan-lounaslista/"},
]

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
    text = soup.get_text("\n")
    lines = [normalize(line) for line in text.splitlines()]
    return [line for line in lines if line]

def dedupe_keep_order(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

def is_day_heading(line: str) -> bool:
    return any(re.match(rf"^{day}\b", line, re.I) for day in WEEKDAYS)

def collect_day_block(lines: list[str], day_name: str) -> list[str]:
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^{day_name}\b", line, re.I):
            start = i
            break
    if start is None:
        return []
    block = []
    for line in lines[start + 1:]:
        if is_day_heading(line):
            break
        block.append(line)
    return block

def euro_amount(text: str) -> str | None:
    m = re.search(r"(\d{1,2}(?:,\d{2})?)\s*€", text)
    return f"{m.group(1)} €" if m else None

def parse_grillit(html: str, day_name: str):
    lines = soup_lines(html)
    block = collect_day_block(lines, day_name)
    items = []
    lunch_menu_parts = []
    in_lunch_menu = False
    price = "-"
    for line in block:
        if re.match(r"^Lounas:\s*", line, re.I):
            continue
        if re.match(r"^(G|L|VL|VE|M|GP|VEP)(\s+(G|L|VL|VE|M|GP|VEP))*$", line, re.I):
            continue
        if re.match(r"^Asiakasomistajahinta:", line, re.I):
            continue
        if re.match(r"^Hinta:\s*", line, re.I):
            amount = euro_amount(line)
            if amount and price == "-" and amount not in {"37,90 €", "35,90 €"}:
                price = amount
            continue
        if line == "Lounasmenu":
            in_lunch_menu = True
            continue
        if line in {"Ruokalistamme", "Tervetuloa lounaalle!"}:
            continue
        if in_lunch_menu:
            if "***" in line:
                lunch_menu_parts.extend([normalize(x) for x in line.split("***") if normalize(x)])
                in_lunch_menu = False
            elif not line.startswith("Hinta"):
                lunch_menu_parts.append(line)
                in_lunch_menu = False
            continue
        if line.startswith("Lisäkkeenä tarjoilemme:"):
            items.append(line.replace("Lisäkkeenä tarjoilemme:", "Lisäkkeet:").strip())
        else:
            items.append(line)
    if lunch_menu_parts:
        items.append("Lounasmenu: " + " + ".join(lunch_menu_parts))
    cleaned = []
    for item in items:
        if item.startswith("Lounaan hintaan sisältyy") or item.startswith("Buffetpöydästä löydät") or "VL =" in item:
            continue
        cleaned.append(item)
    return dedupe_keep_order(cleaned)[:8], price

def parse_viides(html: str, day_name: str):
    lines = soup_lines(html)
    block = collect_day_block(lines, day_name)
    items = []
    for line in block:
        if line.startswith("L=") or line.startswith("Kysy henkilökunnalta") or line.startswith("Kaikki käyttämämme"):
            continue
        items.append(line)
    price = "-"
    for line in lines:
        if re.match(r"^Buffetlounas\b", line, re.I):
            amount = euro_amount(line)
            if amount:
                price = amount
                break
    return dedupe_keep_order(items)[:5], price

def parse_aitiopaikka(html: str, day_name: str):
    lines = soup_lines(html)
    block = collect_day_block(lines, day_name)
    items = []
    for line in block:
        if line.startswith("L =") or line.startswith("Lihojen ja broilerin"):
            continue
        if line.upper() == "PITKÄPERJANTAI":
            items.append("Ravintola suljettu")
            continue
        if line == "Ravintola suljettu!":
            continue
        items.append(line)
    price = "-"
    for line in lines:
        if re.match(r"^Lämminruokalounas\b", line, re.I):
            amount = euro_amount(line)
            if amount:
                price = amount
                break
    return dedupe_keep_order(items)[:5], price

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
