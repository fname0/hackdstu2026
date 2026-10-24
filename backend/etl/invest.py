'ETL инвестпроектов (модуль 2) → data/seed/invest/projects_<регион>.* (xlsx) или projects_don_<регион>.* (invest-don.ru)'
import argparse
import difflib
import hashlib
import json
import math
import re
import sys
import urllib.error
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

from backend.etl.dadata_enrich import CACHE as DD_CACHE, DaData, load_key
from backend.etl.invest_classify import NEED_LABELS, classify
from backend.etl.municipality import GEO, load_reference, norm

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "Хакатон_2026_фактура.xlsx"
RADAR = ROOT / "data" / "seed" / "radar"
OUT = ROOT / "data" / "seed" / "invest"
REGION_NAME = {"61": "Ростовская обл"}

COLS = {
    "№ п/п": "src_no", "Муниципальное образование": "mo_raw", "Куратор проекта": "curator",
    "Входит в перечень ключевых инвестиционных проектов": "is_key", "Инициатор инвестиционного проекта": "initiator_raw",
    "Название и суть инвестиционного проекта (в том числе и мощность)": "title_raw", "Начало": "start_year",
    "Ввод в эксплуатацию": "finish_year", "Всего (млн руб.)": "sum_mln", "Количество новых рабочих мест (мест)": "jobs",
}

IT_SHARE = {
    "ТЭК и энергетика": 0.015, "Девелопмент и жильё": 0.015, "Логистика и склады": 0.03,
    "АПК и пищевое производство": 0.01, "Промышленность": 0.02, "Здравоохранение": 0.04, "Спорт и туризм": 0.02,
    "Торговля и общепит": 0.02, "Коммерческая недвижимость": 0.025, "Автосервис": 0.01, "Прочее": 0.01,
    "ИТ и связь": 0.3, "Бытовые услуги": 0.015, "Инфраструктура и благоустройство": 0.02,
}

_SPACE = re.compile(r"\s+")
_SPLIT = re.compile(r",\s*(?=(?:ИП|ООО|АО|ПАО|ЗАО|Индивидуальный предприниматель)\b)")
_LEGAL = re.compile(r"\b(?:ооо|оао|пао|зао|ао|ип|спк|кфх|гк|сз|общество с ограниченной ответственностью|"
                    r"индивидуальный предприниматель|(?:публичное |закрытое |открытое )?акционерное общество|"
                    r"специализированный застройщик|филиал|федеральный девелопер)\b")
_PAREN = re.compile(r"\([^)]*\)?")

MIN_MATCH = 0.8
_ADDR = re.compile(r"(?:по адресу:?\s*|(?=\b(?:ул|пер|пр|мкр)\.\s)|(?=\b(?:с|х|сл)\.\s?[А-ЯЁ]))(.+)$")

def clean(s) -> str:
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return ""
    return _SPACE.sub(" ", str(s)).strip().strip(",").strip()

def num(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)

def name_key(s: str) -> str:

    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()]", " ", s)
    s = _LEGAL.sub(" ", s)
    return _SPACE.sub(" ", s).strip(" .,-")

def read_sheet() -> pd.DataFrame:
    for sheet, df in pd.read_excel(XLSX, sheet_name=None).items():
        if "Инициатор инвестиционного проекта" in df.columns:
            df = df.rename(columns=COLS)[list(COLS.values())]
            df["sheet"] = sheet
            return df
    raise RuntimeError("в xlsx нет листа с инвестпроектами")

def read_invest_don(region: str) -> pd.DataFrame:
    path = OUT / f"invest_don_{region}.parquet"
    if not path.exists():
        raise SystemExit(f"нет {path.name}: сначала python -m backend.etl.invest_don --region {region}")
    df = pd.read_parquet(path)
    df["sheet"] = None
    return df

SITE_STAGE = {"Завершенные": "введён", "Приостановленные": "приостановлен", "Перспективные": "подготовка"}

