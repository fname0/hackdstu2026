"""API модуля «Калькулятор сделок»: справочники, типовая комплектация, расчёт вилки, выгрузки и КП в DOCX.

Справочники — таблицы calc_items / calc_coefficients (backend/load/load_calc.py, из листов МОД3 xlsx организаторов).
Расчёт без состояния: клиент присылает параметры, сервер считает (backend/app/services/pricing.py) — в базу не пишем,
поэтому работает и под ролью rt_reader (start.bat).
"""
import csv
import io
import json
import os
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.app.api.radar import cached
from backend.app.db import one, rows
from backend.app.services import kp_docx, pricing

router = APIRouter(prefix="/api/calc", tags=["calc"])


class Item(BaseModel):
    id: str
    qty: int = Field(0, ge=0, le=100000)


class CustomItem(BaseModel):
    name: str = ""
    price: float = Field(0, ge=0, le=1e9)
    qty: int = Field(0, ge=0, le=100000)


class Client(BaseModel):
    name: str = ""
    inn: str = ""
    object_name: str = ""
    address: str = ""
    contact: str = ""
    project_id: str = ""


class EstimateRequest(BaseModel):
    items: list[Item] = []
    custom: list[CustomItem] = []
    region: str | None = None
    level: str = "basic"
    stages: list[str] | None = None
    urgency: str = "standard"
    financing: str = "prepay"
    object_type: str | None = None
    area_m2: float | None = Field(None, ge=0, le=10_000_000)
    client: Client = Client()
    offer: Literal["min", "opt", "max", "custom"] = "opt"
    offer_price: float | None = Field(None, ge=0, description="своя цена без НДС, если offer = custom")


@cached(ttl=300)
def reference() -> dict:
    items = rows("SELECT id, \"group\", group_code, name, unit, price, complexity FROM calc_items ORDER BY sort")
    coefs = rows("SELECT kind, code, label, value, note FROM calc_coefficients ORDER BY kind, sort")
    meta = one("SELECT data FROM meta WHERE name = 'calc_reference'")
    ref = {"items": items, "meta": json.loads(meta["data"]) if meta else None}
    for kind in ("region", "level", "stage"):
        ref[f"{kind}s"] = [{k: c[k] for k in ("code", "label", "value", "note")} for c in coefs if c["kind"] == kind]
    return ref


def _ref() -> dict:
    try:
        return reference()
    except Exception as e:  # таблиц нет — справочники не загружены
        raise HTTPException(503, "Справочники калькулятора не загружены: python -m backend.etl.calc_reference, "
                                 "затем python -m backend.load.load_calc") from e


def _region_default() -> str:
    return pricing.REGION_DISTRICT.get(os.environ.get("REGION", "61"), "south")


