"""Расчёт стоимости проекта мониторинга и диспетчеризации здания (модуль 3 «Калькулятор сделок»).

Формула организаторов (справочники МОД3, коэффициенты — из базы, таблицы calc_items / calc_coefficients):
    оборудование  = Σ цена × кол-во × к_сложности            (+ свои позиции: ПО и нестандарт, с наценкой)
    работы        = оборудование × Σ выбранных этапов          (ПИР 10%, ПНР 15%, шеф-монтаж 5%)
    себестоимость = (оборудование + работы) × к_региона × к_уровня × к_срочности × к_финансирования
    вилка         = себестоимость × (1 + наценка): минимум / оптимум / максимум
    с НДС         = вилка × (1 + НДС)

Всё, чего нет в xlsx (срочность, финансирование, наценки, НДС, типовая комплектация, срок), — ДОПУЩЕНИЯ команды.
Они собраны в ASSUMPTIONS и отдаются в API с пометкой: их значения согласуем с ментором и меняем только здесь.
"""
import math

# Регион приложения → федеральный округ из МОД3_Таб1. Регион — параметр, не хардкод (масштабируемость)
REGION_DISTRICT = {
    "61": "south", "23": "south", "30": "south", "34": "south", "01": "south", "08": "south", "91": "south", "92": "south",
    "77": "center", "50": "center", "78": "northwest", "47": "northwest", "66": "ural_volga", "16": "ural_volga",
    "63": "ural_volga", "52": "ural_volga", "54": "far_east_siberia", "24": "far_east_siberia", "25": "far_east_siberia",
}

ASSUMPTIONS = {
    "markup": {"min": 0.10, "opt": 0.20, "max": 0.30},
    "vat": 0.22,  # НДС 22% с 01.01.2026; прайс МОД3 считаем без НДС
    "custom_markup": 0.15,  # наценка за нестандартное оборудование и ПО (риск и поиск поставщика)
    "urgency": [
        {"code": "standard", "label": "Стандартный срок", "value": 1.00, "speedup": 0.0},
        {"code": "fast", "label": "Ускоренный (срок −25%)", "value": 1.15, "speedup": 0.25},
        {"code": "urgent", "label": "Срочный (срок −50%)", "value": 1.30, "speedup": 0.50},
    ],
    "financing": [
        {"code": "prepay", "label": "Предоплата 100%", "value": 1.00, "note": "деньги до начала работ"},
        {"code": "stages", "label": "Поэтапная оплата 30/40/30", "value": 1.03, "note": "часть работ за свой счёт"},
        {"code": "postpay", "label": "Постоплата (отсрочка 60 дней)", "value": 1.05, "note": "кредитуем клиента"},
        {"code": "installment", "label": "Рассрочка 12 месяцев", "value": 1.10, "note": "стоимость денег и риск неплатежа"},
        {"code": "gov", "label": "Госзаказ (44-ФЗ / 223-ФЗ)", "value": 1.03,
         "note": "оплата после приёмки; цена не выше НМЦК, обеспечение контракта"},
    ],
    # Срок: подготовка + монтаж и наладка по числу точек учёта (бригада ~40 точек в неделю)
    "duration": {"base_weeks": 4, "points_per_week": 40},
}

ASSUMPTION_NOTES = [
    "Наценка: минимум 10%, оптимум 20%, максимум 30% к себестоимости",
    "Прайс МОД3 — без НДС, НДС 22% начисляется сверху",
    "Коэффициенты срочности (×1,15 / ×1,3) и схемы финансирования (×1,0…1,1)",
    "Свои позиции (ПО, нестандартное оборудование): коэффициент сложности 1,0 и наценка 15%",
    "Срок: 4 недели подготовки + 1 неделя на каждые 40 точек",
    "Типовая комплектация по типу объекта и площади — нормы команды, их можно править вручную",
]

# Типовая комплектация: сколько штук на объект (obj) и на 1000 м² (k) — нормы-допущения команды.
# Тип объекта задаёт набор систем и плотность (склад — большая площадь, мало точек; клиника — наоборот).
NORMS = {
    "el_01": (1, 2), "el_02": (1, 0), "el_03": (1, 0),
    "ht_01": (1, 0), "ht_02": (0, 4), "ht_03": (2, 1),
    "ws_01": (1, 0), "ws_02": (2, 0), "ws_03": (0, 4),
    "wo_01": (1, 0), "wo_02": (2, 0), "wo_03": (0, 0),
    "vn_01": (0, 0.5), "vn_02": (0, 5), "vn_03": (0, 0.5),
    "kd_01": (0, 0.3), "kd_02": (0, 5), "kd_03": (0, 0),
    "gs_01": (2, 0.5), "gs_02": (1, 0),
}
OBJECT_TYPES = [
    {"code": "office", "label": "Офис, бизнес-центр", "density": 1.0, "systems": ["el", "ht", "ws", "vn", "kd"]},
    {"code": "retail", "label": "Торговый центр, магазин", "density": 0.8, "systems": ["el", "ht", "ws", "vn", "kd"]},
    {"code": "warehouse", "label": "Склад, логистический центр", "density": 0.3, "systems": ["el", "ht", "ws", "vn"]},
    {"code": "production", "label": "Производство, цех", "density": 0.6, "systems": ["el", "ht", "ws", "wo", "vn", "gs"]},
    {"code": "school", "label": "Школа, детский сад", "density": 1.2, "systems": ["el", "ht", "ws", "vn"]},
    {"code": "clinic", "label": "Поликлиника, больница", "density": 1.3, "systems": ["el", "ht", "ws", "wo", "vn", "kd"]},
    {"code": "residential", "label": "Многоквартирный дом", "density": 0.5, "systems": ["el", "ht", "ws", "wo"]},
    {"code": "agro", "label": "АПК: ферма, теплица, элеватор", "density": 0.4, "systems": ["el", "ht", "ws", "vn", "gs"]},
]


