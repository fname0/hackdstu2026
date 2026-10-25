"""API модуля «Инвестиционный навигатор».

Данные — таблица projects (backend/load/load_invest.py): реестр invest-don.ru + проекты из xlsx организаторов.
Отрасль, потребности, потенциал РТК и балл горячести — оценка команды (backend/etl/invest.py, invest_classify.py).
По умолчанию списки показывают только активные проекты (не введён и не приостановлен): их ещё можно продать.
"""
import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.api.radar import _clean, cached
from backend.app.db import one, rows

router = APIRouter(prefix="/api/invest", tags=["invest"])

# Не показываем неподтверждённые госпроекты; исходные записи остаются в БД
VISIBLE = "(sector IS DISTINCT FROM 'government' OR coalesce(stage, '') NOT IN ('стадия не подтверждена', 'стадия уточняется', ''))"

NEEDS = {"it": "ИТ-инфраструктура", "asutp": "АСУ ТП и диспетчеризация", "security": "Безопасность"}
# Окно продаж: решение о подрядчиках связи и автоматики принимается за 6–18 месяцев до ввода
WINDOW = "months_to_launch BETWEEN 6 AND 18 AND is_active"
# «Звонить сейчас»: окно продаж + ИНН инициатора найден + он ещё не клиент РТК. Без ИНН — «через администрацию района»
CALLABLE = f"{WINDOW} AND coalesce(customer_inn, initiator_inn) IS NOT NULL AND client_status <> 'наш клиент'"
VIA_ADMIN = f"{WINDOW} AND coalesce(customer_inn, initiator_inn) IS NULL"

LIST_COLUMNS = """project_id, title, initiator, initiator_inn, client_status, is_interregional, is_key, municipality,
    oktmo, stage, site_status, start_year, finish_year, months_to_launch, sales_window, sum_mln, jobs, industry, needs,
    rtk_potential_mln, hot_score, lat, lon, location_precision, source, in_organizers_sample, url, curator, match_method,
    sector, beneficiary_inn, beneficiary_name, work_type, document_date,
    customer_name, customer_inn, contract_number, contract_status"""

# Ничьи по баллу (у крупных проектов в окне балл упирается в 100) разбиваем суммой проекта
SORTS = {"hot": "hot_score DESC NULLS LAST, sum_mln DESC NULLS LAST", "sum": "sum_mln DESC NULLS LAST",
         "launch": "finish_year NULLS LAST, hot_score DESC", "potential": "rtk_potential_mln DESC NULLS LAST",
         "recent": "modify_date DESC NULLS LAST"}

PROVENANCE = {
    "название, МО, статус, сроки, сумма, рабочие места, инициатор, координаты": "invest-don.ru, реестр инвестпроектов",
    "проекты с отметкой «в выборке организаторов»": "Хакатон_2026_фактура.xlsx",
    "ИНН инициатора": "реестр МСП ФНС (точное совпадение имени) или DaData по названию — уверенность в match_score",
    "наш / не наш клиент": "сверка ИНН с клиентами РТК (МОД1)",
    "стадия, окно продаж": "расчёт по годам ввода и статусу портала на дату выгрузки",
    "отрасль, потребности, что предложить": "правила по тексту проекта, у каждой — цитата (invest_classify.py)",
    "потенциал РТК": "оценка: 3% суммы проекта (условная доля ИТ, связи и автоматики — допущение команды)",
    "балл горячести": "окно продаж 50 + потенциал 30 + ключевой 10 + не наш клиент 10",
}


