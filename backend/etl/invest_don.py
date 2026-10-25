"""Реестр инвестпроектов Ростовской области с invest-don.ru → data/seed/invest/invest_don_61.*

Открытый JSON API портала (тот же, что у его страницы «Реестр инвестиционных проектов»), без ключа:
  GET map.invest-don.ru/api/GetProjectData?id=9149&page=1&rows=2000 — весь реестр: МО, название, статус, ввод,
      рабочие места, «100 губернаторских», координаты;
  GET map.invest-don.ru/api/GetObjectData/<row_id> — карточка: инициатор, начало, стоимость, create_date, modify_date.
Ответы кэшируются в data/seed/invest/raw/ (список — с датой выгрузки, карточки — по row_id), повторный запуск
скачивает только новые карточки. --refresh перекачивает список; modify_date есть только в карточке, поэтому
обновлённые проекты находит только --refresh-cards (перекачивает все карточки).

На выходе таблица с колонками как у листа xlsx (их дальше обрабатывает invest.py --source invest-don) плюс
status, lat/lon, row_id, даты. Запуск: python -m backend.etl.invest_don [--workers 3] [--refresh]
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "seed" / "invest"
RAW = OUT / "raw"
API = "https://map.invest-don.ru/api"
REGISTRY = {"61": "9149"}  # «Реестр инвестиционных проектов»; 9232 — ключевые проекты
UA = "rt-ecosystem-hackathon/0.1 (ETL, ~3 req/s)"

_TOKEN = re.compile(r'class="(property|value)"\s*>\s*<div>(.*?)</div>', re.S)
_NUM = re.compile(r"-?\d[\d\s]*(?:[.,]\d+)?")


def get_json(url: str, tries: int = 4) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_list(region: str, refresh: bool) -> list[dict]:
    path = RAW / f"list_{REGISTRY[region]}.json"
    if refresh or not path.exists():
        data = get_json(f"{API}/GetProjectData?id={REGISTRY[region]}&page=1&rows=5000")
        RAW.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"requested_at": datetime.now().isoformat(timespec="seconds"), "response": data},
                                   ensure_ascii=False), encoding="utf-8")
    cached = json.loads(path.read_text(encoding="utf-8"))
    return cached["response"]["data"]["rows"], cached["requested_at"]


def fetch_card(row_id: str, refresh: bool, pause: float) -> dict | None:
    path = RAW / "cards" / f"{row_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = get_json(f"{API}/GetObjectData/{row_id}")
    except Exception as e:  # сеть или сайт упали — карточку дозапросим в следующий запуск
        print(f"  карточка {row_id}: {e}", file=sys.stderr)
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    data["requested_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(pause)
    return data


def parse_card(card_html: str) -> dict:
    """HTML карточки → {свойство: значение}. Свойство-контейнер (период, стоимость) значения не имеет:
    за ним идут вложенные свойства, их и берём («Начало», «Ввод в эксплуатацию», «Всего»)."""
    out, prop = {}, None
    for kind, text in _TOKEN.findall(card_html):
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
        text = re.sub(r"\s+", " ", text).strip()
        if kind == "property":
            prop = text
        elif prop:
            out[prop] = text
            prop = None
    return out


def to_number(s) -> float | None:
    """«15 млн руб.» → 15.0, «1 500,5» → 1500.5, «5 мест» → 5.0."""
    m = _NUM.search(str(s or ""))
    return float(m.group(0).replace(" ", "").replace(",", ".")) if m else None


def to_year(s) -> int | None:
    m = re.search(r"(19|20)\d{2}", str(s or ""))
    return int(m.group(0)) if m else None


def list_row(r: dict) -> dict:
    o = r["0"]
    props = {(p.get("name") or "title"): p for p in o["properties"]}
    finish = next((q.get("value") for q in props.get("Период реализации проекта (годы)", {}).get("properties", [])
                   if q.get("name") == "Ввод в эксплуатацию"), None)
    feats = ((o.get("coord") or {}).get("value") or {}).get("features") or []
    # Точка, а у участков и трасс — внутренняя точка полигона или линии
    geoms = [shape(f["geometry"]) for f in feats if f.get("geometry") and f["geometry"].get("coordinates")]
    c = unary_union(geoms).representative_point() if geoms else None
    pt = (round(c.x, 6), round(c.y, 6)) if c is not None and not c.is_empty else None
    return {
        "row_id": o["row_id"], "title_list": props.get("title", {}).get("value"),
        "mo_list": props.get("Муниципальное образование", {}).get("value"),
        "status": props.get("Статус", {}).get("value"),
        "curator_list": props.get("Куратор проекта", {}).get("value"),
        "finish_list": to_year(finish),
        "jobs_list": props.get("Количество новых рабочих мест", {}).get("value"),
        "is_governor_100": bool(props.get("Входит в 100 Губернаторских инвестиционных проектов", {}).get("value")),
        "site_lon": pt[0] if pt else None, "site_lat": pt[1] if pt else None,
        "geo_objects": len(feats),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--pause", type=float, default=0.3, help="пауза после запроса карточки в каждом потоке, с")
    ap.add_argument("--refresh", action="store_true", help="перекачать список реестра")
    ap.add_argument("--refresh-cards", action="store_true", help="перекачать все карточки")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")

    rows, list_at = fetch_list(a.region, a.refresh)
    base = pd.DataFrame([list_row(r) for r in rows]).drop_duplicates("row_id")
    print(f"реестр: {len(base)} проектов (выгрузка {list_at})", file=sys.stderr)

    todo = list(base.row_id)
    cards, t0 = {}, time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for n, (rid, c) in enumerate(zip(todo, ex.map(lambda i: fetch_card(i, a.refresh_cards, a.pause), todo)), 1):
            cards[rid] = c
            if n % 100 == 0:
                print(f"  карточки {n}/{len(todo)} · {time.time() - t0:.0f} с", file=sys.stderr, flush=True)

    recs = []
    for r in base.to_dict("records"):
        c = cards.get(r["row_id"])
        f = parse_card(c.get("html", "")) if c else {}
        recs.append({
            # колонки как в листе xlsx — их понимает invest.py
            "src_no": r["row_id"], "mo_raw": f.get("Муниципальное образование") or r["mo_list"],
            "curator": f.get("Куратор проекта") or r["curator_list"],
            "is_key": "Да" if r["is_governor_100"] else "Нет",
            "initiator_raw": f.get("Инициатор инвестиционного проекта"),
            "title_raw": (c or {}).get("title") or r["title_list"],
            "start_year": to_year(f.get("Начало")), "finish_year": to_year(f.get("Ввод в эксплуатацию")) or r["finish_list"],
            "sum_mln": to_number(f.get("Всего")), "sum_raw": f.get("Всего"),
            "jobs": to_number(f.get("Количество новых рабочих мест")) or to_number(r["jobs_list"]),
            # только с сайта
            "row_id": r["row_id"], "status": r["status"], "site_lat": r["site_lat"], "site_lon": r["site_lon"],
            "geo_objects": r["geo_objects"], "progress": f.get("Ход реализации проекта"),
            "create_date": (c or {}).get("create_date"), "modify_date": (c or {}).get("modify_date"),
            "card_loaded": c is not None,
            "url": f"https://invest-don.ru/ru/register_investment_projects/{r['row_id']}",
        })
    out = pd.DataFrame(recs)
    stem = f"invest_don_{a.region}"
    out.to_parquet(OUT / f"{stem}.parquet", index=False)
    out.to_csv(OUT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    meta = {
        "source": f"invest-don.ru, реестр {REGISTRY[a.region]} (map.invest-don.ru/api: GetProjectData, GetObjectData)",
        "list_requested_at": list_at, "projects": len(out), "cards_loaded": int(out.card_loaded.sum()),
        "by_status": out.status.value_counts().to_dict(),
        "with_coords": int(out.site_lat.notna().sum()), "with_initiator": int(out.initiator_raw.notna().sum()),
        "with_sum": int(out.sum_mln.notna().sum()), "with_start": int(out.start_year.notna().sum()),
        "with_finish": int(out.finish_year.notna().sum()),
        "sum_units": out.sum_raw.str.replace(_NUM, "", regex=True).str.strip().value_counts().head(5).to_dict(),
        "built_at": datetime.now().isoformat(timespec="seconds"), "today": date.today().isoformat(),
    }
    (OUT / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
