"""API слоя «Госсектор» радара: государственные и муниципальные учреждения с bus.gov.ru (таблица institutions).

Источник — открытые данные ГИС ГМУ (приказ Минфина № 86н), разбор — backend/etl/busgov.py. Сегмент и «что предложить» —
оценка команды по ОКВЭД и типу учреждения. Учреждения в ликвидации по умолчанию не показываем.
"""
import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import ProgrammingError

from backend.app.api.radar import _clean, cached
from backend.app.db import one, rows

router = APIRouter(prefix="/api/gov", tags=["gov"])

SEGMENTS = ["Образование", "Здравоохранение", "Соцзащита", "Культура", "Спорт", "Органы власти",
            "ЖКХ и инфраструктура", "Прочее"]
LIST_COLUMNS = """inn, name_short, name, segment, level, inst_type, municipality, oktmo, place, address, lat, lon,
    phone, www, chief, chief_position, founder, offer, is_liquidating"""


def _where(segment, level, oktmo, q, bbox, with_liquidating):
    w, p = ["true"], {}
    if not with_liquidating:
        w.append("NOT is_liquidating")
    if segment:
        w.append("segment = ANY(:segment)"); p["segment"] = segment
    if level:
        w.append("level = ANY(:level)"); p["level"] = level
    if oktmo:
        w.append("oktmo = ANY(:oktmo)"); p["oktmo"] = oktmo
    if q:
        w.append("(inn = :qe OR lower(coalesce(name_short, '') || ' ' || name) LIKE :ql)")
        p.update(qe=q.strip(), ql=f"%{q.strip().lower()}%")
    if bbox:
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox.split(",")]
        except ValueError:
            raise HTTPException(400, "bbox: minLon,minLat,maxLon,maxLat")
        w.append("geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)"); p.update(x1=x1, y1=y1, x2=x2, y2=y2)
    return " AND ".join(w), p


@router.get("/summary")
@cached()
def summary():
    """Сводка слоя; available = false, пока таблица не загружена (выгрузка bus.gov.ru идёт часами)."""
    try:
        s = one("""SELECT count(*) FILTER (WHERE NOT is_liquidating) AS institutions,
                          count(*) FILTER (WHERE is_liquidating) AS liquidating,
                          count(*) FILTER (WHERE geom IS NOT NULL AND NOT is_liquidating) AS with_point
                   FROM institutions""")
    except ProgrammingError:
        return {"available": False}
    by = lambda col: [_clean(r) for r in rows(
        f"SELECT {col} AS key, count(*) AS n FROM institutions WHERE NOT is_liquidating GROUP BY 1 ORDER BY n DESC")]
    meta = one("SELECT data FROM meta WHERE name LIKE 'institutions%' LIMIT 1")
    m = json.loads(meta["data"]) if meta else {}
    cm = one("SELECT data FROM meta WHERE name LIKE 'contracts%' LIMIT 1")
    contracts = json.loads(cm["data"]) if cm else None
    # complete — выгрузка bus.gov.ru дошла до конца; при этом сам открытый набор — лента изменений, не весь реестр
    return _clean({"available": True, **s, "by_segment": by("segment"), "by_level": by("level"),
                   "complete": m.get("complete"), "built_at": m.get("built_at"), "contracts": contracts,
                   "source": "bus.gov.ru (ГИС ГМУ), открытые данные по приказу Минфина № 86н; контракты - ЕИС zakupki.gov.ru"})


@router.get("/points")
def points(segment: list[str] | None = Query(None), level: list[str] | None = Query(None),
           oktmo: list[str] | None = Query(None), bbox: str | None = None, limit: int = Query(20000, le=20000)):
    """Точки учреждений. is_rtk_client — есть действующий контракт на связь с Ростелекомом (ЕИС): так учреждение
    красится как клиент РТК, как и компании радара."""
    where, p = _where(segment, level, oktmo, None, bbox, False)
    rtk = """EXISTS (SELECT 1 FROM gov_contracts c WHERE c.customer_inn = institutions.inn AND c.is_rtk AND c.is_active)"""
    try:
        data = rows(f"""SELECT inn, name_short, segment, level, lat, lon, {rtk} AS is_rtk_client FROM institutions
                        WHERE {where} AND geom IS NOT NULL LIMIT :lim""", **p, lim=limit)
    except ProgrammingError:  # контракты ещё не загружены — все «не клиенты»
        data = rows(f"""SELECT inn, name_short, segment, level, lat, lon, false AS is_rtk_client FROM institutions
                        WHERE {where} AND geom IS NOT NULL LIMIT :lim""", **p, lim=limit)
    return [_clean(r) for r in data]


