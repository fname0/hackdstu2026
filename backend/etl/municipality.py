import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEO = ROOT / "data" / "seed" / "geo"

TOWN_TO_DISTRICT = {
    "аксай": "аксайский", "сальск": "сальский", "миллерово": "миллеровский",
    "белая калитва": "белокалитвинский", "красный сулин": "красносулинский",
    "зерноград": "зерноградский", "семикаракорск": "семикаракорский",
    "константиновск": "константиновский", "пролетарск": "пролетарский",
    "цимлянск": "цимлянский", "морозовск": "морозовский",
}

SETTLEMENT_TO_DISTRICT = {
    "чалтырь": "мясниковский", "тацинская": "тацинский", "вешенская": "шолоховский",
    "багаевская": "багаевский", "кагальницкая": "кагальницкий", "покровское": "неклиновский",
    "орловский": "орловский", "песчанокопское": "песчанокопский", "зимовники": "зимовниковский",
    "ремонтное": "ремонтненский", "чертково": "чертковский", "кашары": "кашарский",
    "обливская": "обливский", "тарасовский": "тарасовский", "казанская": "верхнедонской",
    "боковская": "боковский", "дубовское": "дубовский", "заветное": "заветинский",
    "милютинская": "милютинский", "куйбышево": "куйбышевский", "каменоломни": "октябрьский",
    "большая мартыновка": "мартыновский", "весёлый": "веселовский", "веселый": "веселовский",
    "егорлыкская": "егорлыкский", "целина": "целинский", "усть-донецкий": "усть-донецкий",
    "советская": "советский", "глубокий": "каменский", "кулешовка": "азовский",
    "родионово-несветайская": "родионово-несветайский", "романовская": "волгодонской",
    "матвеев курган": "матвеево-курганский",
}

_PREFIX = re.compile(r"^(г\.?|город|р-н|район|станица|ст-ца|село|с\.|поселок|посёлок|п\.|рп|пгт|хутор|х\.|слобода|сл\.)\s+")
_SUFFIX = re.compile(r"\s+(р-н|район)$")

def norm(text: str) -> str:

    s = (text or "").strip().lower().replace("ё", "е")
    for _ in range(2):
        s = _PREFIX.sub("", s).strip()
    return _SUFFIX.sub("", s).strip()

def load_reference(region: str = "61") -> dict:

    path = GEO / {"61": "rostov_municipalities.geojson"}[region]
    ref = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        p = f["properties"]
        name = p["name"]
        if name.startswith("городской округ "):
            key = norm(name.removeprefix("городской округ "))
        else:
            key = norm(name.removesuffix(" район"))
        ref[key] = (p["oktmo"], p["short"])
    return ref

def assign(district: str, city: str, settlement: str, ref: dict):

    d, c, s = norm(district), norm(city), norm(settlement)
    if d and d in ref:
        return (*ref[d], "район из реестра")
    if c:
        if c in ref:
            return (*ref[c], "городской округ из реестра")
        if c in TOWN_TO_DISTRICT and TOWN_TO_DISTRICT[c] in ref:
            return (*ref[TOWN_TO_DISTRICT[c]], "город → район (справочник)")
    if s and s in SETTLEMENT_TO_DISTRICT and SETTLEMENT_TO_DISTRICT[s] in ref:
        return (*ref[SETTLEMENT_TO_DISTRICT[s]], "нас. пункт → район (справочник)")
    return (None, None, "не привязан")
