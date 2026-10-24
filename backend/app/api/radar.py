import csv
import functools
import io
import json
import math
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.db import one, rows

router = APIRouter(prefix="/api/radar", tags=["radar"])

def cached(ttl: int = 300):

    def deco(fn):
        store: dict = {}

        @functools.wraps(fn)
        def wrapper(*a, **kw):
            hit = store.get("v")
            if hit and time.monotonic() - hit[0] < ttl:
                return hit[1]
            v = fn(*a, **kw)
            store["v"] = (time.monotonic(), v)
            return v
        return wrapper
    return deco

ZONE_METRICS = ["potential", "companies", "active_ul", "rtk_clients", "rtk_share_pct", "coverage_vs_region",
                "expected_clients", "client_gap", "ul_income_sum", "ul_income_median",
                "ul_growth_median", "new_month", "left_month", "rtk_left_month", "market_dynamics_pct",
                "avg_relevance", "income_cur", "income_prev", "income_growth_abs", "income_growth_pct", "f_income", "f_growth", "f_gap"]

LIST_COLUMNS = """inn, name_short, kind, category, industry, okved_main, municipality, place, is_rtk_client,
    income_2025, income_growth_pct, staff_2025, msp_years, lead_score, products, dd_status, reloc_signals,
    location_precision, flag_zero_income, flag_check_category, rtk_in_same_building,
    geo_lat, geo_lon"""

def _clean(d: dict) -> dict:

    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}

@router.get("/summary")
@cached()
def summary():
    s = one("""SELECT count(*) AS companies,
                      count(*) FILTER (WHERE kind = 'ЮЛ') AS ul,
                      count(*) FILTER (WHERE kind = 'ИП') AS ip,
                      count(*) FILTER (WHERE kind = 'ИП (КФХ)') AS kfh,
                      count(*) FILTER (WHERE is_rtk_client) AS rtk_clients,
                      count(*) FILTER (WHERE new_in_release) AS new_month,
                      count(*) FILTER (WHERE income_2025 IS NOT NULL) AS with_income,
                      count(*) FILTER (WHERE geom IS NOT NULL) AS with_point,
                      sum(income_2025) AS income_sum
               FROM companies""")
    z = one("SELECT sum(left_month) AS left_month, count(*) FILTER (WHERE white_spot) AS white_spots, count(*) AS zones FROM zones")
    churn = rows("SELECT msp_status, churn_type, count(*) AS n FROM clients GROUP BY 1, 2 ORDER BY n DESC")
    meta = {r["name"]: json.loads(r["data"]) for r in rows("SELECT name, data FROM meta")}
    radar_meta = next((v for k, v in meta.items() if k.startswith("radar_")), {})
    return _clean({**s, **z, "rtk_share_pct": round(s["rtk_clients"] / s["companies"] * 100, 3),
                   "clients_status": churn, "msp_release": radar_meta.get("msp_release"),
                   "msp_prev_release": radar_meta.get("msp_prev_release"),
                   "sources": "ФНС России (реестр МСП, доходы, численность, спецрежимы), DaData (ЕГРЮЛ), OpenStreetMap"})

@router.get("/zones")
def zones():

    return JSONResponse(_zones_geojson())

@cached()
def _zones_geojson():
    cols = ", ".join(["oktmo", "municipality", "short", "kind", "white_spot", "white_spot_reason", "low_coverage",
                      "potential_rank"] + ZONE_METRICS)
    data = rows(f"SELECT {cols}, ST_AsGeoJSON(geom, 5) AS g FROM zones ORDER BY potential DESC")
    features = [{"type": "Feature", "geometry": json.loads(r.pop("g")), "properties": _clean(r)} for r in data]
    return {"type": "FeatureCollection", "features": features}