def _where(stage, status, industry, need, oktmo, client, interregional, key_only, sum_min, sum_max,
           window, active, finish_from, finish_to, bbox, q, source, contact="any", has_inn=False, sector="all"):
    w, p = [VISIBLE], {}
    if sector != "all":
        w.append("sector = :sector"); p["sector"] = sector
    if has_inn:
        w.append("coalesce(customer_inn, initiator_inn) IS NOT NULL")
    if contact == "callable":
        w.append(CALLABLE)
    elif contact == "via_admin":
        w.append(VIA_ADMIN)
    if active:
        w.append("is_active")
    if stage:
        w.append("stage = ANY(:stage)"); p["stage"] = stage
    if status:
        w.append("site_status = ANY(:status)"); p["status"] = status
    if industry:
        w.append("industry = ANY(:industry)"); p["industry"] = industry
    if need:
        w.append("needs && CAST(:need AS text[])"); p["need"] = need
    if oktmo:
        w.append("oktmo = ANY(:oktmo)"); p["oktmo"] = oktmo
    if client == "rtk":
        w.append("client_status = 'наш клиент'")
    elif client == "other":
        w.append("client_status <> 'наш клиент'")
    if interregional:
        w.append("is_interregional")
    if key_only:
        w.append("is_key")
    if sum_min is not None:
        w.append("sum_mln >= :smin"); p["smin"] = sum_min
    if sum_max is not None:
        w.append("sum_mln <= :smax"); p["smax"] = sum_max
    if window:
        w.append(WINDOW)
    if finish_from is not None:
        w.append("finish_year >= :ffrom"); p["ffrom"] = finish_from
    if finish_to is not None:
        w.append("finish_year <= :fto"); p["fto"] = finish_to
    if source:
        w.append("source = :source"); p["source"] = source
    if bbox:
        try:
            x1, y1, x2, y2 = [float(v) for v in bbox.split(",")]
        except ValueError:
            raise HTTPException(400, "bbox: minLon,minLat,maxLon,maxLat")
        w.append("geom && ST_MakeEnvelope(:x1, :y1, :x2, :y2, 4326)"); p.update(x1=x1, y1=y1, x2=x2, y2=y2)
    if q:
        w.append("(initiator_inn = :qe OR customer_inn = :qe OR beneficiary_inn = :qe OR lower(title || ' ' || initiator || ' ' || coalesce(beneficiary_name,'') || ' ' || coalesce(customer_name,'')) LIKE :ql)")
        p.update(qe=q.strip(), ql=f"%{q.strip().lower()}%")
    return " AND ".join(w), p


def _filters(stage: list[str] | None = Query(None), status: list[str] | None = Query(None, description="статус портала"),
             industry: list[str] | None = Query(None), need: list[Literal["it", "asutp", "security"]] | None = Query(None),
             oktmo: list[str] | None = Query(None), client: Literal["all", "rtk", "other"] = "all",
             interregional: bool = False, key_only: bool = False,
             has_inn: bool = Query(False, description="только проекты с найденным ИНН инициатора или заказчика"),
             sum_min: float | None = Query(None, description="млн ₽"), sum_max: float | None = Query(None, description="млн ₽"),
             window: bool = Query(False, description="только 6–18 мес. до ввода"),
             active: bool = Query(True, description="без введённых и приостановленных"),
             finish_from: int | None = None, finish_to: int | None = None, bbox: str | None = None,
             q: str | None = None, source: Literal["invest-don.ru", "xlsx организаторов", "Госпрограммы РО"] | None = None,
             sector: Literal["all", "government", "private"] = "all",
             contact: Literal["any", "callable", "via_admin"] = Query("any", description="callable — «Звонить сейчас», via_admin — окно продаж без ИНН")):
    return _where(stage, status, industry, need, oktmo, client, interregional, key_only, sum_min, sum_max,
                  window, active, finish_from, finish_to, bbox, q, source, contact, has_inn, sector)


def _row(r: dict) -> dict:
    r = _clean(r)
    if "needs" in r:
        r["needs"] = list(r["needs"] or [])
    return r


