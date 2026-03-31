from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LunchBot/1.0; +https://github.com/)"
}

WEEKDAY_NAMES = ["sunnuntai", "maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai"]
DAY_ALIASES = {
    "maanantai": ["maanantai", "ma"],
    "tiistai": ["tiistai", "ti"],
    "keskiviikko": ["keskiviikko", "ke"],
    "torstai": ["torstai", "to"],
    "perjantai": ["perjantai", "pe"],
}

SOURCES = [
    {
        "key": "grillit",
        "name": "Grill it! Marina",
        "subtitle": "Raflaamo",
        "url": "https://www.raflaamo.fi/fi/ravintola/turku/grill-it-marina-turku/menu/lounas",
    },
    {
        "key": "viides",
        "name": "Viides Näyttämö",
        "subtitle": "Kulttuuriranta",
        "url": "https://www.viidesnayttamo.fi/?page_id=73",
    },
    {
        "key": "aitiopaikka",
        "name": "Aitiopaikka",
        "subtitle": "Fresco Ravintolat",
        "url": "https://www.frescoravintolat.fi/lounas/aitiopaikan-lounaslista/",
    },
]


def helsinki_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Helsinki"))


def today_name() -> str:
    return WEEKDAY_NAMES[helsinki_now().weekday() + 1 if helsinki_now().weekday() < 6 else 0]


# Python weekday Monday=0..Sunday=6 -> convert to our list Sunday first
def today_name() -> str:
    py = helsinki_now().weekday()
    mapping = {
        0: "maanantai",
        1: "tiistai",
        2: "keskiviikko",
        3: "torstai",
        4: "perjantai",
        5: "lauantai",
        6: "sunnuntai",
    }
    return mapping[py]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def fetch_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return normalize("\n".join(soup.stripped_strings))


def dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        item = normalize(item)
        if item and item not in seen:
            seen.append(item)
    return seen


def extract_day_block(text: str, day_name: str) -> str | None:
    aliases = DAY_ALIASES.get(day_name, [day_name])
    start_re = re.compile(rf"({'|'.join(map(re.escape, aliases))})(?:\s+\d{{1,2}}\.\d{{1,2}}\.?)?", re.I)
    m = start_re.search(text)
    if not m:
        return None
    rest = text[m.start():]
    next_aliases = []
    for d, vals in DAY_ALIASES.items():
        if d != day_name:
            next_aliases.extend(vals)
    end_re = re.compile(rf"\b({'|'.join(map(re.escape, next_aliases))})\b", re.I)
    m2 = end_re.search(rest[10:])
    end = (m2.start() + 10) if m2 else len(rest)
    return rest[:end].strip()


def parse_price(html: str, text: str) -> str:
    patterns = [
        r"(\d{1,2},\d{2}\s*€)",
        r"(\d{1,2}\.\d{2}\s*€)",
        r"(\d{1,2}\s*€)",
    ]
    lowered = text.lower()
    for keyword in ["hinta", "lounas", "asiakasomistajahinta"]:
        idx = lowered.find(keyword)
        if idx != -1:
            snippet = text[idx:idx + 220]
            for pat in patterns:
                m = re.search(pat, snippet, re.I)
                if m:
                    return m.group(1).replace(".", ",")
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1).replace(".", ",")
    return "-"


def parse_generic_day_lines(text: str, day_name: str) -> list[str]:
    block = extract_day_block(text, day_name)
    if not block:
        return []
    lines = [normalize(x) for x in re.split(r"[\n\r]+", block)]
    if len(lines) <= 1:
        # fallback if HTML collapsed into one line
        parts = re.split(r"(?<=\.)\s+|(?<=,)\s+(?=[A-ZÅÄÖ])", block)
        lines = [normalize(x) for x in parts]
    filtered = []
    for line in lines:
        if not line:
            continue
        if re.fullmatch(r"(maanantai|tiistai|keskiviikko|torstai|perjantai)(\s+\d{1,2}\.\d{1,2}\.?)?", line, re.I):
            continue
        if re.match(r"^(lounaslista|lounasaika)\b", line, re.I):
            continue
        filtered.append(line)
    return dedupe(filtered)


def parse_grillit(html: str, day_name: str) -> tuple[list[str], str]:
    text = text_from_html(html)
    items = parse_generic_day_lines(text, day_name)
    items = [
        x for x in items
        if not re.match(r"^(Hinta:|Asiakasomistajahinta:)\b", x, re.I)
        and not re.fullmatch(r"(G|L|VL|VE|M|GP|VEP)(\s+(G|L|VL|VE|M|GP|VEP))*", x, re.I)
    ]
    return items[:10], parse_price(html, text)


def parse_viides(html: str, day_name: str) -> tuple[list[str], str]:
    text = text_from_html(html)
    items = parse_generic_day_lines(text, day_name)
    return items[:8], parse_price(html, text)


def parse_aitiopaikka(html: str, day_name: str) -> tuple[list[str], str]:
    text = text_from_html(html)
    items = parse_generic_day_lines(text, day_name)
    return items[:8], parse_price(html, text)


PARSERS = {
    "grillit": parse_grillit,
    "viides": parse_viides,
    "aitiopaikka": parse_aitiopaikka,
}


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
        except Exception as e:
            restaurants.append({
                "key": source["key"],
                "name": source["name"],
                "subtitle": source["subtitle"],
                "url": source["url"],
                "price": "-",
                "items": [],
                "status": "error",
            })
            debug.append(f'{source["name"]}: virhe {type(e).__name__}: {e}')

    now = helsinki_now()
    payload = {
        "updated_at": now.isoformat(),
        "updated_at_fi": now.strftime("%d.%m.%Y %H:%M"),
        "today_name": day,
        "debug": debug,
        "restaurants": restaurants,
    }

    out = "data/lunches.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