@router.get("/zones/metrics")
def zone_metrics(kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
                 income_min: float | None = None, income_max: float | None = None,
                 growth_min: float | None = None, include_no_income: bool = True):

    where, p = _where("all", kind, industry, None, income_min, income_max, growth_min, include_no_income, None, None, False)
    data = rows(f"""SELECT oktmo,
                           count(*) AS companies,
                           count(*) FILTER (WHERE kind = 'ЮЛ') AS ul,
                           count(*) FILTER (WHERE is_rtk_client) AS rtk_clients,
                           coalesce(sum(income_2025) FILTER (WHERE kind = 'ЮЛ'), 0) AS income_sum,
                           coalesce(sum(income_2025) FILTER (WHERE income_2024 > 0 AND income_2025 IS NOT NULL), 0) AS income_cur,
                           coalesce(sum(income_2024) FILTER (WHERE income_2024 > 0 AND income_2025 IS NOT NULL), 0) AS income_prev,
                           count(*) FILTER (WHERE new_in_release) AS new_month
                    FROM companies WHERE {where} AND oktmo IS NOT NULL GROUP BY oktmo""", **p)
    return [_clean(r) for r in data]

@router.get("/white-spots")
@cached()
def white_spots():
    return [_clean(r) for r in rows(
        """SELECT oktmo, municipality, potential, potential_rank, companies, active_ul, rtk_clients, expected_clients,
                  coverage_vs_region, white_spot_reason, income_growth_pct, f_income, f_growth, f_gap
           FROM zones WHERE white_spot ORDER BY potential DESC""")]

@router.get("/churn")
@cached()
def churn():

    cols = "inn, coalesce(dd_name, client_name_xlsx) AS name, kind, municipality, okved_main, msp_status, churn_type, churn_risk, dd_status, dd_liquidation_date"
    return {
        "left": [_clean(r) for r in rows(f"SELECT {cols} FROM clients WHERE churn_type IS NOT NULL ORDER BY dd_liquidation_date DESC NULLS LAST")],
        "risk": [_clean(r) for r in rows(f"SELECT {cols} FROM clients WHERE churn_risk IS NOT NULL ORDER BY dd_status, name")],
    }

@router.get("/industries")
@cached()
def industries():
    return rows("SELECT industry, count(*) AS n, count(*) FILTER (WHERE is_rtk_client) AS rtk FROM companies GROUP BY 1 ORDER BY n DESC")

def _where(client, kind, industry, oktmo, income_min, income_max, growth_min, include_no_income, bbox, q, only_points):
    w, p = ["true"], {}
    if client == "rtk":
        w.append("is_rtk_client")
    elif client == "other":
        w.append("NOT is_rtk_client")
    if kind:
        w.append("kind = ANY(:kind)"); p["kind"] = kind
    if industry:
        w.append("industry = ANY(:industry)"); p["industry"] = industry
    if oktmo:
        w.append("oktmo = ANY(:oktmo)"); p["oktmo"] = oktmo
    money = []
    if income_min is not None:
        money.append("income_2025 >= :imin"); p["imin"] = income_min * 1e6
    if income_max is not None:
        money.append("income_2025 <= :imax"); p["imax"] = income_max * 1e6
    if growth_min is not None:
        money.append("income_growth_pct >= :gmin"); p["gmin"] = growth_min
    if money:
        cond = " AND ".join(money)
        w.append(f"(({cond}) OR income_2025 IS NULL)" if include_no_income else f"({cond})")
    if bbox:
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox.split(",")]
        except ValueError:
            raise HTTPException(400, "bbox: minLon,minLat,maxLon,maxLat")
        w.append("geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)"); p.update(x1=x1, y1=y1, x2=x2, y2=y2)
    if only_points:
        w.append("geom IS NOT NULL")
    if q:
        w.append("(inn = :qe OR lower(name) LIKE :ql)"); p.update(qe=q.strip(), ql=f"%{q.strip().lower()}%")
    return " AND ".join(w), p

def _filters(client: Literal["all", "rtk", "other"] = "all",
             kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
             oktmo: list[str] | None = Query(None),
             income_min: float | None = Query(None, description="млн ₽"), income_max: float | None = Query(None, description="млн ₽"),
             growth_min: float | None = Query(None, description="%"),
             include_no_income: bool = True, bbox: str | None = None, q: str | None = None):
    return dict(client=client, kind=kind, industry=industry, oktmo=oktmo, income_min=income_min,
                income_max=income_max, growth_min=growth_min, include_no_income=include_no_income, bbox=bbox, q=q)

SORTS = {"lead_score": "lead_score DESC NULLS LAST", "income": "income_2025 DESC NULLS LAST",
         "growth": "income_growth_pct DESC NULLS LAST", "name": "name_short"}

