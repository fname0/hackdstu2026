"""Госсектор для радара: учреждения региона из выгрузки bus.gov.ru → data/seed/gov/institutions_<регион>.*

Вход: data/raw/busgov/pages/page_*.json (backend/etl/busgov_fetch.py) — «Общая информация о государственных
(муниципальных) учреждениях» по приказу Минфина № 86н, вся Россия, + data/raw/busgov/by_inn/*.json (добор по ИНН).
Открытый набор — лента изменений: в нём ~25,6 тыс. учреждений РФ из ~138,7 тыс. на портале (по Ростовской области
466 на 25.10.2026). Поэтому заказчиков контрактов на связь добираем точечно запросом по ИНН.

Шаги:
  1) регион — по коду субъекта в адресе (КЛАДР «61…») или ОКТМО учреждения (Ростовская область — «60…»);
  2) у учреждения бывает несколько версий записи — оставляем последнюю (дата изменения, затем номер версии);
  3) район радара — первые 5 цифр ОКТМО + «000» (код муниципального района или городского округа),
     как в data/seed/geo/<регион>_municipalities.geojson;
  4) сегмент для продаж — по основному ОКВЭД и типу учреждения: образование, здравоохранение, соцзащита, культура,
     спорт, органы власти, ЖКХ и инфраструктура, прочее;
  5) уровень — по форме собственности (ОКФС): федеральное, региональное, муниципальное;
  6) признак ликвидации — в должности руководителя «ликвидацион…» (председатель ликвидационной комиссии).
Координаты берём с портала как есть (их проставляет ГИС ГМУ), точность — «адрес учреждения».

Запуск: python -m backend.etl.busgov --region 61
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "data" / "raw" / "busgov" / "pages"
# Добор по ИНН (busgov_fetch --inns-csv): открытый набор — лента изменений, в нём ~18% учреждений
BY_INN = PAGES.parent / "by_inn"
OUT = ROOT / "data" / "seed" / "gov"
GEO = ROOT / "data" / "seed" / "geo"
GEOJSON = {"61": "rostov_municipalities.geojson"}
OKTMO_PREFIX = {"61": "60"}  # код региона в ОКТМО отличается от кода в КЛАДР/ИНН

# Сегменты: (название, префиксы основного ОКВЭД). Порядок важен: первый подходящий
SEGMENTS = [
    ("Органы власти", ("84.1", "84.2")),
    ("Образование", ("85",)),
    ("Здравоохранение", ("86",)),
    ("Соцзащита", ("87", "88", "84.3")),
    ("Культура", ("90", "91", "59.14")),
    ("Спорт", ("93",)),
    ("ЖКХ и инфраструктура", ("35", "36", "37", "38", "39", "42", "52.2", "81")),
]
LEVEL = {"11": "федеральное", "12": "федеральное", "13": "региональное", "14": "муниципальное"}

# Что предложить по сегменту — короткая подсказка продажнику (оценка команды, как products.py радара)
OFFER = {
    "Образование": "интернет и Wi-Fi для учебного процесса, видеонаблюдение, СКУД",
    "Здравоохранение": "защищённые каналы для ЕГИСЗ, телемедицина, облако для медданных",
    "Соцзащита": "интернет и телефония, видеонаблюдение, тревожная кнопка",
    "Культура": "Wi-Fi для посетителей, видеонаблюдение, цифровые экраны",
    "Спорт": "видеонаблюдение в местах массового пребывания, Wi-Fi",
    "Органы власти": "защищённая сеть, ВКС, ИБ, облако, Госуслуги-сервисы",
    "ЖКХ и инфраструктура": "телеметрия и диспетчеризация объектов, IoT-учёт ресурсов",
    "Прочее": "интернет, телефония, видеонаблюдение",
}


def segment(okved: str, inst_type: str) -> str:
    for name, prefixes in SEGMENTS:
        if okved.startswith(prefixes):
            return name
    t = inst_type.lower()
    if "школ" in t or "сад" in t or "образоват" in t or "колледж" in t:
        return "Образование"
    if "больниц" in t or "поликлин" in t or "здравоохран" in t:
        return "Здравоохранение"
    return "Прочее"


def address(a: dict) -> str:
    parts = [a.get("zip")]
    for k in ("subject", "region", "city", "locality", "street"):
        if (a.get(k) or {}).get("name"):
            parts.append(a[k]["name"])
    parts.append(a.get("building"))
    return ", ".join(p for p in parts if p)


def parse(rec: dict) -> dict | None:
    pos = rec["body"]["position"]
    main = pos.get("main") or {}
    # Учреждение — initiator; placer — кто разместил запись: само учреждение или «Оператор сайта» (ИНН 4444444432).
    # Брать placer нельзя: записи, размещённые оператором, склеиваются в одно «учреждение»
    org = pos.get("initiator") or pos.get("placer") or {}
    cls = main.get("classifier") or {}
    adr = (main.get("complexAddress") or {})
    a, coords = adr.get("address") or {}, adr.get("coordinates") or {}
    add, other = pos.get("additional") or {}, pos.get("other") or {}
    okveds = cls.get("okved") or []
    okved = next((o for o in okveds if o.get("type") == "C"), okveds[0] if okveds else {})
    chief = (other.get("chief") or [{}])[0]
    founders = other.get("founder") or []
    return {
        "inn": org.get("inn"), "kpp": org.get("kpp"),
        "ogrn": main.get("ogrn"), "name": org.get("fullName"), "name_short": main.get("shortName"),
        "change_date": pos.get("changeDate"), "version": pos.get("versionNumber") or 0,
        "subject_code": (a.get("subject") or {}).get("code") or "",
        "oktmo_full": (cls.get("oktmo") or {}).get("code") or "", "place": (cls.get("oktmo") or {}).get("name"),
        "okopf": (cls.get("okopf") or {}).get("name", "").strip(), "okfs": (cls.get("okfs") or {}).get("code"),
        "okved_main": okved.get("code") or "", "okved_main_name": okved.get("name"),
        "inst_type": (add.get("institutionType") or {}).get("name") or "",
        "address": address(a), "lat": coords.get("latitude"), "lon": coords.get("longitude"),
        "phone": add.get("phone"), "www": (add.get("www") or "").strip() if (add.get("www") or "").strip() not in ("http://", "https://") else None,
        "chief": " ".join(x for x in (chief.get("lastName"), chief.get("firstName"), chief.get("middleName")) if x) or None,
        "chief_position": chief.get("position"),
        "founder": founders[0].get("fullName") if founders else None,
        "budget_owner": (main.get("grbs") or {}).get("fullName"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    files = sorted(PAGES.glob("page_*.json"))
    extra = sorted(BY_INN.glob("*.json")) if BY_INN.exists() else []
    if not files:
        sys.exit("нет страниц в data/raw/busgov/pages — сначала python -m backend.etl.busgov_fetch")
    kladr, okprefix = a.region, OKTMO_PREFIX[a.region]
    rows, seen = [], 0
    for f in files + extra:
        for rec in json.loads(f.read_text(encoding="utf-8")):
            seen += 1
            r = parse(rec)
            if r and r["inn"] and (r["subject_code"].startswith(kladr) or r["oktmo_full"].startswith(okprefix)):
                rows.append(r)
    df = pd.DataFrame(rows)
    versions = len(df)
    df = df.sort_values(["change_date", "version"]).drop_duplicates("inn", keep="last")

    geo = json.loads((GEO / GEOJSON[a.region]).read_text(encoding="utf-8"))
    mun = {f["properties"]["oktmo"]: f["properties"]["short"] for f in geo["features"]}
    # ОКТМО учреждения: регион(2) + район/округ(3) + поселение(3) [+ населённый пункт(3)] → «60712000»
    df["oktmo"] = df.oktmo_full.str[:5] + "000"
    df["oktmo"] = df.oktmo.where(df.oktmo.isin(mun.keys()))
    df["municipality"] = df.oktmo.map(mun)
    df["segment"] = [segment(o, t) for o, t in zip(df.okved_main, df.inst_type)]
    df["offer"] = df.segment.map(OFFER)
    df["level"] = df.okfs.map(LEVEL).fillna("иное")
    df["is_liquidating"] = df.chief_position.fillna("").str.contains("ликвидацион", case=False)
    df["source"] = "bus.gov.ru (ГИС ГМУ), «Общая информация об учреждениях», приказ Минфина № 86н"
    df = df.drop(columns=["subject_code", "okfs", "version"])

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"institutions_{a.region}"
    df.to_parquet(OUT / f"{stem}.parquet", index=False)
    df.to_csv(OUT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    fetch_meta = PAGES.parent / "fetch.meta.json"
    fm = json.loads(fetch_meta.read_text(encoding="utf-8")) if fetch_meta.exists() else {}
    active = df[~df.is_liquidating]
    meta = {
        "source": "bus.gov.ru, набор 7710568760-Generalinformation (открытые данные ГИС ГМУ)",
        "region": a.region, "pages": len(files), "by_inn_files": len(extra), "pages_total": fm.get("pages"), "records_seen": seen,
        "records_total_portal": fm.get("total"), "complete": bool(fm.get("pages")) and len(files) >= fm["pages"],
        "region_versions": versions, "institutions": len(df), "liquidating": int(df.is_liquidating.sum()),
        "with_coords": int(df.lat.notna().sum()), "bound_to_municipality": int(df.oktmo.notna().sum()),
        "by_segment": active.segment.value_counts().to_dict(), "by_level": active.level.value_counts().to_dict(),
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUT / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