def match_local(initiators: list[str], by_key: dict, msp: pd.DataFrame) -> tuple | None:

    for ini in initiators:
        inns = by_key.get(name_key(ini), [])
        if len(inns) == 1:
            return inns[0], msp.name[msp.inn == inns[0]].iloc[0], 1.0, "реестр МСП: точное совпадение имени"
    return None

class Lookup:

    def __init__(self, region: str, offline: bool, budget: int = 3000):
        self.region, self.dd, self.failed = region, None if offline else DaData(load_key(), budget=budget), 0

    def _cached(self, kind: str, query: str, method: str, payload: dict) -> dict | None:
        key = hashlib.md5(f"{self.region}|{query}".encode()).hexdigest()
        path = DD_CACHE / kind / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        if not self.dd:
            return None
        try:
            return self.dd.cached(kind, key, method, payload)["response"]
        except (urllib.error.URLError, TimeoutError) as e:
            self.failed += 1
            print(f"  DaData недоступна ({e}), пропускаю «{query[:40]}»", file=sys.stderr)
            return None
        except RuntimeError as e:
            print(f"  DaData: {e}; дальше работаю по кэшу", file=sys.stderr)
            self.failed += 1
            self.dd = None
            return None

    def party(self, query: str, region_only: bool = True) -> list[dict]:
        if region_only:
            r = self._cached("party_name", query, "suggest/party",
                             {"query": query, "count": 5, "locations": [{"kladr_id": self.region}]})
        else:
            r = self._cached("party_name", f"any|{query}", "suggest/party", {"query": query, "count": 5})
        return (r or {}).get("suggestions", [])

    def address(self, query: str) -> dict | None:
        r = self._cached("address", query, "suggest/address",
                         {"query": query, "count": 1, "locations": [{"kladr_id": self.region}]})
        sug = (r or {}).get("suggestions", [])
        return sug[0]["data"] if sug else None

def match_dadata(initiators: list[str], lk: Lookup) -> tuple | None:

    best = _best_party(initiators, lk, True)
    if best is None:
        legal = [i for i in initiators if re.search(r"\b(?:ООО|АО|ПАО|ЗАО|ОАО|ГК|ФГУП|МУП|ГУП|Филиал|Концерн)\b|«|\"", i)]
        best = _best_party(legal, lk, False)
        if best:
            best = (*best[:3], "DaData suggest/party по названию (вне региона)")
    return best

def _best_party(initiators: list[str], lk: Lookup, region_only: bool) -> tuple | None:
    best = None
    for ini in initiators:

        base = name_key(_PAREN.sub(" ", ini)) or name_key(ini)
        q = base if len(base) > 3 else ini
        for s in lk.party(q, region_only):
            d = s["data"]
            if d.get("state", {}).get("status") not in (None, "ACTIVE", "REORGANIZING"):
                continue
            names = [s["value"], (d.get("name") or {}).get("full") or "", (d.get("name") or {}).get("short") or ""]
            score = max(difflib.SequenceMatcher(None, base, name_key(n)).ratio() for n in names if n)
            if best is None or score > best[2]:
                best = (d["inn"], s["value"], round(score, 2), "DaData suggest/party по названию")
    return best if best and best[2] >= MIN_MATCH else None

def centroids(region: str) -> dict:
    path = GEO / {"61": "rostov_municipalities.geojson"}[region]
    out = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
        c = shape(f["geometry"]).representative_point()
        out[f["properties"]["oktmo"]] = (round(c.y, 5), round(c.x, 5))
    return out

def stage(start, finish, today: date, site_status=None) -> tuple[str, int | None]:

    months = None if finish is None else int((finish - today.year) * 12 + (12 - today.month))
    if site_status in SITE_STAGE:
        return SITE_STAGE[site_status], months
    if finish is None:
        return "сроки не указаны", None
    if start is not None and start > today.year:
        return "подготовка", months
    if finish < today.year:
        return "введён", months
    if finish == today.year:
        return "ввод в этом году", months
    return "реализация", months