@router.get("/companies")
def companies(client: Literal["all", "rtk", "other"] = "all",
              kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
              oktmo: list[str] | None = Query(None), income_min: float | None = None, income_max: float | None = None,
              growth_min: float | None = None, include_no_income: bool = True, bbox: str | None = None,
              q: str | None = None, sort: Literal["lead_score", "income", "growth", "name"] = "lead_score",
              limit: int = Query(50, le=500), offset: int = 0):
    where, p = _where(client, kind, industry, oktmo, income_min, income_max, growth_min, include_no_income, bbox, q, False)
    total = one(f"SELECT count(*) AS n FROM companies WHERE {where}", **p)["n"]
    items = rows(f"SELECT {LIST_COLUMNS} FROM companies WHERE {where} ORDER BY {SORTS[sort]} LIMIT :lim OFFSET :off",
                 **p, lim=limit, off=offset)
    return {"total": total, "items": [_clean(r) for r in items]}

@router.get("/points")
def points(client: Literal["all", "rtk", "other"] = "all",
           kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
           oktmo: list[str] | None = Query(None), income_min: float | None = None, income_max: float | None = None,
           growth_min: float | None = None, include_no_income: bool = True, bbox: str | None = None,
           limit: int = Query(5000, le=20000)):

    where, p = _where(client, kind, industry, oktmo, income_min, income_max, growth_min, include_no_income, bbox, None, True)
    data = rows(f"""SELECT inn, name_short, kind, industry, is_rtk_client, lead_score, income_2025,
                           geo_lat AS lat, geo_lon AS lon, geo_precision
                    FROM companies WHERE {where} ORDER BY lead_score DESC NULLS LAST LIMIT :lim""", **p, lim=limit)
    return [_clean(r) for r in data]

@router.get("/companies/{inn}")
def company(inn: str):
    c = one("SELECT * FROM companies WHERE inn = :inn", inn=inn)
    if not c:
        raise HTTPException(404, "нет в реестре МСП региона")
    c.pop("geom", None)
    c = _clean(c)
    c["branches"] = json.loads(c["branches"]) if c.get("branches") else []
    client = one("SELECT msp_status, churn_type FROM clients WHERE inn = :inn", inn=inn)
    zone = one("SELECT municipality, potential, white_spot, coverage_vs_region FROM zones WHERE oktmo = :o", o=c.get("oktmo"))
    score_parts = {k: c[k] for k in c if k.startswith("s_") and c[k]}
    return {**c, "client_status": client, "zone": _clean(zone) if zone else None, "score_parts": score_parts,
            "provenance": {
                "реквизиты, вид, категория, ОКВЭД, район": "ФНС, реестр МСП",
                "доходы, рост": "ФНС, доходы и расходы по бухотчётности (2024–2025)",
                "численность": "ФНС, среднесписочная численность",
                "статус, КПП, филиалы, юр. адрес": "ЕГРЮЛ через DaData",
                "координаты": "DaData suggest/address (точность в поле geo_precision)",
                "отрасль, продукты, балл": "оценка команды (backend/etl/products.py, scoring.py)",
            }}

EXPORT_COLUMNS = [("inn", "ИНН"), ("name_export", "Наименование"), ("kind", "Вид"), ("category", "Категория"),
                  ("industry", "Отрасль"), ("okved_main", "ОКВЭД"), ("municipality", "Муниципалитет"),
                  ("place", "Населённый пункт"), ("legal_address", "Юр. адрес (ЕГРЮЛ)"),
                  ("is_rtk_client", "Клиент РТК"), ("income_2025", "Доход 2025, ₽"),
                  ("income_growth_pct", "Рост дохода, %"), ("staff_2025", "Численность"),
                  ("lead_score", "Потенциал (оценка)"), ("products", "Рекомендованные продукты"),
                  ("dd_status", "Статус ЕГРЮЛ"), ("reloc_signals", "Регистрация ≠ место работы")]

def _export_rows(where, p, limit=20000):

    cols = ", ".join("coalesce(dd_name, nullif(name_short, ''), name) AS name_export" if c == "name_export" else c for c, _ in EXPORT_COLUMNS)
    return rows(f"SELECT {cols} FROM companies WHERE {where} ORDER BY lead_score DESC NULLS LAST LIMIT :lim", **p, lim=limit)