@router.get("/summary")
@cached()
def summary():
    s = one(f"""SELECT count(*) AS projects,
                       count(*) FILTER (WHERE is_active) AS active,
                       sum(sum_mln) FILTER (WHERE is_active) AS active_sum_mln,
                       sum(rtk_potential_mln) FILTER (WHERE is_active) AS active_potential_mln,
                       count(*) FILTER (WHERE {WINDOW}) AS in_window,
                       sum(sum_mln) FILTER (WHERE {WINDOW}) AS in_window_sum_mln,
                       count(*) FILTER (WHERE is_active AND is_interregional) AS interregional_active,
                       count(*) FILTER (WHERE is_interregional) AS interregional,
                       count(*) FILTER (WHERE client_status = 'наш клиент') AS rtk_clients,
                       count(*) FILTER (WHERE is_active AND client_status <> 'наш клиент'
                                        AND initiator_inn IS NOT NULL) AS active_new_with_inn,
                       count(*) FILTER (WHERE initiator_inn IS NOT NULL) AS with_inn,
                       count(*) FILTER (WHERE in_organizers_sample) AS organizers_sample,
                       count(DISTINCT initiator_inn) FILTER (WHERE is_active) AS active_initiators
                FROM projects WHERE {VISIBLE}""")
    by = lambda col, where="true": rows(
        f"SELECT {col} AS key, count(*) AS n, sum(sum_mln) AS sum_mln FROM projects WHERE ({where}) AND {VISIBLE} GROUP BY 1 ORDER BY n DESC")
    needs = rows(f"""SELECT unnest(needs) AS key, count(*) AS n, sum(rtk_potential_mln) AS potential_mln
                    FROM projects WHERE is_active AND {VISIBLE} GROUP BY 1 ORDER BY n DESC""")
    top = rows(f"SELECT {LIST_COLUMNS} FROM projects WHERE is_active AND {VISIBLE} ORDER BY hot_score DESC NULLS LAST LIMIT 10")
    meta = {r["name"]: json.loads(r["data"]) for r in rows("SELECT name, data FROM meta WHERE name LIKE 'invest%' OR name LIKE 'projects%'")}
    return _clean({**s, "by_stage": [_clean(r) for r in by("stage")],
                   "by_industry": [_clean(r) for r in by("industry", "is_active")],
                   "by_need": [{**_clean(r), "label": NEEDS.get(r["key"], r["key"])} for r in needs],
                   "top": [_row(r) for r in top],
                   "list_requested_at": meta.get("invest_don_61", {}).get("list_requested_at"),
                   "built_at": meta.get("projects_don_61", {}).get("built_at"),
                   "sources": "invest-don.ru, госпрограммы Ростовской области, Хакатон_2026_фактура.xlsx, ФНС, bus.gov.ru, DaData"})


@router.get("/stats")
def stats(f: tuple = Depends(_filters)):
    """KPI-плитки под текущие фильтры: те же показатели, что в summary, но по отфильтрованным проектам."""
    where, p = f
    return _clean(one(f"""SELECT count(*) AS projects,
                                 sum(sum_mln) AS sum_mln,
                                 count(*) FILTER (WHERE {WINDOW}) AS in_window,
                                 sum(sum_mln) FILTER (WHERE {WINDOW}) AS in_window_sum_mln,
                                 count(*) FILTER (WHERE is_interregional) AS interregional,
                                 sum(rtk_potential_mln) AS potential_mln,
                                 count(*) FILTER (WHERE client_status = 'наш клиент') AS rtk_clients,
                                 count(*) FILTER (WHERE coalesce(customer_inn,initiator_inn) IS NOT NULL) AS with_inn,
                                 count(*) FILTER (WHERE {CALLABLE}) AS callable,
                                 count(*) FILTER (WHERE {VIA_ADMIN}) AS via_admin,
                                 count(*) FILTER (WHERE sector = 'government') AS government
                          FROM projects WHERE {where}""", **p))


@router.get("/facets")
@cached()
def facets():
    """Значения для фильтров с количеством активных проектов."""
    f = lambda col: [_clean(r) for r in rows(
        f"""SELECT {col} AS key, count(*) AS n, count(*) FILTER (WHERE is_active) AS active
            FROM projects WHERE {col} IS NOT NULL AND {VISIBLE} GROUP BY 1 ORDER BY n DESC""")]
    return {"stage": f("stage"), "status": f("site_status"), "industry": f("industry"),
            "municipality": [_clean(r) for r in rows(
                f"""SELECT oktmo AS key, municipality AS label, count(*) AS n, count(*) FILTER (WHERE is_active) AS active
                   FROM projects WHERE oktmo IS NOT NULL AND {VISIBLE} GROUP BY 1, 2 ORDER BY n DESC""")],
            "sector": f("sector"),
            "need": [{"key": k, "label": v} for k, v in NEEDS.items()],
            "years": one(f"SELECT min(finish_year) AS min, max(finish_year) AS max FROM projects WHERE {VISIBLE}"),
            "sum_mln": one(f"SELECT min(sum_mln) AS min, max(sum_mln) AS max FROM projects WHERE {VISIBLE}")}