def window_factor(months, st: str) -> tuple[float, str]:

    if st == "приостановлен":
        return 0.1, "проект приостановлен"
    if st == "подготовка" and (months is None or months > 18):
        return 0.8, "перспективный проект — зайти до выбора подрядчиков"
    if months is None:
        return 0.2, "срок ввода не указан"
    if st == "введён" or months <= 0:
        return 0.1, "уже введён — только допродажа в эксплуатации"
    if months < 6:
        return 0.4, "ввод меньше чем через 6 мес. — смета, скорее всего, закрыта"
    if months <= 18:
        return 1.0, "6–18 мес. до ввода — лучшее окно продаж"
    if months <= 36:
        return 0.6, "1,5–3 года до ввода — время знакомиться с инициатором"
    return 0.3, "больше 3 лет до ввода — держать на радаре"

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", default="61")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--source", choices=["xlsx", "invest-don"], default="xlsx")
    ap.add_argument("--budget", type=int, default=3000, help="максимум запросов DaData за запуск")
    a = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    today = date.fromisoformat(a.today)
    don = a.source == "invest-don"

    df = read_invest_don(a.region) if don else read_sheet()
    for c in ("mo_raw", "curator", "initiator_raw", "title_raw", "is_key"):
        df[c] = df[c].map(clean)
    df["is_key"] = df.is_key.eq("Да")
    df["initiators"] = df.initiator_raw.map(lambda s: [clean(x) for x in _SPLIT.split(s) if clean(x)])
    df["initiator"] = df.initiators.str[0]

    ref, cents = load_reference(a.region), centroids(a.region)
    df[["oktmo", "municipality"]] = [list(ref.get(norm(m), (None, None))) for m in df.mo_raw]

    msp = pd.read_parquet(RADAR / f"companies_{a.region}.parquet", columns=["inn", "name", "is_rtk_client"])
    msp["key"] = msp.name.map(name_key)
    clients = set(pd.read_parquet(RADAR / f"clients_{a.region}.parquet", columns=["inn"]).inn)
    msp_inns = set(msp.inn)
    msp_by_key = msp.groupby("key").inn.agg(list).to_dict()
    lk = Lookup(a.region, a.offline, a.budget)

    rows = []
    for n_row, r in enumerate(df.to_dict("records"), 1):
        if n_row % 200 == 0:
            print(f"  {n_row}/{len(df)}", file=sys.stderr, flush=True)
        m = None
        if r["initiators"]:
            m = match_local(r["initiators"], msp_by_key, msp) or match_dadata(r["initiators"], lk)
        inn, matched_name, score, method = m or (None, None, None, "не найден" if r["initiators"] else "инициатор не указан")
        if not inn:
            client_status = "ИНН не найден"
        elif inn in clients:
            client_status = "наш клиент"
        elif inn in msp_inns:
            client_status = "потенциальный (реестр МСП)"
        else:
            client_status = "потенциальный (вне МСП)"

        lat = lon = None
        precision, address = "центр муниципалитета", None
        if don and num(r.get("site_lat")) is not None:
            lat, lon, precision = num(r["site_lat"]), num(r["site_lon"]), "точка с портала invest-don.ru"
        elif am := _ADDR.search(r["title_raw"]):
            address = clean(am.group(1))
            g = lk.address(f"{REGION_NAME[a.region]}, {r['mo_raw']}, {address}")
            if g and g.get("geo_lat") and g.get("qc_geo") not in (None, "") and int(g["qc_geo"]) <= 3:
                lat, lon = float(g["geo_lat"]), float(g["geo_lon"])
                precision = {0: "дом", 1: "дом", 2: "улица", 3: "населённый пункт"}[int(g["qc_geo"])]
        if lat is None and r["oktmo"] in cents:
            lat, lon = cents[r["oktmo"]]

        start, finish, total = num(r["start_year"]), num(r["finish_year"]), num(r["sum_mln"])
        start, finish = (int(start) if start else None), (int(finish) if finish else None)
        st, months = stage(start, finish, today, r.get("status"))
        wf, w_reason = window_factor(months, st)
        cl = classify(r["initiator_raw"], r["title_raw"])
        share = IT_SHARE[cl["industry"]]
        potential = round(total * share, 2) if total is not None else None

        f_window = round(50 * wf, 1)
        f_size = round(30 * min(1.0, math.log10(1 + potential) / 2), 1) if potential else 0.0
        f_key = 10.0 if r["is_key"] else 0.0
        f_new = 10.0 if client_status.startswith("потенциальный") else 0.0

        rows.append({
            "project_id": f"{'don' if don else a.region}-{r['src_no']}", "src_no": r["src_no"], "region": a.region,
            "source": "invest-don.ru" if don else "xlsx организаторов", "site_status": r.get("status"),
            "url": r.get("url"), "modify_date": r.get("modify_date"), "create_date": r.get("create_date"),
            "mo_raw": r["mo_raw"], "oktmo": r["oktmo"], "municipality": r["municipality"],
            "curator": r["curator"], "is_key": r["is_key"],
            "initiator": r["initiator"], "initiators": r["initiators"], "initiator_inn": inn,
            "initiator_matched_name": matched_name, "match_score": score, "match_method": method,
            "client_status": client_status, "is_interregional": bool(inn) and not inn.startswith(a.region),
            "title": clean(r["title_raw"]), "address_from_text": address,
            "lat": lat, "lon": lon, "location_precision": precision,
            "start_year": start, "finish_year": finish,
            "duration_years": finish - start if start and finish else None,
            "stage": st, "months_to_launch": months, "sales_window": w_reason,
            "sum_mln": total, "jobs": num(r["jobs"]),
            "industry": cl["industry"], "industry_reason": cl["industry_reason"],
            "needs": [n["need"] for n in cl["needs"]], "needs_detail": json.dumps(cl["needs"], ensure_ascii=False),
            "it_share": share, "rtk_potential_mln": potential, "rtk_potential_is_estimate": True,
            "hot_score": round(f_window + f_size + f_key + f_new, 1),
            "hot_factors": json.dumps({"окно продаж": f_window, "потенциал": f_size, "ключевой проект": f_key,
                                       "не наш клиент": f_new}, ensure_ascii=False),
        })

    out = pd.DataFrame(rows).sort_values("hot_score", ascending=False)

    key = out.initiator_inn.fillna(out.initiator.map(name_key))
    out["initiator_projects"] = key.map(key.value_counts())

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"projects_{'don_' if don else ''}{a.region}"
    out.to_parquet(OUT / f"{stem}.parquet", index=False)
    out.drop(columns=["initiators"]).to_csv(OUT / f"{stem}.csv", index=False, encoding="utf-8-sig")
    src = "invest-don.ru, реестр инвестпроектов (открытый API портала)" if don else \
        f"{XLSX.name}, лист «{df.sheet.iloc[0]}» (данные организаторов)"
    meta = {
        "source": f"{src}; ИНН и адреса — DaData (ЕГРЮЛ/ЕГРИП, ФИАС)",
        "region": a.region, "today": a.today, "projects": len(out),
        "sum_mln_total": round(out.sum_mln.sum(), 1), "sum_mln_median": round(out.sum_mln.median(), 1),
        "inn_matched": int(out.initiator_inn.notna().sum()),
        "by_match_method": out.match_method.value_counts().to_dict(),
        "by_client_status": out.client_status.value_counts().to_dict(),
        "dadata_failed_requests": lk.failed,
        "interregional":int(out.is_interregional.sum()),
        "by_location_precision": out.location_precision.value_counts().to_dict(),
        "by_stage": out.stage.value_counts().to_dict(),
        "with_sum": int(out.sum_mln.notna().sum()), "with_finish_year": int(out.finish_year.notna().sum()),
        "by_industry": out.industry.value_counts().to_dict(),
        "by_need": {NEED_LABELS[k]: int(out.needs.map(lambda n: k in n).sum()) for k in NEED_LABELS},
        "without_needs": int(out.needs.map(len).eq(0).sum()),
        "it_share_norms": IT_SHARE, "it_share_note": "экспертный норматив для демо, не данные",
        "built_at": datetime.now().isoformat(timespec="seconds"),
    }
    (OUT / f"{stem}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