def _csv_value(v):

    if v is None:
        return ""
    if isinstance(v, bool):
        return "Да" if v else "Нет"
    if isinstance(v, float):
        if not math.isfinite(v):
            return ""
        return str(int(v)) if v.is_integer() else f"{v:.1f}".replace(".", ",")
    return v

@router.get("/export.csv")
def export_csv(client: Literal["all", "rtk", "other"] = "all",
               kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
               oktmo: list[str] | None = Query(None), income_min: float | None = None, income_max: float | None = None,
               growth_min: float | None = None, include_no_income: bool = True, bbox: str | None = None, q: str | None = None):
    where, p = _where(client, kind, industry, oktmo, income_min, income_max, growth_min, include_no_income, bbox, q, False)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EXPORT_COLUMNS])
    for r in _export_rows(where, p):
        w.writerow([_csv_value(r[c]) for c, _ in EXPORT_COLUMNS])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=radar_leads.csv"})

@router.get("/export/crm")
def export_crm(format: Literal["amocrm", "bitrix24"] = "amocrm",
               client: Literal["all", "rtk", "other"] = "other",
               kind: list[str] | None = Query(None), industry: list[str] | None = Query(None),
               oktmo: list[str] | None = Query(None), income_min: float | None = None, income_max: float | None = None,
               growth_min: float | None = None, include_no_income: bool = True, bbox: str | None = None,
               q: str | None = None, limit: int = Query(20000, le=20000)):

    where, p = _where(client, kind, industry, oktmo, income_min, income_max, growth_min, include_no_income, bbox, q, False)
    data = [_clean(r) for r in _export_rows(where, p, limit)]

    def note(r):
        parts = [f"ИНН {r['inn']}", f"Отрасль: {r['industry']} (ОКВЭД {r['okved_main'] or '—'})",
                 f"Район: {r['municipality'] or '—'}", f"Потенциал (оценка): {r['lead_score']}",
                 f"Рекомендованные продукты: {r['products']}"]
        if r["income_2025"] is not None:
            parts.append(f"Доход 2025: {r['income_2025']:,.0f} ₽".replace(",", " "))
        if r["dd_status"] and r["dd_status"] != "действует":
            parts.append(f"Статус ЕГРЮЛ: {r['dd_status']}")
        return ". ".join(parts) + ". Источник: ФНС (реестр МСП, ЕГРЮЛ), радар РТК."

    if format == "amocrm":
        companies = [{
            "name": r["name_export"],
            **({"custom_fields_values": [{"field_code": "ADDRESS", "values": [{"value": r["legal_address"]}]}]}
               if r["legal_address"] else {}),
            "_embedded": {"tags": [{"name": "радар РТК"}, {"name": r["industry"]}]},
        } for r in data]
        payload = {
            "format": "amoCRM API v4",
            "how_to_import": "1) POST /api/v4/companies с массивом companies (до 250 за запрос); "
                             "2) POST /api/v4/companies/notes: для каждого элемента notes entity_id = id созданной компании с тем же company_index",
            "companies": companies,
            "notes": [{"company_index": i, "note_type": "common", "params": {"text": note(r)}} for i, r in enumerate(data)],
        }
    else:
        payload = [{
            "fields": {
                "TITLE": r["name_export"],
                "COMPANY_TYPE": "CUSTOMER" if r["is_rtk_client"] else "OTHER",
                "INDUSTRY": BITRIX_INDUSTRY.get(r["industry"], "OTHER"),
                "ADDRESS": r["legal_address"] or r["place"],
                "COMMENTS": note(r),
                "ORIGINATOR_ID": "rt-radar", "ORIGIN_ID": r["inn"],
            },
            "params": {"REGISTER_SONET_EVENT": "N"},
        } for r in data]
    return JSONResponse(payload, headers={"Content-Disposition": f"attachment; filename=radar_{format}.json"})

BITRIX_INDUSTRY = {"ИТ и связь": "IT", "Производство": "MANUFACTURING", "Финансы и страхование": "FINANCE",
                   "Госсектор": "GOVERNMENT", "Транспорт и логистика": "DELIVERY", "Досуг и спорт": "ENTERTAINMENT",
                   "Профессиональные услуги": "CONSULTING"}