def _estimate(req: EstimateRequest) -> dict:
    ref = _ref()
    body = req.model_dump()
    body["region"] = req.region or _region_default()
    try:
        return pricing.estimate(ref, body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/reference")
def get_reference():
    ref = _ref()
    a = pricing.ASSUMPTIONS
    return {**ref, "region_default": _region_default(), "urgency": a["urgency"], "financing": a["financing"],
            "markup": a["markup"], "vat": a["vat"], "custom_markup": a["custom_markup"],
            "object_types": pricing.OBJECT_TYPES, "assumptions": pricing.ASSUMPTION_NOTES}


@router.get("/typical")
def typical(object_type: str, area_m2: float, systems: list[str] | None = Query(None)):
    """Типовая комплектация под тип объекта и площадь (нормы — допущение команды, правятся в интерфейсе)."""
    try:
        return pricing.typical_spec(_ref(), object_type, area_m2, systems)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/estimate")
def estimate(req: EstimateRequest):
    return _estimate(req)


def _offer(req: EstimateRequest, e: dict) -> float:
    if req.offer == "custom" and req.offer_price:
        return req.offer_price
    return e["fork"][req.offer if req.offer != "custom" else "opt"]["price"]


def _filename(prefix: str, req: EstimateRequest, ext: str) -> dict:
    name = f"{prefix}_{(req.client.name or 'клиент')[:40]}_{date.today():%Y%m%d}.{ext}".replace(" ", "_")
    return {"Content-Disposition": f"attachment; filename=calc.{ext}; filename*=UTF-8''{quote(name)}"}


def _rub(v: float) -> str:
    return f"{round(v):,}".replace(",", " ") + " ₽"


def _money(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


@router.post("/export.csv")
def export_csv(req: EstimateRequest):
    """Спецификация и итог расчёта — для таблицы или загрузки в 1С / CRM."""
    e = _estimate(req)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Раздел", "ID", "Наименование", "Ед.", "Кол-во", "Цена, ₽", "Коэф. сложности", "Сумма, ₽", "Источник"])
    for l in e["lines"]:
        w.writerow(["Оборудование", l["id"], l["name"], l["unit"], l["qty"], _money(l["price"]),
                    str(l["complexity"]).replace(".", ","), _money(l["sum"]), "МОД3_Таб4"])
    for c in e["custom"]:
        w.writerow(["ПО и нестандарт", "", c["name"], "шт.", c["qty"], _money(c["price"]),
                    f"наценка {pricing.ASSUMPTIONS['custom_markup']:.0%}", _money(c["sum"]), "ввод менеджера"])
    for wk in e["works"]:
        w.writerow(["Работы", wk["code"], wk["label"], "", "", "", f"{wk['pct']:.0%} от оборудования", _money(wk["sum"]), "МОД3_Таб3"])
    w.writerow([])
    for c in e["coefficients"]:
        w.writerow(["Коэффициент", c["kind"], c["label"], "", "", "", str(c["value"]).replace(".", ","), "", c["source"]])
    w.writerow(["Итог", "", "Себестоимость", "", "", "", "", _money(e["cost"]), "расчёт"])
    for k, label in (("min", "Минимум"), ("opt", "Оптимум"), ("max", "Максимум")):
        f = e["fork"][k]
        w.writerow(["Вилка", k, f"{label} (наценка {f['markup']:.0%}), без НДС", "", "", "", "", _money(f["price"]), "допущение"])
        w.writerow(["Вилка", k, f"{label}, с НДС {e['vat']:.0%}", "", "", "", "", _money(f["price_vat"]), "допущение"])
    offer = _offer(req, e)
    w.writerow(["КП", req.offer, "Цена предложения без НДС", "", "", "", "", _money(offer), "выбор менеджера"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers=_filename("расчёт", req, "csv"))


@router.post("/export/crm")
def export_crm(req: EstimateRequest, format: Literal["amocrm", "bitrix24"] = "amocrm"):
    """Расчёт как сделка: бюджет — цена предложения с НДС, в примечании — состав, коэффициенты и вилка."""
    e = _estimate(req)
    offer = _offer(req, e)
    offer_vat = round(offer * (1 + e["vat"]))
    level = next(l["label"] for l in e["levels"] if l["code"] == e["params"]["level"])
    title = f"{req.client.name or 'Клиент'}: диспетчеризация здания, уровень «{level}»"[:250]
    note = ". ".join([
        f"Расчёт калькулятора сделок РТК от {date.today():%d.%m.%Y}",
        f"Клиент: {req.client.name or '—'} (ИНН {req.client.inn or '—'})",
        f"Объект: {req.client.object_name or '—'}{', ' + req.client.address if req.client.address else ''}",
        f"Оборудование {_rub(e['equipment'])}, работы {_rub(e['works_total'])}",
        "Коэффициенты: " + ", ".join(f"{c['label']} ×{c['value']}" for c in e["coefficients"]),
        f"Вилка без НДС: {_rub(e['fork']['min']['price'])} … {_rub(e['fork']['opt']['price'])} … {_rub(e['fork']['max']['price'])}",
        f"Предложение: {_rub(offer)} без НДС, {_rub(offer_vat)} с НДС",
        f"Срок: {e['weeks']} нед.",
    ]) + "."
    tags = [{"name": "калькулятор сделок РТК"}, {"name": "диспетчеризация"}, {"name": level}]
    if format == "amocrm":
        lead = {"name": title, "price": offer_vat, "_embedded": {"tags": tags}}
        if req.client.name:
            lead["_embedded"]["companies"] = [{"name": req.client.name}]
        payload = {"format": "amoCRM API v4",
                   "how_to_import": "1) POST /api/v4/leads/complex с массивом leads; "
                                    "2) POST /api/v4/leads/notes: entity_id = id созданной сделки",
                   "leads": [lead], "notes": [{"lead_index": 0, "note_type": "common", "params": {"text": note}}]}
    else:
        payload = [{"fields": {"TITLE": title, "OPPORTUNITY": offer_vat, "CURRENCY_ID": "RUB", "COMMENTS": note,
                               "SOURCE_ID": "OTHER", "SOURCE_DESCRIPTION": "Калькулятор сделок РТК",
                               "ORIGINATOR_ID": "rt-calc", "ORIGIN_ID": req.client.project_id or req.client.inn or None},
                    "params": {"REGISTER_SONET_EVENT": "N"}}]
    return JSONResponse(payload, headers=_filename(f"сделка_{format}", req, "json"))


@router.post("/kp")
def kp(req: EstimateRequest, request: Request):
    """Коммерческое предложение в DOCX по бренду РТК: спецификация, итог с НДС, срок, оплата, что не входит в стоимость.
    Подпись — менеджер, который вошёл (профиль: ФИО, должность, телефон, почта)."""
    e = _estimate(req)
    ref = _ref()
    doc = kp_docx.build(req.model_dump(), e, ref, _offer(req, e), pricing.OBJECT_TYPES,
                        manager=getattr(request.state, "user", None))
    return StreamingResponse(iter([doc]), headers=_filename("КП", req, "docx"),
                             media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