@router.get("/projects")
def projects(f: tuple = Depends(_filters), sort: Literal["hot", "sum", "launch", "potential", "recent"] = "hot",
             limit: int = Query(50, le=500), offset: int = 0):
    where, p = f
    total = one(f"SELECT count(*) AS n, sum(sum_mln) AS sum_mln FROM projects WHERE {where}", **p)
    items = rows(f"SELECT {LIST_COLUMNS} FROM projects WHERE {where} ORDER BY {SORTS[sort]} LIMIT :lim OFFSET :off",
                 **p, lim=limit, off=offset)
    return {"total": total["n"], "sum_mln": _clean(total)["sum_mln"], "items": [_row(r) for r in items]}


@router.get("/points")
def points(f: tuple = Depends(_filters), limit: int = Query(5000, le=5000)):
    """Лёгкие точки для слоя карты: размер — сумма, цвет — стадия."""
    where, p = f
    data = rows(f"""SELECT project_id, lat, lon, stage, months_to_launch, sum_mln, hot_score, industry, title, coalesce(customer_name, initiator) AS initiator,
                           location_precision, sector
                    FROM projects WHERE {where} AND geom IS NOT NULL ORDER BY hot_score DESC NULLS LAST LIMIT :lim""",
                **p, lim=limit)
    return [_clean(r) for r in data]


GANTT_SORTS = {"hot": "hot_score DESC NULLS LAST, finish_year", "launch": "finish_year, hot_score DESC NULLS LAST",
               "start": "start_year NULLS LAST, finish_year, hot_score DESC NULLS LAST", "sum": "sum_mln DESC NULLS LAST"}


@router.get("/timeline")
def timeline(f: tuple = Depends(_filters), gantt_limit: int = Query(60, le=300),
             gantt_sort: Literal["hot", "launch", "start", "sum"] = "hot"):
    """Диаграмма Ганта инвестсобытий: полосы «начало → ввод» по проектам под фильтром + вводы по годам.
    В реестре сроки только годами, поэтому шаг — год, а не квартал."""
    where, p = f
    years = rows(f"""SELECT finish_year AS year, count(*) AS n, sum(sum_mln) AS sum_mln,
                            count(*) FILTER (WHERE {WINDOW}) AS in_window
                     FROM projects WHERE {where} AND finish_year IS NOT NULL GROUP BY 1 ORDER BY 1""", **p)
    # «Скоро ввод»: срок ввода уже прошёл, а проект не введён — в начале такой сортировки он только мешает
    overdue = " AND finish_year >= extract(year FROM now())" if gantt_sort == "launch" else ""
    total = one(f"SELECT count(*) AS n FROM projects WHERE {where} AND finish_year IS NOT NULL{overdue}", **p)["n"]
    gantt = rows(f"""SELECT project_id, title, coalesce(customer_name, initiator) AS initiator, municipality, start_year, finish_year, stage, months_to_launch,
                            sum_mln, hot_score, is_interregional, client_status
                     FROM projects WHERE {where} AND finish_year IS NOT NULL{overdue}
                     ORDER BY {GANTT_SORTS[gantt_sort]} LIMIT :lim""", **p, lim=gantt_limit)
    return {"years": [_clean(r) for r in years], "gantt": [_clean(r) for r in gantt], "gantt_total": total,
            "window_months": [6, 18]}