@router.get("/zone/{oktmo}")
def zone(oktmo: str, segment: list[str] | None = Query(None), limit: int = Query(50, le=500), offset: int = 0):
    """Госсектор района: разбивка по сегментам и список учреждений (крупные сегменты и органы власти первыми)."""
    where, p = _where(segment, None, [oktmo], None, None, False)
    by = [_clean(r) for r in rows(
        "SELECT segment AS key, count(*) AS n FROM institutions WHERE oktmo = :o AND NOT is_liquidating GROUP BY 1 ORDER BY n DESC",
        o=oktmo)]
    total = one(f"SELECT count(*) AS n FROM institutions WHERE {where}", **p)["n"]
    try:  # связь учреждений района по контрактам ЕИС
        telecom = _clean(one("""SELECT count(*) FILTER (WHERE c.supplier_known) AS contracts,
                                       count(*) FILTER (WHERE c.is_rtk) AS rtk,
                                       count(*) FILTER (WHERE c.sales_window) AS sales_window
                                FROM gov_contracts c JOIN institutions i ON i.inn = c.customer_inn
                                WHERE i.oktmo = :o AND c.is_active""", o=oktmo))
    except ProgrammingError:
        telecom = None
    items = rows(f"""SELECT {LIST_COLUMNS} FROM institutions WHERE {where}
                     ORDER BY (segment = 'Органы власти') DESC, segment, name_short LIMIT :lim OFFSET :off""",
                 **p, lim=limit, off=offset)
    return {"by_segment": by, "total": total, "telecom": telecom, "items": [_clean(r) for r in items]}


CONTRACT_COLUMNS = """reestr_number, customer_inn, customer, subject, service, price, signed_date, finish_date, is_active,
    months_left, supplier, supplier_inn, operator, is_rtk, supplier_known, sales_window"""


def _contracts(inn: str) -> list[dict]:
    try:
        return [_clean(r) for r in rows(f"SELECT {CONTRACT_COLUMNS} FROM gov_contracts WHERE customer_inn = :inn "
                                        "ORDER BY is_active DESC, finish_date DESC NULLS LAST", inn=inn)]
    except ProgrammingError:  # контракты ещё не загружены
        return []


@router.get("/institutions/{inn}")
def institution(inn: str):
    r = one(f"SELECT {LIST_COLUMNS}, ogrn, kpp, okopf, okved_main, okved_main_name, budget_owner, change_date, source "
            "FROM institutions WHERE inn = :inn", inn=inn)
    if not r:
        raise HTTPException(404, "учреждение не найдено")
    return {**_clean(r), "contracts": _contracts(inn)}


@router.get("/expiring")
def expiring(months: int = Query(6, ge=1, le=24), oktmo: list[str] | None = Query(None),
             limit: int = Query(50, le=1000), offset: int = 0):
    """«Кому звонить» в госсекторе: действующие контракты на связь не с Ростелекомом, которые кончаются в ближайшие
    months месяцев. Учреждение (сегмент, район, точка) — если оно есть в выгрузке bus.gov.ru."""
    w, p = ["c.supplier_known", "NOT c.is_rtk", "c.is_active", "c.months_left <= :m"], {"m": months}
    if oktmo:
        w.append("i.oktmo = ANY(:oktmo)"); p["oktmo"] = oktmo
    where = " AND ".join(w)
    try:
        total = one(f"""SELECT count(*) AS n, coalesce(sum(c.price), 0) AS sum FROM gov_contracts c
                        LEFT JOIN institutions i ON i.inn = c.customer_inn WHERE {where}""", **p)
    except ProgrammingError:
        return {"total": 0, "sum": 0, "items": []}
    items = rows(f"""SELECT c.reestr_number, c.customer_inn, coalesce(i.name_short, c.customer) AS customer, c.subject,
                            c.service, c.price, c.finish_date, c.months_left, c.supplier, c.operator,
                            i.segment, i.municipality, i.inn IS NOT NULL AS has_card
                     FROM gov_contracts c LEFT JOIN institutions i ON i.inn = c.customer_inn
                     WHERE {where} ORDER BY c.finish_date, c.price DESC NULLS LAST LIMIT :lim OFFSET :off""",
                 **p, lim=limit, off=offset)
    return {"total": total["n"], "sum": total["sum"], "items": [_clean(r) for r in items]}


EXPORT_COLUMNS = [("inn", "ИНН"), ("name", "Наименование"), ("name_short", "Краткое наименование"),
                  ("segment", "Сегмент"), ("level", "Уровень"), ("inst_type", "Тип учреждения"),
                  ("municipality", "Муниципалитет"), ("address", "Адрес"), ("phone", "Телефон"), ("www", "Сайт"),
                  ("chief", "Руководитель"), ("chief_position", "Должность"), ("founder", "Учредитель"),
                  ("offer", "Что предложить (оценка)")]


@router.get("/export.csv")
def export_csv(segment: list[str] | None = Query(None), level: list[str] | None = Query(None),
               oktmo: list[str] | None = Query(None), q: str | None = None):
    where, p = _where(segment, level, oktmo, q, None, False)
    data = rows(f"SELECT {LIST_COLUMNS} FROM institutions WHERE {where} ORDER BY municipality, segment, name_short", **p)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EXPORT_COLUMNS])
    for r in data:
        w.writerow([r.get(c) or "" for c, _ in EXPORT_COLUMNS])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=gov_institutions.csv"})