def _by_code(rows: list[dict], code: str, kind: str) -> dict:
    for r in rows:
        if r["code"] == code:
            return r
    raise ValueError(f"неизвестный {kind}: {code}")


def typical_spec(ref: dict, object_type: str, area_m2: float, systems: list[str] | None = None) -> list[dict]:
    """Типовая комплектация: [{id, qty}] по типу объекта, площади и набору систем (по умолчанию — системы типа)."""
    t = _by_code(OBJECT_TYPES, object_type, "тип объекта")
    use = set(systems if systems is not None else t["systems"])
    k = max(area_m2, 0) / 1000 * t["density"]
    out = []
    for item in ref["items"]:
        if item["group_code"] not in use:
            continue
        per_obj, per_k = NORMS.get(item["id"], (0, 0))
        qty = math.ceil(per_obj + per_k * k) if per_obj + per_k * k > 0 else 0
        if qty:
            out.append({"id": item["id"], "qty": qty})
    return out


def estimate(ref: dict, req: dict) -> dict:
    """Расчёт по запросу: items [{id, qty}], custom [{name, price, qty}], region, level, stages, urgency, financing.

    Возвращает каждую промежуточную сумму и коэффициент с источником — чтобы любое число можно было объяснить.
    """
    a = ASSUMPTIONS
    prices = {i["id"]: i for i in ref["items"]}

    lines = []
    for it in req.get("items", []):
        p = prices.get(it["id"])
        qty = max(int(it.get("qty") or 0), 0)
        if not p or not qty:
            continue
        lines.append({**p, "qty": qty, "sum": p["price"] * qty * p["complexity"]})
    custom = []
    for it in req.get("custom", []):
        price, qty = max(float(it.get("price") or 0), 0), max(int(it.get("qty") or 0), 0)
        if price and qty and str(it.get("name") or "").strip():
            custom.append({"name": str(it["name"]).strip()[:200], "price": price, "qty": qty,
                           "sum": price * qty * (1 + a["custom_markup"])})

    equipment_std = sum(l["sum"] for l in lines)
    equipment_custom = sum(c["sum"] for c in custom)
    equipment = equipment_std + equipment_custom

    chosen = req.get("stages")
    stages = [s for s in ref["stages"] if chosen is None or s["code"] in set(chosen)]
    works = [{"code": s["code"], "label": s["label"], "pct": s["value"], "sum": equipment * s["value"]} for s in stages]
    works_total = sum(w["sum"] for w in works)
    subtotal = equipment + works_total

    region = _by_code(ref["regions"], req.get("region") or "south", "регион")
    level = _by_code(ref["levels"], req.get("level") or "basic", "уровень")
    urgency = _by_code(a["urgency"], req.get("urgency") or "standard", "срок")
    financing = _by_code(a["financing"], req.get("financing") or "prepay", "схема оплаты")

    formula_base = subtotal * region["value"] * level["value"]          # «итог» формулы организаторов
    cost = formula_base * urgency["value"] * financing["value"]         # себестоимость с условиями сделки
    fork = {}
    for key, m in a["markup"].items():
        price = cost * (1 + m)
        fork[key] = {"markup": m, "price": price, "profit": price - cost, "margin": (price - cost) / price if price else 0,
                     "price_vat": price * (1 + a["vat"])}

    points = sum(l["qty"] for l in lines) + sum(c["qty"] for c in custom)
    d = a["duration"]
    weeks_std = d["base_weeks"] + math.ceil(points / d["points_per_week"]) if points else 0
    weeks = math.ceil(weeks_std * (1 - urgency["speedup"])) if points else 0

    # Тот же состав на других уровнях — продажнику видно, сколько стоит «апгрейд» решения
    levels = [{"code": l["code"], "label": l["label"], "value": l["value"],
               "opt": subtotal * region["value"] * l["value"] * urgency["value"] * financing["value"] * (1 + a["markup"]["opt"])}
              for l in ref["levels"]]

    return {
        "lines": lines, "custom": custom, "points": points,
        "equipment_std": equipment_std, "equipment_custom": equipment_custom, "equipment": equipment,
        "works": works, "works_total": works_total, "subtotal": subtotal,
        "coefficients": [
            {"kind": "region", "label": f"Регион: {region['label']}", "value": region["value"], "note": region["note"], "source": "МОД3_Таб1"},
            {"kind": "level", "label": f"Уровень: {level['label']}", "value": level["value"], "note": level["note"], "source": "МОД3_Таб2"},
            {"kind": "urgency", "label": urgency["label"], "value": urgency["value"], "note": "надбавка за сжатие срока", "source": "допущение"},
            {"kind": "financing", "label": financing["label"], "value": financing["value"], "note": financing["note"], "source": "допущение"},
        ],
        "formula_base": formula_base, "cost": cost, "fork": fork, "vat": a["vat"],
        "weeks": weeks, "weeks_std": weeks_std, "levels": levels,
        "params": {"region": region["code"], "level": level["code"], "urgency": urgency["code"],
                   "financing": financing["code"], "stages": [s["code"] for s in stages]},
    }