@router.get("/projects/{project_id}")
def project(project_id: str):
    r = one(f"SELECT * FROM projects WHERE project_id = :id AND {VISIBLE}", id=project_id)
    if not r:
        raise HTTPException(404, "проект не найден")
    r.pop("geom", None)
    r = _row(r)
    company = None
    if r["initiator_inn"]:
        company = one("""SELECT inn, name_short, kind, industry, municipality, is_rtk_client, lead_score, income_2025
                         FROM companies WHERE inn = :inn""", inn=r["initiator_inn"])
    related_inn = r.get("customer_inn") or r["initiator_inn"]
    same = rows(f"""SELECT {LIST_COLUMNS} FROM projects
                    WHERE coalesce(customer_inn,initiator_inn) = :inn AND project_id <> :id AND {VISIBLE} ORDER BY hot_score DESC NULLS LAST LIMIT 20""",
                inn=related_inn, id=project_id) if related_inn else []
    provenance = dict(PROVENANCE)
    if r.get("source") == "Госпрограммы РО":
        provenance = {
            "объект, сметная стоимость, плановый срок": "таблица госпрограммы; дата документа указана в карточке",
            "стадия": r.get("stage_basis") or "не подтверждена; финансирование не доказывает фактический ход работ",
            "заказчик, контракт, подрядчик": "ЕИС, предмет работ и адрес сопоставлены с объектом; ссылка на контракт в карточке",
            "учреждение-получатель": "единственное совпадение названия с bus.gov.ru; это не подтверждение заказчика",
            "потребности": "гипотеза по виду работ; состав закупки нужно проверить",
            "потенциал РТК": "условные 3% сметы только при комплексных работах; оценка команды",
        }
    customer_available = bool(r.get("customer_inn") and one("SELECT inn FROM institutions WHERE inn = :inn", inn=r["customer_inn"]))
    return {**r, "company": _clean(company) if company else None, "initiator_other_projects": [_row(x) for x in same],
            "customer_institution_available": customer_available,
            "provenance": provenance}


@router.get("/companies/{inn}/projects")
def company_projects(inn: str):
    """Инвестпроекты компании — для карточки компании в радаре."""
    return [_row(r) for r in rows(
        f"SELECT {LIST_COLUMNS} FROM projects WHERE initiator_inn = :inn AND {VISIBLE} ORDER BY is_active DESC, hot_score DESC NULLS LAST",
        inn=inn)]


EXPORT_COLUMNS = [("project_id", "ID"), ("title", "Проект"), ("initiator", "Инициатор"), ("initiator_inn", "ИНН инициатора"),
                  ("client_status", "Клиент РТК"), ("is_interregional", "Межрегиональный игрок"),
                  ("municipality", "Муниципалитет"), ("industry", "Отрасль"), ("needs_label", "Потребности РТК"),
                  ("offers", "Что предложить"), ("stage", "Стадия"), ("site_status", "Статус на портале"),
                  ("start_year", "Начало"), ("finish_year", "Ввод"), ("months_to_launch", "Мес. до ввода"),
                  ("sales_window", "Окно продаж"), ("sum_mln", "Сумма, млн ₽"), ("jobs", "Рабочих мест"),
                  ("rtk_potential_mln", "Потенциал РТК, млн ₽ (оценка)"), ("hot_score", "Балл горячести"),
                  ("sector", "Сектор"), ("beneficiary_name", "Учреждение-получатель"),
                  ("beneficiary_inn", "ИНН получателя"), ("work_type", "Вид работ"),
                  ("document_date", "Дата документа"), ("source", "Источник"), ("url", "Ссылка")]
EXPORT_COLUMNS += [("customer_name", "Заказчик ЕИС"), ("customer_inn", "ИНН заказчика"),
                   ("contract_work_address", "Место работ по контракту"),
                   ("contract_number", "Контракт ЕИС"), ("contract_status", "Статус контракта"),
                   ("contract_signed", "Дата контракта"), ("contract_finish", "Срок контракта"),
                   ("contract_amount_rub", "Цена контракта, ₽"), ("contractor_name", "Подрядчик"),
                   ("contractor_inn", "ИНН подрядчика"), ("stage_basis", "Основание стадии"),
                   ("stage_evidence_url", "Ссылка ЕИС"), ("stage_checked_at", "Дата проверки ЕИС")]


def _export_rows(where, p, limit):
    data = rows(f"""SELECT *, (SELECT string_agg(d->>'label', ', ') FROM jsonb_array_elements(needs_detail) d) AS needs_label,
                           (SELECT string_agg(d->>'offer', '; ') FROM jsonb_array_elements(needs_detail) d) AS offers
                    FROM projects WHERE {where} ORDER BY hot_score DESC NULLS LAST LIMIT :lim""", **p, lim=limit)
    for r in data:
        r.pop("geom", None)
    return [_row(r) for r in data]


def _csv_value(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Да" if v else "Нет"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:.1f}".replace(".", ",")
    return v


@router.get("/export.csv")
def export_csv(f: tuple = Depends(_filters), limit: int = Query(5000, le=5000)):
    where, p = f
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EXPORT_COLUMNS])
    for r in _export_rows(where, p, limit):
        w.writerow([_csv_value(r.get(c)) for c, _ in EXPORT_COLUMNS])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=invest_projects.csv"})


@router.get("/export/crm")
def export_crm(f: tuple = Depends(_filters), format: Literal["amocrm", "bitrix24"] = "amocrm",
               limit: int = Query(5000, le=5000)):
    """Проекты как сделки для CRM (те же фильтры и порядок, что у CSV).

    amoCRM (API v4): `leads` — тело для POST /api/v4/leads/complex (сделка + вложенная компания-инициатор; бюджет —
        потенциал РТК в рублях, теги — потребности); `notes` — примечание с обоснованием для POST /api/v4/leads/notes
        по `lead_index`.
    Bitrix24: вызовы crm.deal.add; OPPORTUNITY — потенциал РТК, ORIGIN_ID — ID проекта для дедупликации.
    """
    where, p = f
    data = _export_rows(where, p, limit)

    def note(r):
        parts = [f"Инвестпроект: {r['title']}", f"Инициатор: {r['initiator']} (ИНН {r['initiator_inn'] or 'не найден'})",
                 f"Муниципалитет: {r['municipality'] or '—'}", f"Стадия: {r['stage']}, ввод {r['finish_year'] or '—'}",
                 f"Окно продаж: {r['sales_window']}", f"Сумма проекта: {_csv_value(r['sum_mln'])} млн ₽",
                 f"Потребности: {r['needs_label'] or '—'}", f"Что предложить: {r['offers'] or '—'}",
                 f"Потенциал РТК (оценка): {_csv_value(r['rtk_potential_mln'])} млн ₽",
                 f"Источник: {r['source']} {r['url'] or ''}".strip()]
        if r.get("beneficiary_name"):
            parts.append(f"Учреждение-получатель: {r['beneficiary_name']} (ИНН {r['beneficiary_inn']}); заказчик уточняется")
        if r.get("source_detail"):
            parts.append((r.get("stage_basis") or "Стадия не подтверждена") + "; дата документа " + str(r.get("document_date") or "—"))
        if r.get("customer_inn"):
            parts.append(f"Заказчик: {r['customer_name']} (ИНН {r['customer_inn']}); контракт {r['contract_number']}, {r['contract_status']}; {r.get('stage_basis') or ''}; {r.get('stage_evidence_url') or ''}")
        return ". ".join(parts) + ". Инвестнавигатор РТК."

    def budget(r):
        return int(round((r["rtk_potential_mln"] or 0) * 1e6))

    def tags(r):
        return [{"name": "инвестнавигатор РТК"}, {"name": r["industry"]}] + [{"name": NEEDS[n]} for n in r["needs"] if n in NEEDS]

    if format == "amocrm":
        payload = {
            "format": "amoCRM API v4",
            "how_to_import": "1) POST /api/v4/leads/complex с массивом leads (до 50 за запрос); "
                             "2) POST /api/v4/leads/notes: entity_id = id созданной сделки с тем же lead_index",
            "leads": [{"name": f"{r.get('customer_name') or r['initiator']}: {r['title'][:200]}", "price": budget(r),
                       "_embedded": {"tags": tags(r), "companies": [{"name": r.get("customer_name") or r["initiator"]}]}} for r in data],
            "notes": [{"lead_index": i, "note_type": "common", "params": {"text": note(r)}} for i, r in enumerate(data)],
        }
    else:
        payload = [{"fields": {"TITLE": f"{r.get('customer_name') or r['initiator']}: {r['title'][:200]}", "OPPORTUNITY": budget(r),
                               "CURRENCY_ID": "RUB", "COMMENTS": note(r), "SOURCE_ID": "OTHER",
                               "SOURCE_DESCRIPTION": "Инвестнавигатор РТК", "ORIGINATOR_ID": "rt-invest",
                               "ORIGIN_ID": r["project_id"]},
                    "params": {"REGISTER_SONET_EVENT": "N"}} for r in data]
    return JSONResponse(payload, headers={"Content-Disposition": f"attachment; filename=invest_{format}.json"})


